"""Timeline tests with synthetic line audio: frames, cards, the aligned track and subtitles."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from capstone_script.planner import write_json
from capstone_script.scene_plan import dump_plan, load_plan, validate_plan
from capstone_script.timeline import (
    CHAPTER_FRAMES, END_FRAMES, GAP_FRAMES, LEAD_FRAMES, TAIL_FRAMES, TITLE_FRAMES, TimelineError, build_timeline,
    subtitle_rows, subtitles, write_timeline,
)

ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "fixtures" / "scene-plan.valid.json"
RATE = 48000


def chaptered(plan):
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    ids = [scene["id"] for scene in data["scenes"]]
    data["chapters"] = [{"id": "chapter-01", "title": "The question", "sceneIds": ids[:2]},
                        {"id": "chapter-02", "title": "The answer", "sceneIds": ids[2:]}]
    return validate_plan(data)


class TimelineTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capstone-timeline-test-")
        self.addCleanup(temporary.cleanup)
        self.run_dir = Path(temporary.name)
        self.plan = load_plan(VALID)

    def narrate(self, plan):
        """Write one WAV per line (value = line number, 1.25 s + n samples) and a matching manifest."""
        blocks = []
        lines = [line for scene in plan.scenes for line in scene.narration]
        for number, line in enumerate(lines, start=1):
            samples = np.full(60000 + number, number / 100, dtype=np.float32)
            path = self.run_dir / "audio" / line.id / "narration.wav"
            path.parent.mkdir(parents=True)
            sf.write(path, samples, RATE, subtype="FLOAT")
            scene_id = next(scene.id for scene in plan.scenes if line in scene.narration)
            blocks.append({"sceneId": scene_id, "narrationId": line.id, "text": line.text,
                           "audioPath": f"audio/{line.id}/narration.wav", "sampleRate": RATE, "channels": 1,
                           "sampleCount": samples.size, "durationSeconds": samples.size / RATE})
        manifest = {"schemaVersion": "1", "status": "completed", "sampleRate": RATE, "blocks": blocks,
                    "planSha256": hashlib.sha256(dump_plan(plan).encode("utf-8")).hexdigest()}
        (self.run_dir / "scene-plan.json").write_text(dump_plan(plan), encoding="utf-8")
        write_json(self.run_dir / "audio-manifest.json", manifest)
        return manifest

    def test_lines_start_on_frames_after_the_title_and_pauses(self):
        timeline = build_timeline(self.plan, self.narrate(self.plan))
        first, second = timeline["scenes"][:2]
        self.assertEqual(first["from"], TITLE_FRAMES)
        self.assertEqual(first["lines"][0]["from"], TITLE_FRAMES + LEAD_FRAMES)
        self.assertEqual(first["lines"][0]["durationInFrames"], 38)  # ceil(60001 / 1600)
        self.assertEqual(first["lines"][1]["from"], TITLE_FRAMES + LEAD_FRAMES + 38 + GAP_FRAMES)
        last_line = first["lines"][-1]
        self.assertEqual(second["from"], last_line["from"] + last_line["durationInFrames"] + TAIL_FRAMES)
        self.assertEqual(first["lines"][2]["highlightPointIndex"], 0)
        self.assertEqual(second["lines"][1]["highlightNodeId"], "dns")
        end = timeline["scenes"][-1]
        self.assertEqual(end["from"] + end["durationInFrames"], timeline["durationInFrames"])
        self.assertEqual(timeline["audio"]["sampleCount"], timeline["durationInFrames"] * 1600)
        self.assertEqual(timeline["chapters"], [])

    def test_chapter_cards_come_before_each_chapter(self):
        plan = chaptered(self.plan)
        timeline = build_timeline(plan, self.narrate(plan))
        first, second = timeline["chapters"]
        self.assertEqual(first["from"], TITLE_FRAMES)
        self.assertEqual(timeline["scenes"][0]["from"], TITLE_FRAMES + CHAPTER_FRAMES)
        third_scene = timeline["scenes"][2]
        self.assertEqual(second["from"] + CHAPTER_FRAMES, third_scene["from"])
        self.assertEqual(first["from"] + first["durationInFrames"], second["from"])
        self.assertEqual(second["from"] + second["durationInFrames"], timeline["durationInFrames"])
        self.assertEqual(third_scene["chapterId"], "chapter-02")

    def test_a_plan_edited_after_narration_is_refused(self):
        manifest = self.narrate(self.plan)
        data = self.plan.model_dump(mode="json", by_alias=True, exclude_none=True)
        data["scenes"][0]["narration"][0]["text"] = "A different first line."
        with self.assertRaisesRegex(TimelineError, "changed after narration"):
            build_timeline(validate_plan(data), manifest)

    def test_written_track_puts_each_line_at_its_start_frame(self):
        self.narrate(self.plan)
        out = write_timeline(self.run_dir)
        timeline = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
        track, rate = sf.read(out / "narration.wav", dtype="float32")
        self.assertEqual((rate, track.size), (RATE, timeline["audio"]["sampleCount"]))
        line = timeline["scenes"][1]["lines"][0]  # The sixth line overall: value 0.06.
        start = line["from"] * 1600
        self.assertEqual(track[start - 1], 0)
        self.assertAlmostEqual(float(track[start]), 0.06, places=3)
        self.assertAlmostEqual(float(track[start + line["sampleCount"] - 1]), 0.06, places=3)
        self.assertEqual(track[start + line["sampleCount"]], 0)
        self.assertTrue((out / "subtitles.srt").exists() and (out / "subtitles.vtt").exists())
        with self.assertRaises(FileExistsError):
            write_timeline(self.run_dir)

    def test_subtitles_use_the_timeline_frames(self):
        timeline = build_timeline(self.plan, self.narrate(self.plan))
        srt, vtt = subtitles(timeline, "srt"), subtitles(timeline, "vtt")
        first = timeline["scenes"][0]["lines"][0]
        rows = subtitle_rows(first["text"])
        self.assertTrue(srt.startswith(f"1\n00:00:02,200 --> 00:00:03,467\n{rows[0]}\n"))
        self.assertTrue(vtt.startswith("WEBVTT\n\n00:00:02.200 --> 00:00:03.467\n"))
        self.assertEqual(srt.count(" --> "), 18)

    def test_long_subtitles_split_near_the_middle(self):
        self.assertEqual(subtitle_rows("Short line."), ["Short line."])
        rows = subtitle_rows("Your browser asks a DNS server for the address of the website you typed.")
        self.assertEqual(len(rows), 2)
        self.assertLess(abs(len(rows[0]) - len(rows[1])), 12)


if __name__ == "__main__":
    unittest.main()
