"""preview.html tests on a run narrated with synthetic audio."""

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.narrate import narrate_plan
from capstone_script.preview import build_preview, motion_beats, process_beats
from capstone_script.scene_plan import dump_plan, validate_plan
from test_narrate import WordEngine
from test_planner import VALID


def embedded(html):
    match = re.search(r'<script id="preview-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(match.group(1))


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-preview-test-")
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name) / "run"
        self.run.mkdir()
        versions = patch("capstone_tts.audio.version", return_value="unit-test-placeholder")
        versions.start()
        self.addCleanup(versions.stop)

    def narrate(self, data=VALID):
        plan = validate_plan(data)
        (self.run / "scene-plan.json").write_text(dump_plan(plan), encoding="utf-8")
        narrate_plan(plan, self.run, WordEngine)

    def test_preview_embeds_the_plan_and_line_timings(self):
        self.narrate()
        html = build_preview(self.run).read_text(encoding="utf-8")
        data = embedded(html)
        self.assertEqual(data["plan"]["title"], VALID["title"])
        self.assertEqual(len(data["blocks"]), 18)
        self.assertEqual(data["audio"], "narration-preview.wav")
        self.assertEqual(data["blocks"][0]["previewStartSeconds"], 0.2)
        self.assertNotIn("__PREVIEW_DATA__", html)

    def test_script_closing_tags_in_plan_text_stay_inside_the_data(self):
        data = copy.deepcopy(VALID)
        data["title"] = "Tags like </script> stay text"
        self.narrate(data)
        html = build_preview(self.run).read_text(encoding="utf-8")
        self.assertEqual(html.count("</script>"), 2)
        self.assertEqual(embedded(html)["plan"]["title"], "Tags like </script> stay text")

    def test_incomplete_narration_is_refused(self):
        self.narrate()
        path = self.run / "audio-manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["status"] = "failed"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "not complete"):
            build_preview(self.run)

    def test_motion_beats_name_entities_and_cover_lines_without_actions(self):
        scene = {"visual": {
            "entities": [{"id": "packet", "kind": "packet", "label": "Your message"},
                         {"id": "device", "kind": "laptop", "label": ""}],
            "actions": [{"entityId": "packet", "kind": "follow-path", "startLine": 0, "endLine": 1,
                         "startOffset": 0, "endOffset": 1},
                        {"entityId": "device", "kind": "opacity", "startLine": 1, "endLine": 2,
                         "startOffset": 0, "endOffset": 0}]},
                 "narration": [{"id": "one"}, {"id": "two"}, {"id": "three"}]}
        beats = motion_beats(scene)
        self.assertEqual(beats[0], {"narrationId": "one", "description": "Your message follows its route."})
        self.assertIn("laptop changes visibility", beats[1]["description"])
        self.assertIn("scene holds", beats[2]["description"])

    def test_motion_sample_preview_has_a_description_for_every_narration_beat(self):
        fixture = Path(__file__).resolve().parents[1] / "fixtures/scene-plan.motion-network.json"
        self.narrate(json.loads(fixture.read_text(encoding="utf-8")))
        data = embedded(build_preview(self.run).read_text(encoding="utf-8"))
        motion_scenes = [scene for scene in data["plan"]["scenes"] if scene["template"] == "motion"]
        self.assertTrue(motion_scenes)
        for scene in motion_scenes:
            beats = data["motionBeats"][scene["id"]]
            self.assertEqual([beat["narrationId"] for beat in beats],
                             [line["id"] for line in scene["narration"]])
            self.assertTrue(all(beat["description"] for beat in beats))

    def test_process_preview_describes_events_without_claiming_to_render_them(self):
        scene = {"visual": {"actorKind": "box", "actors": [{"id": "parcel", "label": "Parcel"}],
                 "stations": [{"id": "bench", "label": "Packing"}], "events": [
                     {"kind": "start", "actorIds": ["parcel"], "stationIds": ["bench"],
                      "startLine": 0, "endLine": 0, "startOffset": 0, "endOffset": 1}]},
                 "narration": [{"id": "one"}, {"id": "two"}]}
        beats = process_beats(scene)
        self.assertEqual(beats[0]["description"], "Parcel begins processing at Packing.")
        self.assertEqual(beats[1]["description"], "No new process event is scheduled on this line.")

    def test_preview_links_a_completed_render_but_not_a_partial_file(self):
        self.narrate()
        video = self.run / "video.mp4"
        video.write_bytes(b"test-video")
        self.assertEqual(embedded(build_preview(self.run).read_text())["renderedVideos"], [])
        report = self.run / "video-info.json"
        report.write_text(json.dumps({"bytes": video.stat().st_size,
                                      "expectedSeconds": 10, "probedSeconds": 10.01}))
        links = embedded(build_preview(self.run).read_text())["renderedVideos"]
        self.assertEqual(links, [{"href": "video.mp4", "label": "Watch rendered MP4"}])
        report.write_text(json.dumps({"bytes": video.stat().st_size,
                                      "expectedSeconds": 10, "probedSeconds": 8}))
        self.assertEqual(embedded(build_preview(self.run).read_text())["renderedVideos"], [])


if __name__ == "__main__":
    unittest.main()
