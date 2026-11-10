"""Semantic repair is bounded, preserves identity and never silently ships unresolved sync."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from capstone_script.long_form import visual_continuity
from capstone_script.planner import PlannerError, make_spec, write_json
from capstone_script.review import Issue, check_review, write_review
from capstone_script.scene_plan import dump_plan, load_plan, validate_plan
from capstone_script.visual_repair import affected_scene_ids, check_visual_repair
from test_planner import FakeClient, as_model_output, response
from test_process_contract import event, process_plan
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

    def test_custom_repair_changes_acting_without_redrawing_identity(self):
        source = load_plan(ROOT / "fixtures/scene-plan.custom-rigs.json")
        data = json.loads(dump_plan(source))
        data["scenes"] = data["scenes"][:1]
        track = data["scenes"][0]["visual"]["rigs"][0]["clips"][0]["tracks"][0]
        track["keyframes"][1]["easing"] = "ease-out"
        repaired, problems = check_visual_repair(json.dumps(as_model_output(data)), source, source.scenes[0].id)
        self.assertEqual(problems, [])
        self.assertIsNotNone(repaired)

        part = next(part for part in data["scenes"][0]["visual"]["rigs"][0]["parts"] if part["shapes"])
        part["shapes"][0]["fill"] = "#ff0000"
        rejected, problems = check_visual_repair(json.dumps(as_model_output(data)), source, source.scenes[0].id)
        self.assertIsNone(rejected)
        self.assertIn("part hierarchy and shapes", " ".join(problems))

    def test_contact_repair_cannot_drop_grounding_but_can_correct_its_anchor(self):
        source = load_plan(ROOT / "fixtures/scene-plan.spatial-quality.json")
        data = json.loads(dump_plan(source))
        data["scenes"] = data["scenes"][:1]
        data["scenes"][0]["visual"]["contacts"][0]["targetY"] = -1
        repaired, problems = check_visual_repair(json.dumps(as_model_output(data)), source, "scene-01")
        self.assertEqual(problems, [])
        self.assertIsNotNone(repaired)
        data["scenes"][0]["visual"]["contacts"] = []
        rejected, problems = check_visual_repair(json.dumps(as_model_output(data)), source, "scene-01")
        self.assertIsNone(rejected)
        self.assertIn("Preserve authored contact relationships", " ".join(problems))

    def test_closed_baseline_repair_keeps_counter_without_inventing_an_opening(self):
        data = process_plan()
        scene = data["scenes"][0]
        scene["visual"]["title"] = "One counter open"
        scene["visual"]["events"] = [event("start", ("a",), ("one",), 0),
                                       event("hold", line=1),
                                       event("finish", ("a",), ("one",), 2),
                                       event("arrive", ("c",), line=3)]
        scene["narration"][0]["text"] = "One shopper steps up while the others wait in line."
        scene["narration"][1]["text"] = "Only one counter is open, so it serves one shopper at a time."
        scene["narration"][2]["text"] = "That shopper finishes and leaves through the exit."
        source = validate_plan(data)
        repaired_data = copy.deepcopy(data)
        repaired_data["scenes"][0]["visual"]["stations"][1]["initialState"] = "closed"

        repaired, problems = check_visual_repair(json.dumps(as_model_output(repaired_data)), source, "scene-01")

        self.assertEqual(problems, [])
        self.assertEqual(repaired.scenes[0].narration, source.scenes[0].narration)
        self.assertEqual(repaired.scenes[0].visual.events, source.scenes[0].visual.events)
        stations = repaired.scenes[0].visual.stations
        self.assertEqual([station.id for station in stations], ["one", "two"])
        self.assertEqual(stations[1].initial_state, "closed")
        self.assertEqual(stations[1].color, source.scenes[0].visual.stations[1].color)

        # Identity preservation still applies: hiding the counter by removing it
        # is not a substitute for authoring its real closed state.
        repaired_data["scenes"][0]["visual"]["stations"].pop()
        rejected, problems = check_visual_repair(json.dumps(as_model_output(repaired_data)), source, "scene-01")
        self.assertIsNone(rejected)
        self.assertIn("Preserve object 'two'", " ".join(problems))

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
        client = FakeClient(response(first), response(self.replacement()), response(first),
                            response(self.replacement()), response(first),
                            response(self.replacement()), response(first))
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
            self.assertEqual(len(client.calls), 7)
            self.assertEqual(len(record["visualReview"]["revisionRounds"]), 2)
            self.assertFalse((run / "scene-plan.draft.json").exists())

    def test_recategorizing_unshown_comparison_as_accuracy_does_not_pass(self):
        first = review_output(edits=[])
        first["issues"] = [self.issue]
        final = review_output(edits=[])
        final["issues"] = [{**self.issue, "category": "accuracy", "severity": "medium",
                            "problem": "The comparison still lacks a visible baseline."}]
        client = FakeClient(response(first), response(self.replacement()), response(final),
                            response(self.replacement()), response(final),
                            response(self.replacement()), response(final))
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
            client = FakeClient(response(initial), response(final),
                                *([] if resolved else [response(self.replacement()), response(final),
                                                       response(self.replacement()), response(final)]))
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
                self.assertEqual(len(client.calls), 2 if resolved else 6)

    def test_accuracy_review_then_new_sync_finding_is_revised_and_audited(self):
        initial = review_output(edits=[])
        initial["issues"] = [{**self.issue, "category": "accuracy", "severity": "medium",
                              "problem": "The claimed result is not supported by the shown comparison."}]
        audit = review_output(edits=[])
        audit["issues"] = [self.issue]
        replacement = self.replacement()
        replacement["scenes"][0]["narration"][0]["text"] = "A request travels from your browser toward the website's server."
        clean = review_output(edits=[])
        clean["issues"] = []
        client = FakeClient(response(initial), response(audit), response(replacement), response(clean))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "scene-plan.json").write_text(dump_plan(self.plan))
            write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
            write_review(run, client)
            record = json.loads((run / "review.json").read_text())
            self.assertEqual(record["visualReview"]["status"], "passed")
            self.assertEqual(record["visualReview"]["repairedSceneIds"], [])
            self.assertEqual(record["visualReview"]["revisionRounds"][0]["sceneIds"], ["scene-01"])
            self.assertEqual(record["finalIssues"], [])
            self.assertEqual(record["changes"][0]["after"], replacement["scenes"][0]["narration"][0]["text"])
            self.assertEqual(load_plan(run / "scene-plan.draft.json"), self.plan)
            self.assertEqual(load_plan(run / "scene-plan.revision-01.json"), load_plan(run / "scene-plan.json"))
            self.assertIn(self.issue["problem"], client.calls[-1]["messages"][0]["content"])
            self.assertIn("Original draft for scope comparison", client.calls[-1]["messages"][0]["content"])
            self.assertEqual(len(client.calls), 4)

    def test_invalid_visual_only_repair_can_recover_without_promoting_it(self):
        first = review_output(edits=[])
        first["issues"] = [self.issue]
        clean = review_output(edits=[])
        clean["issues"] = []
        client = FakeClient(response(first), response(text="invalid json"), response(text="invalid json"),
                            response(first), response(self.replacement()), response(clean))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "scene-plan.json").write_text(dump_plan(self.plan))
            write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
            write_review(run, client)
            record = json.loads((run / "review.json").read_text())
            self.assertIn("visualRepairError", record["visualReview"])
            self.assertEqual(record["visualReview"]["status"], "passed")
            self.assertEqual(len(record["visualReview"]["revisionRounds"]), 1)
            self.assertEqual(load_plan(run / "scene-plan.draft.json"), self.plan)
            self.assertEqual(len(client.calls), 6)

    def test_final_audit_api_failure_never_promotes_a_valid_revision(self):
        first = review_output(edits=[])
        first["issues"] = [{**self.issue, "category": "accuracy", "severity": "medium"}]
        replacement = self.replacement()
        replacement["scenes"][0]["narration"][0]["text"] = "A request travels from your browser toward the website's server."
        client = FakeClient()
        responses = [response(first), response(first), response(replacement),
                     RuntimeError("simulated audit service failure")]
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            original = dump_plan(self.plan)
            (run / "scene-plan.json").write_text(original)
            write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
            with patch.object(client.beta.messages, "create", side_effect=responses) as request:
                with self.assertRaisesRegex(RuntimeError, "simulated audit service failure"):
                    write_review(run, client)
                self.assertEqual(request.call_count, 4)
            self.assertEqual((run / "scene-plan.json").read_text(), original)
            self.assertFalse((run / "scene-plan.draft.json").exists())
            candidate = load_plan(run / "scene-plan.revision-01.json")
            self.assertEqual(candidate.scenes[0].narration[0].text,
                             replacement["scenes"][0]["narration"][0]["text"])
            record = json.loads((run / "review.json").read_text())
            self.assertEqual(record["status"], "failed")
            self.assertEqual(record["visualReview"]["status"], "auditing")
            self.assertEqual(len(record["visualReview"]["revisionRounds"]), 1)
            self.assertNotIn("remainingIssues", record["visualReview"]["revisionRounds"][0])
            self.assertIn("simulated audit service failure", record["error"])

    def test_later_visual_repair_failure_discards_partial_batch_before_audit(self):
        first = review_output(edits=[])
        first["issues"] = [self.issue, {**self.issue, "location": "scene-02"}]
        clean = review_output(edits=[])
        clean["issues"] = []
        replacement = self.replacement()
        client = FakeClient(response(first), response(replacement), response(text="invalid json"),
                            response(text="invalid json"), response(clean))
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary)
            (run / "scene-plan.json").write_text(dump_plan(self.plan))
            write_json(run / "project-spec.json", make_spec("How a web request works", "Students", 75)[0])
            write_review(run, client)
            # The clean audit must assess the unchanged batch, not a mixture of
            # the first repaired scene and the later unrepaired scene.
            audit_request = client.calls[-1]["messages"][0]["content"]
            self.assertIn(self.plan.scenes[0].visual.statement, audit_request)
            self.assertNotIn(replacement["scenes"][0]["visual"]["concept"]["statement"], audit_request)
            self.assertEqual(load_plan(run / "scene-plan.json"), self.plan)
            self.assertEqual(load_plan(run / "scene-plan.draft.json"), self.plan)
            record = json.loads((run / "review.json").read_text())
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["visualReview"]["status"], "passed")
            self.assertEqual(record["visualReview"]["repairedSceneIds"], [])
            self.assertIn("visualRepairError", record["visualReview"])
            self.assertEqual(len(client.calls), 5)

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
