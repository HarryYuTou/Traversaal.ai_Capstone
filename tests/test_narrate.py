"""Narration bridge tests with synthetic audio; the real Kokoro model is not loaded."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np
import soundfile as sf

from capstone_script.__main__ import main
from capstone_script.narrate import NarrationError, narrate_plan
from capstone_script.scene_plan import load_plan, validate_plan
from test_planner import TOPIC, FakeClient, model_output, response

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "fixtures" / "scene-plan.valid.json"
PLAN = load_plan(FIXTURE)


class WordEngine:
    """Synthetic stand-in for KokoroEngine: 0.1 s of tone per word at 24 kHz."""

    def __init__(self, fail_on=None):
        self.fail_on = fail_on

    def chunks(self, text, speed):
        if self.fail_on and self.fail_on in text:
            raise ValueError("No pronunciation found")
        samples = 2400 * len(text.split())
        yield text, (0.25 * np.sin(2 * np.pi * 440 * np.arange(samples) / 24000)).astype(np.float32)


def edited_plan(new_text):
    """The fixture with its first line rewritten."""
    data = PLAN.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["scenes"][0]["narration"][0]["text"] = new_text
    return validate_plan(data)


class NarrateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-narrate-test-")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        self.run.mkdir()
        versions = patch("capstone_tts.audio.version", return_value="unit-test-placeholder")
        versions.start()
        self.addCleanup(versions.stop)

    def test_unchanged_lines_reuse_an_earlier_run(self):
        narrate_plan(PLAN, self.run, Mock(return_value=WordEngine()))
        second = Path(self.temporary.name) / "second"
        factory = Mock(return_value=WordEngine())
        manifest = narrate_plan(edited_plan("A brand new opening line."), second, factory, reuse_from=self.run)
        factory.assert_called_once()
        hits = [block["cacheHit"] for block in manifest["blocks"]]
        self.assertEqual(hits, [False] + [True] * (len(hits) - 1))
        self.assertEqual(manifest["reusedLines"], len(hits) - 1)
        self.assertEqual(manifest["reusedFrom"], self.run.as_posix())
        reused = manifest["blocks"][1]
        self.assertEqual(reused["synthesisMs"], 0.0)
        self.assertEqual(sf.info(second / reused["audioPath"]).frames, reused["sampleCount"])
        self.assertTrue((second / "narration-preview.wav").exists())

    def test_a_missing_earlier_line_is_synthesized_instead(self):
        narrate_plan(PLAN, self.run, Mock(return_value=WordEngine()))
        shutil.rmtree(self.run / "audio" / "scene-01-line-02")
        factory = Mock(return_value=WordEngine())
        manifest = narrate_plan(PLAN, Path(self.temporary.name) / "second", factory, reuse_from=self.run)
        factory.assert_called_once()
        self.assertEqual([block["cacheHit"] for block in manifest["blocks"][:3]], [True, False, True])

    def test_a_fully_reused_plan_never_loads_the_model(self):
        narrate_plan(PLAN, self.run, Mock(return_value=WordEngine()))
        factory = Mock(return_value=WordEngine())
        manifest = narrate_plan(PLAN, Path(self.temporary.name) / "second", factory, reuse_from=self.run)
        factory.assert_not_called()
        self.assertEqual(manifest["timingsMs"]["modelLoad"], 0.0)
        self.assertTrue(all(block["cacheHit"] for block in manifest["blocks"]))

    def test_a_different_speed_is_not_reused(self):
        narrate_plan(PLAN, self.run, Mock(return_value=WordEngine()))
        manifest = narrate_plan(PLAN, Path(self.temporary.name) / "second", Mock(return_value=WordEngine()),
                                speed=1.2, reuse_from=self.run)
        self.assertEqual(manifest["reusedLines"], 0)

    def test_every_line_gets_verified_audio_and_one_model_load(self):
        factory = Mock(return_value=WordEngine())
        manifest = narrate_plan(PLAN, self.run, factory)
        factory.assert_called_once()
        self.assertEqual(manifest["status"], "completed")
        self.assertEqual([b["narrationId"] for b in manifest["blocks"]],
                         [line.id for scene in PLAN.scenes for line in scene.narration])
        first = manifest["blocks"][0]
        self.assertEqual(first["audioPath"], "audio/scene-01-line-01/narration.wav")
        self.assertEqual(first["sampleCount"], 4800 * len(PLAN.scenes[0].narration[0].text.split()))
        self.assertEqual(sf.info(self.run / first["audioPath"]).frames, first["sampleCount"])
        self.assertTrue((self.run / "audio" / "scene-01-line-01" / "audio-info.json").exists())
        saved = json.loads((self.run / "audio-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved, manifest)

    def test_preview_track_adds_the_documented_pauses(self):
        manifest = narrate_plan(PLAN, self.run, WordEngine)
        speech = sum(block["sampleCount"] for block in manifest["blocks"])
        scenes, lines = len(PLAN.scenes), len(manifest["blocks"])
        pauses = scenes * (9600 + 9600) + (lines - scenes) * 4800
        self.assertEqual(sf.info(self.run / "narration-preview.wav").frames, speech + pauses)
        starts = [block["previewStartSeconds"] for block in manifest["blocks"]]
        self.assertEqual(starts[0], 0.2)
        self.assertEqual(starts, sorted(starts))
        end_of_scene_one = starts[4] + manifest["blocks"][4]["durationSeconds"]
        self.assertAlmostEqual(starts[5] - end_of_scene_one, 0.4)  # tail + next lead

    def test_failed_line_is_named_and_finished_lines_are_kept(self):
        with self.assertRaisesRegex(NarrationError, "scene-02/scene-02-line-01"):
            narrate_plan(PLAN, self.run, lambda: WordEngine(fail_on="Computers find"))
        manifest = json.loads((self.run / "audio-manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["status"], "failed")
        self.assertEqual(manifest["failedNarrationId"], "scene-02-line-01")
        self.assertEqual(len(manifest["blocks"]), 5)
        self.assertTrue((self.run / "audio" / "scene-01-line-05" / "narration.wav").exists())
        self.assertFalse((self.run / "narration-preview.wav").exists())

    def test_existing_narration_is_never_overwritten(self):
        (self.run / "audio").mkdir()
        factory = Mock()
        with self.assertRaises(FileExistsError):
            narrate_plan(PLAN, self.run, factory)
        factory.assert_not_called()


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-command-test-")
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / "run"
        for patcher in (patch("capstone_tts.audio.version", return_value="unit-test-placeholder"),
                        patch("capstone_script.__main__._engine_factory", return_value=WordEngine),
                        patch("capstone_script.__main__.load_env_file")):
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_main(self, *argv):
        with redirect_stdout(io.StringIO()) as out:
            code = main(list(argv))
        return code, out.getvalue()

    def test_narrate_command_snapshots_the_plan_and_writes_audio(self):
        code, out = self.run_main("narrate", "--plan", str(FIXTURE), "--out", str(self.out))
        self.assertEqual(code, 0)
        self.assertIn("18 lines", out)
        self.assertEqual(load_plan(self.out / "scene-plan.json"), PLAN)
        self.assertTrue((self.out / "narration-preview.wav").exists())

    def test_run_command_goes_from_topic_to_narration(self):
        with patch("capstone_script.__main__._client", return_value=FakeClient(response(model_output()))):
            code, _ = self.run_main("run", "--topic", TOPIC, "--out", str(self.out))
        self.assertEqual(code, 0)
        for name in ("project-spec.json", "llm-response.json", "scene-plan.json",
                     "audio-manifest.json", "narration-preview.wav"):
            self.assertTrue((self.out / name).exists(), name)


if __name__ == "__main__":
    unittest.main()
