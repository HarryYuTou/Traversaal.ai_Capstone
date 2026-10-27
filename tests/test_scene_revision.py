"""Joint semantic repair is bounded, atomic and still subject to immutable review."""

import copy
import json
from pathlib import Path
import unittest

from capstone_script.planner import PlannerError
from capstone_script.review import Issue
from capstone_script.scene_plan import dump_plan, load_plan, summarize, validate_plan
from capstone_script.scene_revision import check_scene_revision, revise_scenes, revision_scene_ids
from capstone_script.visual_repair import check_visual_repair
from test_planner import FakeClient, as_model_output, response
from test_process_contract import process_plan
from test_scene_plan import valid_data, with_chapters, with_new_templates

ROOT = Path(__file__).resolve().parents[1]


def finding(location="scene-01", category="sync", severity="low"):
    return Issue(location=location, category=category, severity=severity,
                 problem="The claim does not match the depicted actions.")


def spec_for(plan):
    return {"topic": "Why does another counter reduce waiting?", "audience": "General audience",
            "targetDurationSec": 60, "reviewWordTarget": summarize(plan)["words"]}


def subset_output(plan, scene_ids):
    data = json.loads(dump_plan(plan))
    data["scenes"] = [scene for scene in data["scenes"] if scene["id"] in scene_ids]
    data.pop("chapters", None)
    return as_model_output(data)


class SceneRevisionTests(unittest.TestCase):
    def setUp(self):
        self.plan = load_plan(ROOT / "fixtures/scene-plan.valid.json")
        self.spec = spec_for(self.plan)

    def check(self, data, ids=("scene-01",), plan=None, spec=None):
        return check_scene_revision(json.dumps(data), plan or self.plan, ids, spec or self.spec)

    def test_blocker_locations_resolve_in_plan_order_and_ignore_low_accuracy(self):
        issues = [finding("scene-03", "accuracy", "high"), finding("scene-01-line-02"),
                  finding("scene-01"), finding("scene-02", "accuracy", "low"),
                  finding("plan", "clarity", "high")]
        self.assertEqual(revision_scene_ids(self.plan, issues), ["scene-01", "scene-03"])
        self.assertEqual(revision_scene_ids(self.plan, [finding("unknown", "accuracy", "medium")]),
                         [scene.id for scene in self.plan.scenes])

    def test_revises_two_scenes_atomically_and_preserves_other_content_and_chapters(self):
        source = validate_plan(with_chapters(valid_data()))
        before = dump_plan(source)
        data = subset_output(source, ["scene-01", "scene-02"])
        data["scenes"][0]["narration"][0]["text"] = "You enter a website address and ask the browser to find and display that page."
        data["scenes"][1]["narration"][0]["text"] = "Your browser needs the server's numbered address before it can connect."
        data["scenes"][0]["visual"]["concept"]["statement"] = "The browser finds the server and asks for the page."
        data["projectId"] = "ignored-output-metadata"
        data["title"] = "Ignored output title"
        candidate, problems = self.check(data, ("scene-01", "scene-02"), source)
        self.assertEqual(problems, [])
        self.assertNotEqual(candidate.scenes[0].narration, source.scenes[0].narration)
        self.assertNotEqual(candidate.scenes[1].narration, source.scenes[1].narration)
        self.assertEqual(candidate.scenes[2:], source.scenes[2:])
        self.assertEqual(candidate.chapters, source.chapters)
        self.assertEqual(candidate.title, source.title)
        self.assertEqual(candidate.project_id, source.project_id)
        self.assertEqual(dump_plan(source), before)

    def test_missing_extra_duplicate_reordered_or_unexpected_scene_is_rejected(self):
        original = subset_output(self.plan, ["scene-01", "scene-02"])
        for kind in ("missing", "extra", "duplicate", "reordered", "unexpected"):
            with self.subTest(kind=kind):
                data = copy.deepcopy(original)
                if kind == "missing":
                    data["scenes"].pop()
                elif kind == "extra":
                    data["scenes"].append(subset_output(self.plan, ["scene-03"])["scenes"][0])
                elif kind == "duplicate":
                    data["scenes"][1] = copy.deepcopy(data["scenes"][0])
                elif kind == "reordered":
                    data["scenes"].reverse()
                else:
                    data["scenes"][1]["id"] = "scene-unknown"
                candidate, problems = self.check(data, ("scene-01", "scene-02"))
                self.assertIsNone(candidate)
                self.assertIn("exactly the requested scene ids", " ".join(problems))

    def test_requested_ids_must_exist_once_in_original_order(self):
        for ids in ([], ["unknown"], ["scene-01", "scene-01"], ["scene-02", "scene-01"]):
            with self.subTest(ids=ids):
                candidate, problems = self.check(subset_output(self.plan, ids), ids)
                self.assertIsNone(candidate)
                self.assertIn("unique subset", " ".join(problems))

    def test_narration_ids_order_count_and_highlights_cannot_change(self):
        for kind in ("id", "order", "count", "highlight"):
            with self.subTest(kind=kind):
                data = subset_output(self.plan, ["scene-01"])
                lines = data["scenes"][0]["narration"]
                if kind == "id":
                    lines[0]["id"] = "renamed-line"
                elif kind == "order":
                    lines[0], lines[1] = lines[1], lines[0]
                elif kind == "count":
                    lines.pop(0)
                else:
                    lines[0]["highlight"] = "0"
                candidate, problems = self.check(data)
                self.assertIsNone(candidate)
                self.assertIn("ids, order, count and highlights", " ".join(problems))

    def test_regular_narration_limits_still_apply(self):
        data = subset_output(self.plan, ["scene-01"])
        data["scenes"][0]["narration"][0]["text"] = " ".join(["word"] * 26)
        candidate, problems = self.check(data)
        self.assertIsNone(candidate)
        self.assertIn("at most 25", " ".join(problems))

    def test_template_cannot_change_even_when_new_template_is_valid(self):
        data = subset_output(self.plan, ["scene-01"])
        scene = data["scenes"][0]
        scene["template"] = "flow"
        scene["visual"] = {"title": "A different template", "flow": {
            "nodes": [{"id": "first", "label": "First"}, {"id": "second", "label": "Second"}]}}
        for index, line in enumerate(scene["narration"]):
            line["highlight"] = "first" if index == 0 else "second"
        candidate, problems = self.check(data)
        self.assertIsNone(candidate)
        self.assertIn("template unchanged", " ".join(problems))

    def test_quote_words_and_attribution_remain_immutable(self):
        raw = {"schemaVersion": "1", "projectId": "quote-test", "title": "A quoted observation",
               "scenes": [{"id": "scene-01", "purpose": "Read an exact quotation.", "template": "quote",
                           "visual": {"title": "An observation", "quote": "Two people leave together.", "author": "Example narrator"},
                           "narration": [{"id": "scene-01-line-01", "text": "Two people leave together.", "highlightQuote": True}]}]}
        plan = validate_plan(raw)
        for kind in ("narration", "quote", "author"):
            with self.subTest(kind=kind):
                data = subset_output(plan, ["scene-01"])
                scene = data["scenes"][0]
                if kind == "narration":
                    scene["narration"][0]["text"] = "Two people arrive together."
                else:
                    scene["visual"]["quote"][kind] = "Two people arrive together." if kind == "quote" else "Someone else"
                candidate, problems = self.check(data, plan=plan, spec=spec_for(plan))
                self.assertIsNone(candidate)
                self.assertTrue(any("quot" in problem for problem in problems), problems)

    def test_object_identity_and_full_event_coverage_are_required(self):
        plan = validate_plan(process_plan())
        for kind in ("color", "coverage", "invalid-event"):
            with self.subTest(kind=kind):
                data = subset_output(plan, ["scene-01"])
                visual = data["scenes"][0]["visual"]["process"]
                if kind == "color":
                    visual["actors"][0]["color"] = "secondary"
                elif kind == "coverage":
                    visual["events"].pop(1)
                else:
                    visual["events"][0]["stationIds"] = ["missing", "two"]
                candidate, problems = self.check(data, plan=plan, spec=spec_for(plan))
                self.assertIsNone(candidate)
                expected = {"color": "identity color", "coverage": "no process event",
                            "invalid-event": "every id must reference"}[kind]
                self.assertIn(expected, " ".join(problems))

    def test_continuing_identity_can_restore_previous_color_and_unique_station_id(self):
        raw = process_plan()
        next_scene = copy.deepcopy(raw["scenes"][0])
        next_scene["id"] = "scene-02"
        for index, line in enumerate(next_scene["narration"], 1):
            line["id"] = f"scene-02-line-{index:02d}"
        next_scene["visual"]["actors"][0]["color"] = "secondary"
        next_scene["visual"]["stations"][0]["id"] = "renamed-one"
        for event in next_scene["visual"]["events"]:
            event["stationIds"] = ["renamed-one" if item == "one" else item for item in event["stationIds"]]
        raw["scenes"].append(next_scene)
        plan = validate_plan(raw)
        data = subset_output(plan, ["scene-02"])
        visual = data["scenes"][0]["visual"]["process"]
        visual["actors"][0]["color"] = "accent"
        visual["stations"][0]["id"] = "one"
        for event in visual["events"]:
            event["stationIds"] = ["one" if item == "renamed-one" else item for item in event["stationIds"]]
        candidate, problems = self.check(data, ("scene-02",), plan, spec_for(plan))
        self.assertEqual(problems, [])
        self.assertEqual(candidate.scenes[1].visual.actors[0].color, "accent")
        self.assertEqual(candidate.scenes[1].visual.stations[0].id, "one")
        self.assertEqual(candidate.scenes[0], plan.scenes[0])

    def test_one_invalid_replacement_rejects_the_whole_batch_without_mutation(self):
        before = dump_plan(self.plan)
        data = subset_output(self.plan, ["scene-01", "scene-02"])
        data["scenes"][0]["narration"][0]["text"] = "Your browser receives a website address and begins finding the requested page."
        data["scenes"][1]["visual"]["flow"]["nodes"].pop()
        candidate, problems = self.check(data, ("scene-01", "scene-02"))
        self.assertIsNone(candidate)
        self.assertTrue(problems)
        self.assertEqual(dump_plan(self.plan), before)

    def test_total_word_budget_including_measured_extension_is_required(self):
        data = subset_output(self.plan, ["scene-01"])
        for line in data["scenes"][0]["narration"]:
            line["text"] = "Look here."
        candidate, problems = self.check(data)
        self.assertIsNone(candidate)
        self.assertIn("revised script has", " ".join(problems))
        unchanged = subset_output(self.plan, ["scene-01"])
        candidate, problems = self.check(unchanged, spec={"targetDurationSec": 30})
        self.assertIsNone(candidate)
        self.assertIn("revised script has", " ".join(problems))

    def test_opt_in_shared_validator_allows_text_but_default_remains_strict(self):
        data = subset_output(self.plan, ["scene-01"])
        data["scenes"][0]["narration"][0]["text"] = "Your browser receives a website address and begins finding the requested page."
        accepted, problems = check_visual_repair(json.dumps(data), self.plan, "scene-01", allow_narration_edits=True)
        self.assertEqual(problems, [])
        self.assertIsNotNone(accepted)
        rejected, problems = check_visual_repair(json.dumps(data), self.plan, "scene-01")
        self.assertIsNone(rejected)
        self.assertIn("narration unchanged", " ".join(problems))

    def test_joint_request_contains_full_context_findings_and_uses_bounded_schema(self):
        ids = ["scene-01", "scene-02"]
        client = FakeClient(response(subset_output(self.plan, ids)))
        attempts = []
        candidate, revised = revise_scenes(self.plan, [finding("scene-02", "accuracy", "medium"), finding()],
                                            self.spec, client, "Reference evidence.", attempts=attempts, round_number=2)
        self.assertEqual(revised, ids)
        self.assertEqual(candidate, self.plan)
        self.assertEqual(len(client.calls), 1)
        call = client.calls[0]
        text = call["messages"][0]["content"]
        self.assertIn("scene-05", text)
        self.assertIn("Previous audit findings", text)
        self.assertIn("Reference evidence.", text)
        self.assertIn("Revision round: 2", text)
        self.assertIn("do not erase the explanation", call["system"])
        self.assertEqual(call["output_config"]["format"]["schema"]["$defs"]["_OutputScene"]["properties"]["template"]["enum"],
                         ["concept", "flow"])
        self.assertEqual(attempts[0]["step"], "scene-revision-2")

    def test_only_one_validation_retry_and_original_stays_unchanged(self):
        before = dump_plan(self.plan)
        bad = subset_output(self.plan, ["scene-01"])
        bad["scenes"] = []
        client = FakeClient(response(bad), response(bad))
        attempts = []
        with self.assertRaisesRegex(PlannerError, "No usable scene revision"):
            revise_scenes(self.plan, [finding()], self.spec, client, attempts=attempts)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(dump_plan(self.plan), before)

    def test_retry_can_return_valid_candidate_without_extra_call(self):
        client = FakeClient(response(text="not json"), response(subset_output(self.plan, ["scene-01"])))
        candidate, ids = revise_scenes(self.plan, [finding()], self.spec, client)
        self.assertEqual(candidate, self.plan)
        self.assertEqual(ids, ["scene-01"])
        self.assertEqual(len(client.calls), 2)

    def test_no_blockers_skip_request_and_overlarge_template_set_fails_before_request(self):
        client = FakeClient()
        candidate, ids = revise_scenes(self.plan, [finding(category="accuracy")], self.spec, client)
        self.assertIs(candidate, self.plan)
        self.assertEqual(ids, [])
        large_plan = validate_plan(with_new_templates(valid_data()))
        with self.assertRaisesRegex(PlannerError, "at most 3"):
            revise_scenes(large_plan, [finding("plan")], spec_for(large_plan), client)
        self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
