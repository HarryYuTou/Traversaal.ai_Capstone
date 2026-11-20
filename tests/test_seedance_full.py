"""Full-footage composition and compatibility checks; no live model requests."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capstone_video import MODEL_ID, OUTPUT_SIZES, VideoError
from capstone_video.composition import full_video_timeline, require_full_coverage
from capstone_video.pipeline import check_plan, generate_clips, integrate_clips
from capstone_video.planning import atomic_json, candidate_scenes, plan_clips, validate_directions
from capstone_web.jobs import JobStore, RequestError, validate_request
from capstone_web.worker import generate
from capstone_script.scene_plan import dump_plan, load_plan
from tests.test_seedance import ROOT, PROMPT, FakeProvider, fake_normalize, fixture, request


class FullVideoTests(unittest.TestCase):
    def test_cards_become_footage_without_moving_narration_or_changing_animation(self):
        _, original = fixture()
        original.update(width=1920, height=1080, titleFrames=60, chapters=[{"from": 180, "cardFrames": 45}])
        for scene in original["scenes"][1:]:
            scene["from"] += 45
            for line in scene["lines"]:
                line["from"] += 45
        original["durationInFrames"] += 45
        original["durationSeconds"] = original["durationInFrames"] / 30
        original["scenes"][1]["lines"][0]["highlightQuote"] = True
        saved = copy.deepcopy(original)
        for resolution, dimensions in OUTPUT_SIZES.items():
            result = full_video_timeline(original, resolution)
            self.assertEqual((result["width"], result["height"]), dimensions)
            self.assertEqual(result["titleFrames"], 0)
            self.assertEqual(result["chapters"], [])
            self.assertEqual([(s["from"], s["durationInFrames"]) for s in result["scenes"]],
                             [(0, 180), (180, 165), (345, 120)])
            self.assertEqual(result["audio"], original["audio"])
            self.assertEqual(result["durationSeconds"], original["durationSeconds"])
            self.assertEqual([l["from"] for s in result["scenes"] for l in s["lines"]],
                             [l["from"] for s in original["scenes"] for l in s["lines"]])
            self.assertNotIn("highlightQuote", result["scenes"][1]["lines"][0])
        self.assertEqual(original, saved)

    def test_full_candidates_include_formerly_protected_visuals(self):
        source = load_plan(ROOT / "fixtures/scene-plan.valid.json")
        timeline = {"fps": 30, "scenes": [{"id": s.id, "durationInFrames": 120, "lines": []}
                                          for s in source.scenes]}
        self.assertLess(len(candidate_scenes(source, timeline, 120)), len(source.scenes))
        candidates = candidate_scenes(source, timeline, 4, full_video=True)
        self.assertEqual([c["sceneId"] for c in candidates], [s.id for s in source.scenes])
        directions = {"style": "Consistent scientific illustration with gentle lighting.", "scenes": [
            {"sceneId": c["sceneId"], "prompts": [PROMPT for _ in c["slots"]]} for c in candidates]}
        validate_directions(directions, candidates, full_video=True)
        directions["scenes"][0]["prompts"] = []
        with self.assertRaises(ValueError):
            validate_directions(directions, candidates, full_video=True)
        directions["scenes"][0]["useVideo"] = False
        with self.assertRaises(ValueError):
            validate_directions(directions, candidates, full_video=True)

    def test_ten_minute_plan_covers_every_frame_without_legacy_seconds_cap(self):
        source, timeline = fixture()
        for i, scene in enumerate(timeline["scenes"]):
            scene.update({"from": i * 6000, "durationInFrames": 6000})
        timeline.update(durationInFrames=18000, durationSeconds=600)
        timeline = full_video_timeline(timeline, "720p")
        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_clips(tmp, source, timeline, full_video=True, sample=True, resolution="720p")
            check_plan(plan)
            require_full_coverage(timeline, plan)
            self.assertEqual(plan["requestedSeconds"], 600)
            self.assertEqual(plan["maxGeneratedSeconds"], 1200)
            self.assertEqual(sum(s["durationInFrames"] for s in plan["shots"]), 18000)
            self.assertEqual(plan["model"], MODEL_ID)
            self.assertEqual(plan_clips(tmp, source, timeline, full_video=True, sample=True,
                                        resolution="720p", max_seconds=4), plan)

    def test_full_director_batches_long_topics_with_one_shared_style(self):
        source, timeline = fixture()
        for i, scene in enumerate(timeline["scenes"]):
            scene.update({"from": i * 1800, "durationInFrames": 1800})
        timeline.update(durationInFrames=5400, durationSeconds=180)
        timeline = full_video_timeline(timeline, "480p")
        batches = []
        style = "Consistent scientific illustration with gentle lighting."
        def direct(client, system, payload, schema, review, *args, **kwargs):
            payload = json.loads(payload)
            batches.append(payload)
            self.assertEqual(payload["sharedStyle"], "" if len(batches) == 1 else style)
            self.assertNotIn("useVideo", schema["properties"]["scenes"]["items"]["properties"])
            result = {"style": style, "scenes": [{"sceneId": c["sceneId"],
                      "prompts": [PROMPT] * len(c["slots"])} for c in payload["candidates"]]}
            verified, errors = review(json.dumps(result))
            self.assertEqual(errors, [])
            return verified
        with tempfile.TemporaryDirectory() as tmp, patch("capstone_script.planner.request_json", side_effect=direct):
            plan = plan_clips(tmp, source, timeline, full_video=True, client=object())
            require_full_coverage(timeline, plan)
            self.assertEqual(len(batches), 3)
            self.assertTrue(all(s["prompt"].startswith(style) for s in plan["shots"]))

    def test_partial_coverage_is_rejected_and_completed_clips_cover_both_ends(self):
        source, original = fixture()
        timeline = full_video_timeline(original, "480p")
        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_clips(tmp, source, timeline, full_video=True, sample=True)
            for mutation in (lambda p: p["shots"].pop(),
                             lambda p: p["shots"][0].update(offsetFrames=1),
                             lambda p: p["shots"][0].update(durationInFrames=179)):
                broken = copy.deepcopy(plan)
                mutation(broken)
                with self.assertRaises(VideoError):
                    require_full_coverage(timeline, broken)
            provider = FakeProvider()
            manifest = generate_clips(tmp, plan, provider, normalize_clip=fake_normalize)
            result = integrate_clips(tmp, timeline, plan, manifest)
            self.assertTrue(all(s["template"] == "generated-video" for s in result["scenes"]))
            self.assertEqual(result["generatedVideo"]["coverage"], "full")
            self.assertEqual(result["generatedVideo"]["seconds"], 14)
            for frame in range(result["durationInFrames"]):
                active = [c for s in result["scenes"] for c in s["visual"]["clips"]
                          if s["from"] + c["from"] <= frame < s["from"] + c["from"] + c["durationInFrames"]]
                self.assertEqual(len(active), 1, f"frame {frame}")

    def test_retry_is_explicit_and_still_bounded_in_full_video_mode(self):
        source, original = fixture()
        with tempfile.TemporaryDirectory() as tmp:
            plan = plan_clips(tmp, source, full_video_timeline(original, "480p"), full_video=True, sample=True)
            provider = FakeProvider()
            provider.status = "failed"
            for retry in (False, False, True, True):
                with self.assertRaises(VideoError):
                    generate_clips(tmp, plan, provider, retry_failed=retry, normalize_clip=fake_normalize)
            self.assertEqual(len(provider.posts), 2)

    def test_new_requests_have_one_quality_and_version_while_animation_is_unchanged(self):
        seedance = request(source="topic", durationSeconds=600, videoResolution="720p", draft=True,
                           theme="night", minimumDurationSec=420)
        self.assertEqual((seedance["draft"], seedance["theme"], seedance["minimumDurationSec"]), (False, "light", 0))
        self.assertNotIn("maxGeneratedSeconds", seedance)
        self.assertEqual(validate_request(seedance), seedance)
        with self.assertRaisesRegex(RequestError, "Refresh"):
            request(maxGeneratedSeconds=60)
        animation = request(source="topic", visualMode="animation", durationSeconds=600, draft=True,
                            theme="night", minimumDurationSec=420)
        self.assertEqual((animation["draft"], animation["theme"], animation["minimumDurationSec"]), (True, "night", 420))
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp)
            full = store.create(seedance)
            self.assertEqual(full["pipelineVersion"], 2)
            self.assertNotIn("pipelineVersion", store.create(animation))
            # A persisted pre-change job must keep its original hybrid interpretation on resume.
            legacy = copy.deepcopy(full)
            legacy.pop("pipelineVersion")
            legacy["status"] = "failed"
            legacy["request"]["maxGeneratedSeconds"] = 60
            atomic_json(Path(tmp) / full["id"] / "job.json", legacy)
            loaded = JobStore(tmp).get(full["id"])
            self.assertNotIn("pipelineVersion", loaded)
            self.assertEqual(loaded["request"]["maxGeneratedSeconds"], 60)

    def test_full_worker_resumes_local_render_without_repaying_or_renarrating(self):
        source, original = fixture()
        provider = FakeProvider()
        def prepare(request, output, minimum, update, *, full_video=False):
            self.assertTrue(full_video)
            self.assertEqual(minimum, 0)
            output.mkdir()
            (output / "scene-plan.json").write_text(dump_plan(source))
            atomic_json(output / "audio-manifest.json", {})
            atomic_json(output / "video/timeline.json", original)
            for name in ("narration.wav", "subtitles.vtt", "subtitles.srt"):
                (output / "video" / name).write_bytes(b"synthetic-test-data")
            return source, None, None
        def render(output, **kwargs):
            self.assertFalse(kwargs["draft"])
            timeline = json.loads((output / "video/timeline.json").read_text())
            self.assertEqual((timeline["width"], timeline["height"]), (1280, 720))
            self.assertEqual(timeline["visualMode"], "seedance-full")
            self.assertEqual(timeline["titleFrames"], 0)
            self.assertEqual(timeline["chapters"], [])
            self.assertTrue(all(s["template"] == "generated-video" for s in timeline["scenes"]))
            return {"probedSeconds": 14, "width": 1280, "height": 720, "bytes": 1000}
        def clips(*args, **kwargs):
            return generate_clips(*args, **kwargs, normalize_clip=fake_normalize)
        with tempfile.TemporaryDirectory() as tmp, patch("capstone_web.worker.prepare_narration", side_effect=prepare) as narration, \
                patch("capstone_script.planner.load_env_file"), \
                patch("capstone_video.provider.ArkVideoClient", return_value=provider), \
                patch("capstone_video.pipeline.generate_clips", side_effect=clips), \
                patch("capstone_script.render.render_video", side_effect=RuntimeError("render stopped")) as rendering:
            job = {"id": "test-full", "pipelineVersion": 2, "request": request(videoResolution="720p")}
            with self.assertRaises(RuntimeError):
                generate(job, Path(tmp), lambda event: None)
            rendering.side_effect = render
            result = generate({**job, "resumeCount": 1}, Path(tmp), lambda event: None)
            self.assertEqual(result["generatedVideo"]["coverage"], "full")
            self.assertEqual(result["generatedVideo"]["model"], MODEL_ID)
            self.assertEqual(len(provider.posts), 3)
            self.assertTrue(all(post[2] == "720p" for post in provider.posts))
            narration.assert_called_once()


if __name__ == "__main__":
    unittest.main()
