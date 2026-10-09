"""ScenePlan contract tests: structure, cross-references and the exported schema."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from capstone_script.__main__ import main
from capstone_script.scene_plan import (
    PlanValidationError, dump_plan, json_schema, load_plan, summarize, validate_plan,
)

ROOT = Path(__file__).resolve().parents[1]
VALID = ROOT / "fixtures" / "scene-plan.valid.json"
INVALID = ROOT / "fixtures" / "scene-plan.invalid.json"
SCHEMA = ROOT / "schemas" / "scene-plan.schema.json"


def valid_data():
    return json.loads(VALID.read_text(encoding="utf-8"))


class ScenePlanTests(unittest.TestCase):
    def problems(self, data):
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(data)
        return caught.exception.problems

    def assert_problem(self, data, expected):
        problems = self.problems(data)
        self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_valid_fixture_has_the_formal_sample_shape(self):
        summary = summarize(load_plan(VALID))
        self.assertEqual(summary["scenes"], 5)
        self.assertEqual(summary["lines"], 18)
        self.assertEqual(summary["templates"], ["concept", "flow"])
        # 60-90 s target: speech alone must not already fall outside it.
        self.assertTrue(60 <= summary["estimatedSpeechSeconds"] <= 90, summary)

    def test_round_trip_keeps_the_plan_unchanged(self):
        self.assertEqual(json.loads(dump_plan(load_plan(VALID))), valid_data())

    def test_structural_errors_name_the_json_location(self):
        cases = {
            "unknown field": (lambda d: d["scenes"][0]["visual"].update(color="red"),
                              "scenes[0].visual.color: Extra inputs are not permitted"),
            "unknown template": (lambda d: d["scenes"][1].update(template="chart"),
                                 "scenes[1]: Input tag 'chart'"),
            "long node label": (lambda d: d["scenes"][1]["visual"]["nodes"][0].update(label="X" * 25),
                                "scenes[1].visual.nodes[0].label: String should have at most 24 characters"),
            "one node": (lambda d: d["scenes"][1]["visual"].update(nodes=d["scenes"][1]["visual"]["nodes"][:1]),
                         "scenes[1].visual.nodes: List should have at least 2 items"),
            "four points": (lambda d: d["scenes"][0]["visual"]["points"].append("Fourth"),
                            "scenes[0].visual.points: List should have at most 3 items"),
            "too many scenes": (lambda d: d.update(scenes=d["scenes"] * 3),
                                "scenes: List should have at most 12 items"),
            "path-like id": (lambda d: d["scenes"][0].update(id="../scene"),
                             "scenes[0].id: String should match pattern"),
            "missing narration": (lambda d: d["scenes"][0].pop("narration"),
                                  "scenes[0].narration: Field required"),
            "future version": (lambda d: d.update(schemaVersion="2"), "schemaVersion: Input should be '1'"),
            "node highlight in a concept scene": (
                lambda d: d["scenes"][0]["narration"][0].update(highlightNodeId="browser"),
                "scenes[0].narration[0].highlightNodeId: Extra inputs are not permitted"),
            "point index as text": (lambda d: d["scenes"][0]["narration"][2].update(highlightPointIndex="0"),
                                    "scenes[0].narration[2].highlightPointIndex"),
            "point index as boolean": (lambda d: d["scenes"][0]["narration"][2].update(highlightPointIndex=True),
                                       "scenes[0].narration[2].highlightPointIndex"),
        }
        for name, (change, expected) in cases.items():
            with self.subTest(case=name):
                data = valid_data()
                change(data)
                self.assert_problem(data, expected)

    def test_cross_reference_errors(self):
        cases = {
            "duplicate scene id": (lambda d: d["scenes"][1].update(id="scene-01"),
                                   "scenes[1].id: duplicate scene id 'scene-01'"),
            "duplicate narration id": (lambda d: d["scenes"][1]["narration"][0].update(id="scene-01-line-01"),
                                       "scenes[1].narration[0].id: duplicate narration id 'scene-01-line-01'"),
            "duplicate node id": (lambda d: d["scenes"][1]["visual"]["nodes"][1].update(id="browser"),
                                  "scenes[1].visual.nodes[1].id: duplicate node id 'browser'"),
            "missing node": (lambda d: d["scenes"][1]["narration"][0].update(highlightNodeId="server"),
                             "scenes[1].narration[0].highlightNodeId: 'server' is not a node in this scene"),
            "point out of range": (lambda d: d["scenes"][0]["narration"][4].update(highlightPointIndex=3),
                                   "scenes[0].narration[4].highlightPointIndex: 3 is out of range"),
            "too many words": (lambda d: d["scenes"][0]["narration"][0].update(text=" ".join(["word"] * 26)),
                               "scenes[0].narration[0].text: has 26 words"),
            "no words": (lambda d: d["scenes"][0]["narration"][0].update(text="..."),
                         "scenes[0].narration[0].text: must contain spoken words"),
            "not English": (lambda d: d["scenes"][0]["narration"][0].update(text="Hello κοσμος"),
                            "scenes[0].narration[0].text: must be English"),
        }
        for name, (change, expected) in cases.items():
            with self.subTest(case=name):
                data = valid_data()
                change(data)
                self.assert_problem(data, expected)

    def test_exactly_25_words_are_allowed(self):
        data = valid_data()
        data["scenes"][0]["narration"][0]["text"] = " ".join(["word"] * 25)
        validate_plan(data)

    def test_invalid_fixture_reports_every_problem_at_once(self):
        with self.assertRaises(PlanValidationError) as caught:
            load_plan(INVALID)
        self.assertEqual(caught.exception.problems, [
            "scenes[0].narration[0].highlightPointIndex: 3 is out of range; this scene has 3 points",
            "scenes[1].narration[0].id: duplicate narration id 'scene-01-line-01'; "
            "narration ids must be unique across the plan",
            "scenes[1].narration[1].highlightNodeId: 'server' is not a node in this scene",
            "scenes[1].narration[2].text: has 28 words; split it into lines of at most 25",
        ])

    def test_malformed_json_is_a_plan_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "plan.json"
            path.write_text('{"schemaVersion": "1",', encoding="utf-8")
            with self.assertRaisesRegex(PlanValidationError, "not valid JSON"):
                load_plan(path)


class SchemaExportTests(unittest.TestCase):
    def test_committed_schema_matches_the_models(self):
        self.assertEqual(json.loads(SCHEMA.read_text(encoding="utf-8")), json_schema(),
                         "Run: python -m capstone_script schema")

    def test_schema_accepts_the_valid_fixture_and_rejects_structural_errors(self):
        validator = jsonschema.Draft202012Validator(json_schema())
        self.assertEqual(list(validator.iter_errors(valid_data())), [])
        for change in (lambda d: d["scenes"][0]["visual"].update(color="red"),
                       lambda d: d["scenes"][1].update(template="chart"),
                       lambda d: d["scenes"][0].update(id="../scene")):
            data = valid_data()
            change(data)
            self.assertFalse(validator.is_valid(data))

    def test_schema_alone_does_not_catch_cross_reference_errors(self):
        # Documents the gap: other languages must also run these checks.
        data = valid_data()
        data["scenes"][1]["narration"][0]["id"] = "scene-01-line-01"
        self.assertTrue(jsonschema.Draft202012Validator(json_schema()).is_valid(data))
        with self.assertRaises(PlanValidationError):
            validate_plan(data)


class CommandLineTests(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_validate_reports_a_summary(self):
        code, out, _ = self.run_main("validate", "--plan", str(VALID))
        self.assertEqual(code, 0)
        self.assertIn("Valid scene plan: 5 scenes, 18 narration lines", out)

    def test_validate_lists_problems_and_fails(self):
        code, _, err = self.run_main("validate", "--plan", str(INVALID))
        self.assertEqual(code, 1)
        self.assertEqual(err.count("\n  - "), 4)

    def test_missing_file_fails_cleanly(self):
        code, _, err = self.run_main("validate", "--plan", str(ROOT / "fixtures" / "missing.json"))
        self.assertEqual(code, 1)
        self.assertIn("ERROR", err)

    def test_schema_command_writes_the_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "nested" / "scene-plan.schema.json"
            code, _, _ = self.run_main("schema", "--output", str(output))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), json_schema())


if __name__ == "__main__":
    unittest.main()
