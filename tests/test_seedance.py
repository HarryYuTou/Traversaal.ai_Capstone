"""Offline paid-request safety, recovery, timing and media tests. Never contacts Ark."""

import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import wave
import zlib

import httpx

from capstone_video import MODEL_ID, SubmissionUnknown, VideoError
from capstone_video.provider import ArkVideoClient
from capstone_video.planning import atomic_json, digest, plan_clips, candidate_scenes, validate_directions
from capstone_video.pipeline import file_digest, generate_clips, integrate_clips, normalize, probe
from capstone_web.jobs import JobStore, RequestError, validate_request
from capstone_web.worker import generate
from capstone_script.scene_plan import dump_plan, load_plan

ROOT = Path(__file__).resolve().parents[1]
PROMPT = "Close-up of clear water droplets forming on the outside of a cold glass."


def request(**extra):
    return validate_request({"topic": "Cold glass", "audience": "Adults", "durationSeconds": 30,
                             "source": "sample", "visualMode": "seedance", **extra})


def fixture():
    source = load_plan(ROOT / "fixtures/scene-plan.seedance-glass.json")
    timeline = {"fps": 30, "title": source.title, "durationInFrames": 420, "durationSeconds": 14,
                "audio": {"path": "narration.wav"}, "scenes": []}
    for i, scene in enumerate(source.scenes):
        timeline["scenes"].append({"id": scene.id, "template": scene.template,
            "visual": scene.visual.model_dump(mode="json"), "from": 60 + i * 120, "durationInFrames": 120,
            "lines": [{"id": line.id, "text": line.text, "from": 66 + i * 120} for line in scene.narration]})
    return source, timeline


def fake_normalize(source, target, frames, fps):
    target.write_bytes(b"verified-test-video" + str(frames).encode())
    return {"duration": frames / fps, "frames": frames, "sha256": file_digest(target), "audioStreams": 0}


class FakeProvider:
    def __init__(self):
        self.posts, self.polls, self.downloads = [], [], []
        self.status = "succeeded"
        self.failure = None
        self.preflight = Mock()

    def close(self):
        pass

    def submit(self, *args):
        self.posts.append(args)
        if self.failure:
            raise self.failure
        return "task-" + str(len(self.posts))

    def get(self, task_id):
        self.polls.append(task_id)
        return {"id": task_id, "model": MODEL_ID, "status": self.status,
                "content": {"video_url": "https://test.volces.com/video"},
                "usage": {"completion_tokens": 1000}}

    def download(self, url, path):
        self.downloads.append(url)
        path.write_bytes(b"source-video")


class ProviderTests(unittest.TestCase):
    def client(self, handler):
        with patch.dict(os.environ, {"ARK_VIDEO_MODEL": MODEL_ID}):
            client = ArkVideoClient("unit-test-secret", transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        return client

    def test_exact_model_body_and_api_host(self):
        seen = []
        client = self.client(lambda req: (seen.append(req), httpx.Response(200, json={"id": "task-1"}))[1])
        self.assertEqual(client.submit(PROMPT, 6, "480p", 123), "task-1")
        body = json.loads(seen[0].content)
        self.assertEqual(body["model"], MODEL_ID)
        self.assertEqual(body["duration"], 6)
        self.assertEqual(body["resolution"], "480p")
        self.assertFalse(body["generate_audio"])
        self.assertFalse(body["watermark"])
        self.assertEqual(str(seen[0].url), "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks")

    def test_mismatched_model_configuration_and_response_rejected(self):
        with patch.dict(os.environ, {"ARK_VIDEO_MODEL": "more-expensive-model"}), self.assertRaises(VideoError):
            ArkVideoClient("test")
        client = self.client(lambda _: httpx.Response(200, json={"status": "succeeded", "model": "wrong"}))
        with self.assertRaises(VideoError):
            client.get("task-1")

    def test_post_timeout_server_error_and_invalid_body_never_retry(self):
        for response in (httpx.Response(503, json={}), httpx.Response(200, text="bad"), httpx.Response(200, json={})):
            calls = []
            client = self.client(lambda req: (calls.append(req), response)[1])
            with self.assertRaises(SubmissionUnknown):
                client.submit(PROMPT, 4, "480p", 1)
            self.assertEqual(len(calls), 1)
        client = self.client(Mock(side_effect=httpx.ReadTimeout("secret")))
        with self.assertRaises(SubmissionUnknown) as caught:
            client.submit(PROMPT, 4, "480p", 1)
        self.assertNotIn("secret", str(caught.exception))

    def test_auth_and_quota_errors_are_safe_and_no_fallback(self):
        for code in (400, 401, 403, 404, 429):
            client = self.client(lambda _, code=code: httpx.Response(code, json={"error": {"message": "secret"}}))
            with self.assertRaises(VideoError) as caught:
                client.submit(PROMPT, 4, "480p", 1)
            self.assertNotIsInstance(caught.exception, SubmissionUnknown)
            self.assertNotIn("secret", str(caught.exception))

    def test_download_is_separate_and_partial_download_is_cleaned(self):
        client = self.client(lambda _: httpx.Response(200, json={}))
        with tempfile.TemporaryDirectory() as tmp, patch("capstone_video.provider.httpx.stream") as stream:
            stream.return_value.__enter__.return_value = httpx.Response(200, content=b"x" * 200)
            target = Path(tmp) / "clip.mp4"
            client.download("https://test.volces.com/video?signature=private", target)
            self.assertEqual(target.stat().st_size, 200)
            self.assertNotIn("headers", stream.call_args.kwargs)
            self.assertNotIn("auth", stream.call_args.kwargs)
            stream.return_value.__enter__.return_value = httpx.Response(403)
            with self.assertRaises(VideoError):
                client.download("https://test.volces.com/video", target)
            self.assertFalse(target.with_suffix(".download").exists())
            with self.assertRaises(VideoError):
                client.download("http://127.0.0.1/private", target)

    def test_validation_happens_before_post(self):
        handler = Mock()
        client = self.client(handler)
        for seconds, resolution in ((3, "480p"), (16, "480p"), (5, "1080p"), (True, "480p")):
            with self.assertRaises(VideoError):
                client.submit(PROMPT, seconds, resolution, 1)
        handler.assert_not_called()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.directory = Path(tmp.name)
        self.source, self.timeline = fixture()
        self.plan = plan_clips(self.directory, self.source, self.timeline, sample=True, max_seconds=20)
        self.provider = FakeProvider()

    def run_clips(self, **options):
        return generate_clips(self.directory, self.plan, self.provider, normalize_clip=fake_normalize,
                              sleep=lambda _: None, **options)

    def test_success_timing_cost_and_resume_reuses_all_clips_offline(self):
        manifest = self.run_clips()
        self.assertEqual(len(self.provider.posts), 3)
        self.assertEqual(manifest["estimatedCostCny"], .111)
        self.provider.preflight.side_effect = VideoError("offline")
        self.run_clips()
        self.assertEqual(len(self.provider.posts), 3)
        result = integrate_clips(self.directory, self.timeline, self.plan, manifest)
        self.assertEqual(result["durationInFrames"], self.timeline["durationInFrames"])
        self.assertEqual(result["audio"], self.timeline["audio"])
        for original, new in zip(self.timeline["scenes"], result["scenes"]):
            self.assertEqual(new["lines"], original["lines"])
            self.assertEqual(sum(c["durationInFrames"] for c in new["visual"]["clips"]), original["durationInFrames"])
        self.assertEqual(result["generatedVideo"]["model"], MODEL_ID)

    def test_preflight_failure_does_not_consume_budget_or_create_submission_intent(self):
        self.provider.preflight.side_effect = VideoError("offline")
        with self.assertRaises(VideoError):
            self.run_clips()
        saved = json.loads((self.directory / "video-generation.json").read_text())
        self.assertEqual(saved["submittedSeconds"], 0)
        self.assertEqual(self.provider.posts, [])
        self.provider.preflight.side_effect = None
        self.run_clips()
        self.assertEqual(len(self.provider.posts), 3)

    def test_missing_reported_usage_does_not_look_like_free_video(self):
        original = self.provider.get
        def without_usage(task_id):
            response = original(task_id)
            response.pop("usage")
            return response
        self.provider.get = without_usage
        self.assertIsNone(self.run_clips()["estimatedCostCny"])

    def test_unknown_submission_is_never_resubmitted_even_with_resume(self):
        self.provider.failure = SubmissionUnknown("response lost")
        with self.assertRaises(SubmissionUnknown):
            self.run_clips()
        self.provider.failure = None
        with self.assertRaises(SubmissionUnknown):
            self.run_clips(retry_failed=True)
        self.assertEqual(len(self.provider.posts), 1)

    def test_timeout_and_poll_disconnect_reuse_task_id(self):
        self.provider.status = "running"
        with self.assertRaisesRegex(VideoError, "wait limit"):
            self.run_clips(timeout_seconds=0)
        original = self.provider.polls[-1]
        self.provider.status = "succeeded"
        self.run_clips()
        self.assertEqual(self.provider.polls[1], original)
        self.assertEqual(len(self.provider.posts), 3)

    def test_failed_task_requires_explicit_resume_and_is_bounded(self):
        self.provider.status = "failed"
        with self.assertRaises(VideoError):
            self.run_clips()
        with self.assertRaises(VideoError):
            self.run_clips()
        self.assertEqual(len(self.provider.posts), 1)
        with self.assertRaises(VideoError):
            self.run_clips(retry_failed=True)
        with self.assertRaisesRegex(VideoError, "two-attempt"):
            self.run_clips(retry_failed=True)
        self.assertEqual(len(self.provider.posts), 2)

    def test_retries_count_toward_generation_limit(self):
        self.plan["maxGeneratedSeconds"] = 12
        self.plan["planDigest"] = digest({k: v for k, v in self.plan.items() if k != "planDigest"})
        self.provider.status = "failed"
        with self.assertRaises(VideoError):
            self.run_clips()
        self.provider.status = "succeeded"
        with self.assertRaisesRegex(VideoError, "limit was reached"):
            self.run_clips(retry_failed=True)
        self.assertEqual(len(self.provider.posts), 3)

    def test_download_failure_and_corrupt_cache_reuse_remote_task(self):
        original = self.provider.download
        self.provider.download = Mock(side_effect=VideoError("interrupted"))
        with self.assertRaises(VideoError):
            self.run_clips()
        self.provider.download = original
        self.run_clips()
        (self.directory / "video/generated/shot-001.mp4").write_bytes(b"corrupted")
        self.run_clips()
        self.assertEqual(len(self.provider.posts), 3)

    def test_changed_plan_model_or_asset_rejected(self):
        manifest = self.run_clips()
        (self.directory / "video/generated/shot-001.mp4").write_bytes(b"changed")
        with self.assertRaisesRegex(VideoError, "asset"):
            integrate_clips(self.directory, self.timeline, self.plan, manifest)
        self.plan["model"] = "different-model"
        with self.assertRaises(VideoError):
            self.run_clips()

    def test_planning_reuses_saved_plan_and_rejects_changed_settings(self):
        self.assertEqual(plan_clips(self.directory, self.source, self.timeline, sample=True, max_seconds=20), self.plan)
        with self.assertRaisesRegex(VideoError, "changed"):
            plan_clips(self.directory, self.source, self.timeline, sample=True, max_seconds=30)
        candidates = candidate_scenes(self.source, self.timeline, 4)
        self.assertEqual(len(candidates), 1)
        with self.assertRaises(ValueError):
            validate_directions({"style": "x" * 40, "scenes": []}, candidates)

    def test_precise_diagrams_are_never_video_candidates(self):
        source = load_plan(ROOT / "fixtures/scene-plan.valid.json")
        timeline = {"fps": 30, "scenes": [{"id": s.id, "durationInFrames": 120, "lines": []} for s in source.scenes]}
        selected = candidate_scenes(source, timeline, 120)
        ids = {c["sceneId"] for c in selected}
        for scene in source.scenes:
            if scene.template != "concept":
                self.assertNotIn(scene.id, ids)


class ResumeAndWorkerTests(unittest.TestCase):
    def test_resume_http_handler_enforces_ownership_and_active_job_guard_without_a_socket(self):
        from capstone_web.server import Handler
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp)
            job = store.create(request(), owner="alice")
            atomic_json(Path(tmp) / job["id"] / "output/pipeline-checkpoint.json", {})
            store.fail(job["id"], "stopped")
            handler = object.__new__(Handler)
            handler.server = SimpleNamespace(store=store, runner=Mock())
            handler._user = Mock(return_value={"id": "bob"})
            handler._read_json = Mock(return_value={})
            handler._json = Mock()
            with self.assertRaises(RequestError) as caught:
                handler._resume_job(job["id"])
            self.assertEqual(caught.exception.status, 404)
            handler.server.runner.submit.assert_not_called()
            handler._user.return_value = {"id": "alice"}
            handler._resume_job(job["id"])
            self.assertEqual(handler._json.call_args.args[0], 202)
            self.assertEqual(handler._json.call_args.args[1]["id"], job["id"])
            handler.server.runner.submit.assert_called_once()
            with self.assertRaises(RequestError) as caught:
                handler._resume_job(job["id"])
            self.assertEqual(caught.exception.status, 409)

    def test_create_handler_requires_seedance_readiness_even_for_a_sample(self):
        from capstone_web.server import Handler
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp)
            handler = object.__new__(Handler)
            handler.server = SimpleNamespace(store=store, runner=Mock(), readiness=lambda: {
                "sampleReady": True, "liveReady": True, "seedanceSampleReady": False,
                "checks": [{"id": "seedance_key", "label": "Ark key", "ok": False}]})
            handler._user = Mock(return_value={"id": "alice"})
            handler._read_json = Mock(return_value=request())
            handler._json = Mock()
            with self.assertRaises(RequestError) as caught:
                handler._create_job()
            self.assertEqual(caught.exception.status, 503)
            self.assertEqual(store.list("alice"), [])
            handler.server.runner.submit.assert_not_called()

    def test_resume_is_same_job_and_excludes_ambiguous_submissions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp)
            job = store.create(request(), owner="alice")
            output = Path(tmp) / job["id"] / "output"
            atomic_json(output / "pipeline-checkpoint.json", {})
            store.fail(job["id"], "stopped")
            self.assertTrue(store.get(job["id"])["canResume"])
            self.assertEqual(store.resume(job["id"])["id"], job["id"])
            with self.assertRaises(RequestError):
                store.resume(job["id"])
            atomic_json(output / "video-generation.json", {"shots": {"shot-001": {"state": "submission_unknown"}}})
            restarted = JobStore(tmp)
            self.assertFalse(restarted.get(job["id"])["canResume"])
            with self.assertRaises(RequestError):
                restarted.resume(job["id"])

    def test_worker_recovers_after_render_failure_without_new_speech_or_paid_posts(self):
        source, timeline = fixture()
        provider = FakeProvider()
        events = []
        def prepare(request, output, minimum, update):
            output.mkdir()
            (output / "scene-plan.json").write_text(dump_plan(source))
            atomic_json(output / "audio-manifest.json", {})
            atomic_json(output / "video/timeline.json", timeline)
            for name in ("narration.wav", "subtitles.vtt", "subtitles.srt"):
                (output / "video" / name).write_bytes(b"synthetic-test-data")
            return source, None, None
        actual = generate_clips
        def clips(*args, **kwargs):
            return actual(*args, **kwargs, normalize_clip=fake_normalize)
        with tempfile.TemporaryDirectory() as tmp, patch("capstone_web.worker.prepare_narration", side_effect=prepare) as narration, \
                patch("capstone_script.planner.load_env_file"), \
                patch("capstone_video.provider.ArkVideoClient", return_value=provider), \
                patch("capstone_video.pipeline.generate_clips", side_effect=clips), \
                patch("capstone_script.render.render_video", side_effect=RuntimeError("render stopped")) as render:
            job = {"id": "test", "request": request()}
            with self.assertRaises(RuntimeError):
                generate(job, Path(tmp), events.append)
            render.side_effect = None
            render.return_value = {"probedSeconds": 14, "width": 1920, "height": 1080, "bytes": 1000}
            result = generate({**job, "resumeCount": 1}, Path(tmp), events.append)
            self.assertEqual(result["generatedVideo"]["model"], MODEL_ID)
            narration.assert_called_once()
            self.assertEqual(len(provider.posts), 3)
            (Path(tmp) / "output/video/narration.wav").write_bytes(b"changed")
            with self.assertRaisesRegex(VideoError, "changed"):
                generate(job, Path(tmp), events.append)
            self.assertEqual(len(provider.posts), 3)

    def test_web_validation_excludes_any_model_or_host_override(self):
        self.assertEqual(request()["videoResolution"], "480p")
        self.assertEqual(request()["durationSeconds"], 30)
        for extra in ({"model": "wrong"}, {"baseUrl": "https://other.test"}, {"maxGeneratedSeconds": True},
                      {"maxGeneratedSeconds": 121}, {"videoResolution": "1080p"}):
            with self.assertRaises(RequestError):
                request(**extra)


class MediaTests(unittest.TestCase):
    def test_real_24fps_file_converts_to_exact_30fps_frames_without_audio(self):
        from capstone_script.render import _node, REMOTION_CLI, RENDERER
        if not REMOTION_CLI.exists():
            self.skipTest("Install the renderer to exercise the bundled ffmpeg.")
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            def chunk(kind, payload):
                return struct.pack('>I', len(payload)) + kind + payload + struct.pack('>I', zlib.crc32(kind + payload))
            png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 640, 360, 8, 2, 0, 0, 0))
            png += chunk(b'IDAT', zlib.compress((b'\x00' + bytes([40, 90, 130]) * 640) * 360)) + chunk(b'IEND', b'')
            (directory / "test.png").write_bytes(png)
            with wave.open(str(directory / "audio.wav"), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(b'\x00\x00' * 48000 * 4)
            source, target = directory / "source.mp4", directory / "clip.mp4"
            subprocess.run([_node(), str(REMOTION_CLI), "ffmpeg", "-v", "error", "-loop", "1", "-framerate", "24",
                "-i", str(directory / "test.png"), "-i", str(directory / "audio.wav"),
                "-t", "4", "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", str(source)],
                cwd=RENDERER, check=True, capture_output=True, timeout=60)
            self.assertEqual(probe(source)["frames"], 96)
            self.assertEqual(probe(source)["audioStreams"], 1)
            result = normalize(source, target, 113, 30)
            self.assertEqual(result["frames"], 113)
            self.assertAlmostEqual(result["duration"], 113 / 30, places=4)
            self.assertEqual(result["audioStreams"], 0)
            with self.assertRaisesRegex(VideoError, "cover"):
                normalize(source, target, 150, 30)


if __name__ == "__main__":
    unittest.main()
