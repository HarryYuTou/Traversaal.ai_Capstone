"""preview.html tests on a run narrated with synthetic audio."""

import copy
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.narrate import narrate_plan
from capstone_script.preview import build_preview
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


if __name__ == "__main__":
    unittest.main()
