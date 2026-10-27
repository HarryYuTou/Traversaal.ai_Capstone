"""Semantic repair is bounded, preserves identity and never silently ships unresolved sync."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from capstone_script.long_form import visual_continuity
from capstone_script.planner import PlannerError, make_spec, write_json
from capstone_script.review import Issue, check_review, write_review
from capstone_script.scene_plan import dump_plan, load_plan, validate_plan
from capstone_script.visual_repair import affected_scene_ids, check_visual_repair
from test_planner import FakeClient, as_model_output, response
from test_process_contract import process_plan
from test_review import review_output

ROOT = Path(__file__).resolve().parents[1]


class VisualRepairTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan(ROOT / "fixtures/scene-plan.valid.json")
        self.issue = {"location": "scene-01-line-01", "category": "sync", "severity": "low",
                      "problem": "The visual statement does not show the narrated setup."}

    def replacement(self):
        data = json.loads(dump_plan(self.plan))
        data["scenes"] = data["scenes"][:1]
        data["scenes"][0]["visual"]["statement"] = "Follow a request from your browser to a web server."
        return as_model_output(data)

    def test_repair_keeps_narration_and_other_scenes(self):
        candidate, problems = check_visual_repair(json.dumps(self.replacement()), self.plan, "scene-01")
        self.assertEqual(problems, [])
        self.assertEqual(candidate.scenes[0].narration, self.plan.scenes[0].narration)
        self.assertEqual(candidate.scenes[1:], self.plan.scenes[1:])
        self.assertNotEqual(candidate.scenes[0].visual.statement, self.plan.scenes[0].visual.statement)

    def test_repair_cannot_rewrite_narration_to_hide_a_mismatch(self):
        data = self.replacement()
        data["scenes"][0]["narration"][0]["text"] = "An unrelated statement."
        candidate, problems = check_visual_repair(json.dumps(data), self.plan, "scene-01")
        self.assertIsNone(candidate)
        self.assertIn("narration unchanged", " ".join(problems))

    def test_process_repair_cannot_change_object_identity(self):
        source = validate_plan(process_plan())
        data = process_plan()
        data["scenes"][0]["visual"]["actors"][0]["color"] = "secondary"
        candidate, problems = check_visual_repair(json.dumps(as_model_output(data)), source, "scene-01")
        self.assertIsNone(candidate)
        self.assertIn("identity color", " ".join(problems))

    def test_line_locations_resolve_once_to_their_scene(self):
        issues = [Issue.model_validate(self.issue), Issue.model_validate(self.issue)]
        self.assertEqual(affected_scene_ids(self.plan, issues), ["scene-01"])

    def test_plan_wide_sync_includes_supporting_templates(self):
        issue = Issue.model_validate({**self.issue, "location": "plan"})
        self.assertEqual(affected_scene_ids(self.plan, [issue]), [scene.id for scene in self.plan.scenes])

    def test_sync_scene_narration_is_protected_from_initial_review_edits(self):
        result = review_output()
        result["issues"] = [self.issue]
        candidate, problems = check_review(json.dumps(result), self.plan, {"targetDurationSec": 75})
        self.assertIsNone(candidate)
        self.assertIn("Keep narration in scenes with sync issues unchanged", " ".join(problems))

    def test_final_audit_cannot_rewrite_the_plan_it_assesses(self):
        candidate, problems = check_review(json.dumps(review_output()), self.plan,
                                           {"targetDurationSec": 75}, audit_only=True)
        self.assertIsNone(candidate)
        self.assertIn("final audit", " ".join(problems))

    def test_visual_repair_is_rechecked_and_recorded(self):
        first = review_output(edits=[])
        first["issues"] = [self.issue]
        final = review_output(edits=[])
        final["issues"] = []
        client = FakeClient(response(first), response(self.replacement()), response(final))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "scene-plan.json").write_text(dump_plan(self.plan))
            spec, _ = make_spec("How a web request works", "Students", 75)
            write_json(run / "project-spec.json", spec)
            write_review(run, client)
            record = json.loads((run / "review.json").read_text())
            self.assertEqual(record["visualReview"]["status"], "passed")
            self.assertEqual(record["visualReview"]["repairedSceneIds"], ["scene-01"])
            self.assertEqual(record["issueResolutions"][0]["resolution"], "repaired-and-rechecked")
            self.assertEqual(record["finalIssues"], [])
            self.assertEqual(len(client.calls), 3)
            self.assertEqual(load_plan(run / "scene-plan.draft.json"), self.plan)

    def test_unresolved_visual_issue_stops_without_replacing_original(self):
        first = review_output(edits=[])
        first["issues"] = [self.issue]
        client = FakeClient(response(first), response(self.replacement()), response(first))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            original = dump_plan(self.plan)
            (run / "scene-plan.json").write_text(original)
            write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
            with self.assertRaisesRegex(PlannerError, "still has narration/action mismatches"):
                write_review(run, client)
            self.assertEqual((run / "scene-plan.json").read_text(), original)
            record = json.loads((run / "review.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["visualReview"]["status"], "needs-review")
            self.assertEqual(len(client.calls), 3)

    def test_recategorizing_unshown_comparison_as_accuracy_does_not_pass(self):
        first = review_output(edits=[])
        first["issues"] = [self.issue]
        final = review_output(edits=[])
        final["issues"] = [{**self.issue, "category": "accuracy", "severity": "medium",
                            "problem": "The comparison still lacks a visible baseline."}]
        client = FakeClient(response(first), response(self.replacement()), response(final))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            original = dump_plan(self.plan)
            (run / "scene-plan.json").write_text(original)
            write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
            with self.assertRaisesRegex(PlannerError, "unsupported factual claims"):
                write_review(run, client)
            self.assertEqual((run / "scene-plan.json").read_text(), original)
            record = json.loads((run / "review.json").read_text())
            self.assertEqual(record["visualReview"]["status"], "needs-review")
            self.assertEqual(record["visualReview"]["remainingIssues"][0]["category"], "accuracy")

    def test_initial_accuracy_issue_also_requires_an_immutable_recheck(self):
        initial = review_output(edits=[])
        initial["issues"] = [{**self.issue, "category": "accuracy", "severity": "medium"}]
        for resolved in (False, True):
            final = review_output(edits=[])
            final["issues"] = [] if resolved else initial["issues"]
            client = FakeClient(response(initial), response(final))
            with self.subTest(resolved=resolved), tempfile.TemporaryDirectory() as temporary:
                run = Path(temporary)
                original = dump_plan(self.plan)
                (run / "scene-plan.json").write_text(original)
                write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
                if resolved:
                    write_review(run, client)
                else:
                    with self.assertRaisesRegex(PlannerError, "unsupported factual claims"):
                        write_review(run, client)
                    self.assertEqual((run / "scene-plan.json").read_text(), original)
                record = json.loads((run / "review.json").read_text())
                self.assertEqual(record["visualReview"]["repairedSceneIds"], [])
                self.assertEqual(record["visualReview"]["status"], "passed" if resolved else "needs-review")
                self.assertEqual(len(client.calls), 2)

    def test_chapter_context_records_real_final_process_state(self):
        plan = validate_plan(process_plan())
        before = dump_plan(plan)
        context = visual_continuity(plan)["endingVisual"]
        self.assertEqual(context["finalQueue"], ["c"])
        self.assertEqual(context["finalService"], [])
        self.assertEqual(context["completedActorIds"], ["a", "b"])
        self.assertEqual(context["openStationIds"], ["one", "two"])
        self.assertEqual(dump_plan(plan), before)


if __name__ == "__main__":
    unittest.main()
