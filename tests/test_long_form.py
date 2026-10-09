"""Chapter-by-chapter planner tests with a scripted fake client: no network calls and no API key."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.__main__ import main
from capstone_script.long_form import chapter_range, outline_request, rescale, review_outline
from capstone_script.planner import PlannerError, make_spec, write_plan_run
from capstone_script.scene_plan import load_plan, summarize
from test_planner import TOPIC, FakeClient, broken_highlight, model_output, response

AUDIENCE = "University students with no networking background"


def outline_output(seconds=(75, 75, 75)):
    return {"title": "How a web page reaches you",
            "chapters": [{"title": f"Part {n}", "goal": f"Explain part {n}.",
                          "keyPoints": ["First idea", "Second idea"], "targetSeconds": value}
                         for n, value in enumerate(seconds, start=1)]}


class LongFormTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-long-test-")
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / "run"
        self.spec, _ = make_spec(TOPIC, AUDIENCE, 225)

    def saved(self, name):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def test_chapters_are_planned_in_order_and_merged_into_one_plan(self):
        client = FakeClient(response(outline_output()), *(response(model_output()) for _ in range(3)))
        write_plan_run(self.out, self.spec, client)
        plan = load_plan(self.out / "scene-plan.json")
        summary = summarize(plan)
        self.assertEqual((summary["chapters"], summary["scenes"], summary["lines"]), (3, 15, 54))
        self.assertEqual(plan.title, "How a web page reaches you")
        self.assertEqual([chapter.title for chapter in plan.chapters], ["Part 1", "Part 2", "Part 3"])
        self.assertEqual(plan.chapters[1].scene_ids, [f"scene-{n:02d}" for n in range(6, 11)])
        self.assertEqual(plan.scenes[-1].narration[-1].id, "scene-15-line-04")
        self.assertEqual(plan.scenes[6].narration[1].highlight_node_id, "dns")
        record = self.saved("llm-response.json")
        self.assertEqual(record["mode"], "chapters")
        self.assertEqual([a["step"] for a in record["attempts"]],
                         ["outline", "chapter-01", "chapter-02", "chapter-03"])
        self.assertAlmostEqual(record["estimatedCostUsd"], 4 * (1200 * 4 + 3400 * 20) / 1e6)
        self.assertEqual([c["plannedSeconds"] for c in self.saved("outline.json")["chapters"]], [75, 75, 75])

    def test_chapter_requests_carry_the_outline_and_the_previous_chapter(self):
        client = FakeClient(response(outline_output()), *(response(model_output()) for _ in range(3)))
        write_plan_run(self.out, self.spec, client)
        outline_call, first, second, last = client.calls
        self.assertTrue(outline_call["system"].startswith("You plan the chapters"))
        self.assertNotIn("chapters", first["output_config"]["format"]["schema"]["properties"])
        self.assertIn("Long videos", first["system"])
        self.assertIn("This is the opening chapter", first["messages"][0]["content"])
        self.assertNotIn("previous chapter ended", first["messages"][0]["content"])
        request = second["messages"][0]["content"]
        self.assertIn("chapter 2 of 3", request)
        self.assertIn("3. Part 3: Explain part 3.", request)
        self.assertIn("- Second idea", request)
        self.assertIn("about 185 words", request)
        last_line = model_output()["scenes"][-1]["narration"][-1]["text"]
        self.assertIn(f"> {last_line}", request)
        self.assertIn("This is the final chapter", last["messages"][0]["content"])

    def test_outline_problems_get_one_repair_request(self):
        client = FakeClient(response(outline_output((150, 100))), response(outline_output()),
                            *(response(model_output()) for _ in range(3)))
        write_plan_run(self.out, self.spec, client)
        repair = client.calls[1]["messages"][2]["content"]
        self.assertIn("chapters: use 3 to 4 chapters, not 2", repair)
        self.assertIn("targetSeconds add up to 250", repair)

    def test_a_chapter_that_fails_twice_stops_the_run_and_keeps_the_evidence(self):
        client = FakeClient(response(outline_output()), response(model_output(broken_highlight)),
                            response(model_output(broken_highlight)))
        with self.assertRaisesRegex(PlannerError, "No usable scene plan for chapter 1 of 3"):
            write_plan_run(self.out, self.spec, client)
        record = self.saved("llm-response.json")
        self.assertEqual(record["status"], "failed")
        self.assertEqual([a["step"] for a in record["attempts"]], ["outline", "chapter-01", "chapter-01"])
        self.assertFalse((self.out / "scene-plan.json").exists())

    def test_outline_review_checks_count_length_and_language(self):
        self.assertEqual(review_outline(json.dumps(outline_output()), self.spec)[1], [])
        _, problems = review_outline(json.dumps(outline_output((75, 75, 30))), self.spec)
        self.assertIn("chapters[2].targetSeconds: 30 is outside 40 to 150", problems)
        data = outline_output()
        data["chapters"][0]["title"] = "第一部分"
        data["chapters"][1].pop("goal")
        _, problems = review_outline(json.dumps(data), self.spec)
        self.assertEqual(problems, ["chapters[1].goal: Field required"])
        data["chapters"][1]["goal"] = "Explain."
        _, problems = review_outline(json.dumps(data), self.spec)
        self.assertTrue(any(p.startswith("chapters[0].title: must be English") for p in problems), problems)

    def test_lengths_and_chapter_counts(self):
        self.assertEqual(rescale([70, 80, 70], 225), [72, 82, 71])
        self.assertEqual(sum(rescale([61, 79, 73, 88], 300)), 300)
        self.assertEqual([chapter_range(s) for s in (181, 420, 600)], [(3, 4), (5, 7), (7, 8)])
        self.assertIn("Chapters: 5 to 7", outline_request(make_spec(TOPIC, AUDIENCE, 420)[0]))

    def test_plan_command_reports_chapters_and_cost(self):
        client = FakeClient(response(outline_output()), *(response(model_output()) for _ in range(3)))
        stdout = io.StringIO()
        with patch("capstone_script.__main__._client", return_value=client), \
                patch("capstone_script.__main__.load_env_file"), redirect_stdout(stdout):
            code = main(["plan", "--topic", TOPIC, "--duration", "225", "--out", str(self.out)])
        self.assertEqual(code, 0)
        self.assertIn("3 chapters | 15 scenes | 54 lines", stdout.getvalue())
        self.assertIn("API about $0.29 at list prices", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
