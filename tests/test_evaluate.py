"""Evaluation tests with a scripted fake client: metrics come from the files each run writes."""

import json
from pathlib import Path
import tempfile
import unittest

from capstone_script.evaluate import evaluate
from test_planner import TOPIC, FakeClient, broken_highlight, model_output, response
from test_review import NEW_TEXT, review_output

TOPICS = [{"topic": TOPIC, "audience": "Students", "duration": 75},
          {"topic": "Why is the sky blue?", "audience": "Children", "duration": 75}]


class EvaluateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="capstone-eval-test-")
        self.addCleanup(temporary.cleanup)
        self.out = Path(temporary.name) / "eval"

    def test_each_topic_is_planned_reviewed_and_summarized(self):
        client = FakeClient(response(model_output()), response(review_output()),
                            response(model_output(broken_highlight)), response(model_output(broken_highlight)))
        results = evaluate(TOPICS, self.out, client)
        first, second = results["runs"]
        self.assertEqual((first["planStatus"], first["repairs"], first["scenes"], first["lines"]),
                         ("completed", 0, 5, 18))
        self.assertEqual(first["templates"], {"concept": 2, "flow": 3})
        self.assertEqual(first["scores"]["clarity"], 4)
        self.assertEqual(first["linesRewritten"], 1)
        self.assertEqual(first["wordsDraft"], 214)
        self.assertEqual(second["planStatus"], "failed")
        self.assertEqual((second["requests"], second["repairs"]), (2, 1))
        self.assertIn("router", second["error"])
        summary = results["summary"]
        self.assertEqual((summary["topics"], summary["planned"], summary["repairs"]), (2, 1, 1))
        self.assertEqual(summary["firstRequestPassRate"], 0.5)
        self.assertEqual(json.loads((self.out / "results.json").read_text(encoding="utf-8"))["summary"], summary)
        table = (self.out / "results.md").read_text(encoding="utf-8")
        self.assertIn("| 1 | What happens after you enter a website address? | 75 s | single | first request |", table)
        self.assertIn("| 2 | Why is the sky blue? | 75 s | single | failed | 2 |", table)
        self.assertEqual(first["run"], "01-what-happens-after-you-enter-a-w")
        plan = json.loads((self.out / first["run"] / "scene-plan.json").read_text(encoding="utf-8"))
        self.assertEqual(plan["scenes"][0]["narration"][0]["text"], NEW_TEXT)

    def test_existing_output_is_refused(self):
        self.out.mkdir()
        with self.assertRaises(FileExistsError):
            evaluate(TOPICS, self.out, FakeClient())


if __name__ == "__main__":
    unittest.main()
