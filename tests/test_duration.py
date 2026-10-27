"""Measured-duration acceptance and repair, using synthetic audio and no paid API."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from capstone_script.__main__ import main
from capstone_script.duration import (
    DurationError, duration_check, ensure_minimum_duration, merge_extension, requested_minimum, require_duration,
)
from capstone_script.narrate import narrate_plan
from capstone_script.planner import write_json
from capstone_script.render import render_video
from capstone_script.scene_plan import dump_plan, load_plan, validate_plan
from capstone_script.timeline import build_timeline, write_timeline
from test_narrate import WordEngine


class DurationEngine(WordEngine):
    def chunks(self, text, speed):
        import numpy as np
        for words, samples in super().chunks(text, speed):
            yield words, np.repeat(samples, 2)

ROOT = Path(__file__).resolve().parents[1]
PLAN = load_plan(ROOT / "fixtures/scene-plan.valid.json")


def extra_plan(round_number=1):
    data = PLAN.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["scenes"] = data["scenes"][:2]
    for index, scene in enumerate(data["scenes"]):
        for number, line in enumerate(scene["narration"]):
            line["text"] = (f"Example {round_number} step {index + 1} detail {number + 1} explains how "
                            "the receiver reconstructs missing packets after checking each message.")
    return validate_plan(data)


class DurationPolicyTests(unittest.TestCase):
    def test_new_long_requests_default_to_level1_but_legacy_runs_are_exempt(self):
        self.assertEqual(requested_minimum(420), 420)
        self.assertEqual(requested_minimum(600), 420)
        self.assertEqual(requested_minimum(90), 0)
        self.assertEqual(requested_minimum(420, 0), 0)
        self.assertIsNone(duration_check({"targetDurationSec": 420}, 384.683, "rendered-mp4")["passed"])
        for value in (-1, True, 420.0, 601, 29):
            with self.subTest(value=value), self.assertRaises(ValueError):
                requested_minimum(420, value)

    def test_no_rounding_tolerance_turns_a_short_video_into_a_pass(self):
        spec = {"targetDurationSec": 420, "minimumDurationSec": 420}
        self.assertFalse(duration_check(spec, 419.999, "rendered-mp4")["passed"])
        self.assertTrue(duration_check(spec, 420.0, "rendered-mp4")["passed"])
        for seconds in (float("nan"), float("inf"), 0):
            with self.subTest(seconds=seconds), self.assertRaises(DurationError):
                duration_check(spec, seconds, "rendered-mp4")

    def test_merge_keeps_original_ids_order_and_final_chapter_membership(self):
        plan = load_plan(ROOT / "fixtures/scene-plan.long.json")
        merged = merge_extension(plan, extra_plan(), 1)
        originals = {scene.id: scene for scene in plan.scenes}
        self.assertEqual([scene for scene in merged.scenes if scene.id in originals], plan.scenes)
        self.assertEqual(merged.scenes[-1], plan.scenes[-1])
        self.assertEqual(merged.chapters[-1].scene_ids[-3:],
                         ["duration-01-scene-01", "duration-01-scene-02", plan.scenes[-1].id])

    def test_exact_repeated_narration_cannot_fill_the_duration_gap(self):
        with self.assertRaisesRegex(DurationError, "repeated"):
            merge_extension(PLAN, PLAN, 1)


class DurationRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-duration-test-")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        versions = patch("capstone_tts.audio.version", return_value="unit-test-placeholder")
        versions.start()
        self.addCleanup(versions.stop)
        self.spec = {"projectId": PLAN.project_id, "topic": "How the internet works", "audience": "Curious adults",
                     "targetDurationSec": 60, "minimumDurationSec": 60, "allowedTemplates": ["concept", "flow"]}
        write_json(self.run / "project-spec.json", self.spec)
        (self.run / "scene-plan.json").write_text(dump_plan(PLAN))
        self.manifest = narrate_plan(PLAN, self.run, DurationEngine)
        self.before = build_timeline(PLAN, self.manifest)["durationSeconds"]

    def test_already_long_enough_makes_no_api_request_or_new_audio(self):
        self.spec["minimumDurationSec"] = 30
        write_json(self.run / "project-spec.json", self.spec)
        self.assertGreater(self.before, 30)
        factory = Mock(side_effect=RuntimeError("No API credential"))
        with patch("capstone_script.duration.generate_extension") as generate:
            plan = ensure_minimum_duration(self.run, None, Mock(), client_factory=factory)
        self.assertEqual(plan, PLAN)
        generate.assert_not_called()
        factory.assert_not_called()
        record = json.loads((self.run / "duration-check.json").read_text())
        self.assertTrue(record["passed"])
        self.assertEqual(record["measurement"], "narrated-timeline")

    def test_transient_failures_do_not_consume_successful_content_rounds(self):
        with patch("capstone_script.duration.generate_extension", side_effect=[
                ConnectionError("Offline"), ConnectionError("Offline"), extra_plan()]) as generate, \
                patch("capstone_script.review.write_review"):
            for _ in range(2):
                with self.assertRaises(ConnectionError):
                    ensure_minimum_duration(self.run, Mock(), DurationEngine)
            plan = ensure_minimum_duration(self.run, Mock(), DurationEngine)
        self.assertEqual(generate.call_count, 3)
        self.assertIn("duration-03-scene-01", {scene.id for scene in plan.scenes})
        record = json.loads((self.run / "duration-extension.json").read_text())
        self.assertEqual(record["status"], "passed")
        self.assertEqual([item["promoted"] for item in record["rounds"]], [False, False, True])
        self.assertEqual([item["round"] for item in record["rounds"]], [1, 1, 1])
        self.assertTrue((self.run / "duration-attempt-03/previous/audio-manifest.json").is_file())

    def test_repair_review_budget_preserves_target_and_accounts_for_all_review_costs(self):
        write_json(self.run / "review.json", {"estimatedCostUsd": 0.25})

        def review(candidate, *args, **kwargs):
            staged_spec = json.loads((candidate / "project-spec.json").read_text())
            self.assertEqual(staged_spec["targetDurationSec"], self.spec["targetDurationSec"])
            self.assertGreater(staged_spec["reviewWordTarget"], 300)
            write_json(candidate / "review.json", {"estimatedCostUsd": 0.75})

        with patch("capstone_script.duration.generate_extension", return_value=extra_plan()), \
                patch("capstone_script.review.write_review", side_effect=review):
            ensure_minimum_duration(self.run, Mock(), DurationEngine)
        record = json.loads((self.run / "duration-extension.json").read_text())
        self.assertEqual(record["initialReviewCostUsd"], 0.25)
        self.assertEqual(record["extensionReviewCostUsd"], 0.75)
        self.assertEqual(record["estimatedCostUsd"], 0.75)
        self.assertNotIn("reviewWordTarget", json.loads((self.run / "project-spec.json").read_text()))

    def test_existing_sufficient_run_can_be_checked_without_api_credentials(self):
        with patch("capstone_script.__main__._client", side_effect=RuntimeError("No API key")) as client, \
                redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(["ensure-duration", "--run", str(self.run), "--minimum-duration", "30", "--offline"])
        self.assertEqual(code, 0)
        client.assert_not_called()

    def test_extension_reuses_audio_rebuilds_subtitles_and_archives_old_music_and_video(self):
        self.spec["minimumDurationSec"] = 60
        write_json(self.run / "project-spec.json", self.spec)
        self.assertLess(self.before, 60)
        write_timeline(self.run)
        (self.run / "video/music.wav").write_bytes(b"old music")
        (self.run / "video.mp4").write_bytes(b"old video")
        with patch("capstone_script.duration.generate_extension", return_value=extra_plan()) as generate, \
                patch("capstone_script.review.write_review") as review:
            merged = ensure_minimum_duration(self.run, Mock(), DurationEngine)
        generate.assert_called_once()
        review.assert_called_once()
        saved = json.loads((self.run / "audio-manifest.json").read_text())
        self.assertEqual(saved["reusedLines"], len(self.manifest["blocks"]))
        self.assertGreater(build_timeline(merged, saved)["durationSeconds"], 60)
        self.assertEqual(load_plan(self.run / "scene-plan.json"), merged)
        self.assertFalse((self.run / "video/music.wav").exists())
        self.assertFalse((self.run / "video.mp4").exists())
        backup = self.run / "duration-attempt-01/previous"
        self.assertEqual((backup / "video/music.wav").read_bytes(), b"old music")
        self.assertEqual((backup / "video.mp4").read_bytes(), b"old video")
        self.assertIn("Example 1", (self.run / "video/subtitles.vtt").read_text())
        self.assertNotIn("Example 1", (backup / "video/subtitles.vtt").read_text())
        require_duration(self.run, build_timeline(merged, saved)["durationSeconds"], "narrated-timeline")

    def test_two_insufficient_extensions_fail_without_claiming_acceptance(self):
        self.spec.update(targetDurationSec=420, minimumDurationSec=420)
        write_json(self.run / "project-spec.json", self.spec)
        with patch("capstone_script.duration.generate_extension", side_effect=[extra_plan(1), extra_plan(2)]) as generate, \
                patch("capstone_script.review.write_review"), \
                self.assertRaisesRegex(DurationError, "after 2 content extensions"):
            ensure_minimum_duration(self.run, Mock(), DurationEngine)
        self.assertEqual(generate.call_count, 2)
        record = json.loads((self.run / "duration-extension.json").read_text())
        self.assertEqual(record["status"], "failed")
        self.assertEqual(len(record["rounds"]), 2)
        self.assertFalse(json.loads((self.run / "duration-check.json").read_text())["passed"])
        self.assertTrue((self.run / "duration-attempt-02/previous/audio-manifest.json").is_file())

    def test_review_failure_keeps_original_plan_and_audio_intact(self):
        with patch("capstone_script.duration.generate_extension", return_value=extra_plan()), \
                patch("capstone_script.review.write_review", side_effect=ValueError("Review unavailable")), \
                self.assertRaisesRegex(ValueError, "Review unavailable"):
            ensure_minimum_duration(self.run, Mock(), DurationEngine)
        self.assertEqual(load_plan(self.run / "scene-plan.json"), PLAN)
        self.assertEqual(json.loads((self.run / "audio-manifest.json").read_text()), self.manifest)
        self.assertTrue((self.run / "duration-attempt-01/scene-plan.json").is_file())

    def test_short_timeline_is_blocked_before_any_renderer_process(self):
        write_timeline(self.run)
        with patch("capstone_script.render.subprocess.run") as subprocess, self.assertRaises(DurationError):
            render_video(self.run)
        subprocess.assert_not_called()

    def test_probed_mp4_below_minimum_is_rejected_without_success_metadata(self):
        self.spec["minimumDurationSec"] = 30
        write_json(self.run / "project-spec.json", self.spec)
        write_timeline(self.run)

        def render(*args, **kwargs):
            (self.run / "video-draft.mp4").write_bytes(b"fake video")
            return Mock(returncode=0)

        with patch("capstone_script.render.render_command", return_value=["mock-render"]), \
                patch("capstone_script.render.subprocess.run", side_effect=render), \
                patch("capstone_script.render.probe_seconds", return_value=29.999), \
                self.assertRaises(DurationError):
            render_video(self.run, draft=True, music=False)
        self.assertFalse((self.run / "video-draft-info.json").exists())
        check = json.loads((self.run / "duration-check.json").read_text())
        self.assertFalse(check["passed"])
        self.assertEqual(check["measurement"], "rendered-mp4")


class DurationCommandTests(unittest.TestCase):
    def test_invalid_minimum_is_rejected_before_planning(self):
        with tempfile.TemporaryDirectory() as temporary, patch("capstone_script.__main__._client") as client, \
                redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
            code = main(["run", "--topic", "A topic", "--duration", "90", "--minimum-duration", "420",
                         "--out", str(Path(temporary) / "new")])
        self.assertEqual(code, 1)
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
