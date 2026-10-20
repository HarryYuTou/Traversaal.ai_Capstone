"""Workflow state, narration coverage and compact planner output; no API calls."""

import copy
import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from capstone_script.long_form import merge_chapters, review_outline
from capstone_script.planner import (
    _OutputPlan, coverage_problems, from_model_output, normalize_ids, output_schema,
    planner_prompt, review_plan, scene_range, write_plan_run,
)
from capstone_script.scene_plan import PlanValidationError, dump_plan, json_schema, scene_icons, validate_plan
from test_long_form import outline_output
from test_planner import VALID, FakeClient, as_model_output, response


def event(kind, actors=(), stations=(), line=0, start=0, end=1, end_line=None):
    return {"kind": kind, "actorIds": list(actors), "stationIds": list(stations),
            "startLine": line, "endLine": line if end_line is None else end_line,
            "startOffset": start, "endOffset": end}


def process_visual():
    return {"title": "Two stations process waiting work", "actorKind": "person",
            "actors": [{"id": name, "color": "accent", "label": ""} for name in ("a", "b", "c")],
            "stations": [{"id": name, "label": name.title(), "kind": "counter", "color": "ink"}
                         for name in ("one", "two")],
            "initialQueue": ["a", "b"], "initialService": [],
            "events": [event("start", ("a", "b"), ("one", "two"), 0), event("hold", line=1),
                       event("finish", ("a", "b"), ("one", "two"), 2), event("arrive", ("c",), line=3)]}


def process_plan():
    return {"schemaVersion": "1", "projectId": "process-test", "title": "A workflow explanation",
            "scenes": [{"id": "scene-01", "purpose": "Show parallel work and arrival.", "template": "process",
                        "visual": process_visual(),
                        "narration": [{"id": f"scene-01-line-{i:02d}", "text": text}
                                      for i, text in enumerate(("Two people enter the available stations.",
                                                               "Both stations now work at the same time.",
                                                               "The two people finish and leave.",
                                                               "Another person joins the waiting line."), 1)]}]}


def all_process_plan():
    data = copy.deepcopy(VALID)
    for scene in data["scenes"]:
        scene["template"] = "process"
        scene["visual"] = process_visual()
        scene["narration"] = [{"id": line["id"], "text": line["text"]} for line in scene["narration"]]
        count = len(scene["narration"])
        scene["visual"]["events"] = [event("start", ("a", "b"), ("one", "two"), 0),
                                      *(event("hold", line=i) for i in range(1, count - 1)),
                                      event("finish", ("a", "b"), ("one", "two"), count - 1)]
    return data


class ProcessContractTests(unittest.TestCase):
    def assert_problem(self, change, expected):
        data = process_plan()
        change(data["scenes"][0]["visual"])
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(data)
        self.assertTrue(any(expected in problem for problem in caught.exception.problems), caught.exception.problems)

    def test_parallel_workflow_roundtrips_with_a_small_required_output_shape(self):
        data = process_plan()
        plan = validate_plan(data)
        self.assertEqual(json.loads(dump_plan(plan)), data)
        self.assertEqual(scene_icons(plan.scenes[0]), [])
        self.assertEqual(coverage_problems(plan), [])
        jsonschema.validate(data, json_schema())
        output = as_model_output(data)
        _OutputPlan.model_validate(output)
        back, problems = from_model_output(output)
        self.assertEqual(problems, [])
        self.assertEqual(back, data)
        schema = output_schema(["process"])
        jsonschema.validate(output, schema)
        self.assertNotIn("MotionAction", schema["$defs"])
        for name in ("_OutputProcess", "ProcessActor", "ProcessStation", "ProcessOccupancy", "ProcessEvent"):
            part = schema["$defs"][name]
            self.assertEqual(set(part["required"]), set(part["properties"]))

    def test_actor_and_station_ids_are_unique_in_a_shared_namespace(self):
        self.assert_problem(lambda v: v["actors"][1].update(id="a"), "duplicate id")
        self.assert_problem(lambda v: v["stations"][1].update(id="one"), "duplicate id")
        self.assert_problem(lambda v: v["stations"][0].update(id="a"), "actor and station ids must be distinct")

    def test_initial_occupancy_cannot_duplicate_actors_or_stations(self):
        self.assert_problem(lambda v: v.update(initialQueue=["a", "a"]), "two queue positions")
        self.assert_problem(lambda v: v.update(initialQueue=["missing"]), "every id must name an actor")
        self.assert_problem(lambda v: v.update(initialService=[{"actorId": "a", "stationId": "one"}]),
                            "already occupies a queue or service position")
        self.assert_problem(lambda v: v.update(initialQueue=[], initialService=[
            {"actorId": "a", "stationId": "one"}, {"actorId": "b", "stationId": "one"}]), "already occupied")

    def test_arrival_cannot_recycle_a_visible_or_departed_actor(self):
        self.assert_problem(lambda v: v["events"][3].update(actorIds=["a"]), "cannot arrive again")
        self.assert_problem(lambda v: v["events"][0].update(kind="arrive", stationIds=[]), "cannot arrive again")

    def test_start_respects_queue_order_free_stations_and_pairs(self):
        self.assert_problem(lambda v: v["events"][0].update(actorIds=["b", "a"]), "front of the queue")
        self.assert_problem(lambda v: v.update(initialService=[{"actorId": "c", "stationId": "one"}]),
                            "requires free stations")
        self.assert_problem(lambda v: v["events"][0].update(stationIds=["one"]), "pair each actor")
        self.assert_problem(lambda v: v["events"][0].update(stationIds=["one", "one"]), "must not repeat")

    def test_finish_must_match_current_service(self):
        self.assert_problem(lambda v: v["events"][2].update(stationIds=["two", "one"]), "currently serving")
        self.assert_problem(lambda v: v["events"][2].update(actorIds=["c"], stationIds=["one"]), "currently serving")

    def test_event_shapes_and_references_are_checked(self):
        self.assert_problem(lambda v: v["events"][1].update(actorIds=["a"]), "hold requires empty")
        self.assert_problem(lambda v: v["events"][3].update(stationIds=["one"]), "arrive requires an empty")
        self.assert_problem(lambda v: v["events"][3].update(actorIds=[]), "needs at least one actor")
        self.assert_problem(lambda v: v["events"][3].update(actorIds=["missing"]), "reference this scene's actors")

    def test_event_order_nonoverlap_and_positive_narration_spans(self):
        self.assert_problem(lambda v: v["events"].reverse(), "chronological and must not overlap")
        self.assert_problem(lambda v: v["events"][1].update(startLine=0, startOffset=0.5), "must not overlap")
        self.assert_problem(lambda v: v["events"][1].update(startOffset=1), "end anchor must be after")
        self.assert_problem(lambda v: v["events"][3].update(endLine=4), "outside this scene's 4 narration lines")
        data = process_plan()
        data["scenes"][0]["visual"]["events"] = [event("start", ("a",), ("one",), start=0, end=0.5),
                                                     event("hold", start=0.5, end=1)]
        validate_plan(data)  # Touching endpoints are valid; timing coverage is a planner-level check.

    def test_coverage_accepts_deliberate_holds_but_rejects_unexplained_lines_and_no_change(self):
        data = process_plan()
        del data["scenes"][0]["visual"]["events"][1]
        self.assertIn("no process event covers this line", coverage_problems(validate_plan(data))[0])
        data["scenes"][0]["visual"]["events"] = [event("hold", end_line=3)]
        self.assertIn("at least one visible state change", coverage_problems(validate_plan(data))[0])

    def test_normalization_updates_every_process_reference_and_detects_collisions(self):
        data = process_plan()
        visual = data["scenes"][0]["visual"]
        visual["actors"][0]["id"] = "First Person"
        visual["stations"][0]["id"] = "Service Desk"
        visual["initialQueue"][0] = "First Person"
        for event_data in (visual["events"][0], visual["events"][2]):
            event_data["actorIds"][0] = "First Person"
            event_data["stationIds"][0] = "Service Desk"
        normalized = normalize_ids(data, "test")
        checked = validate_plan(normalized).scenes[0].visual
        self.assertEqual(checked.events[0].actor_ids[0], "first-person")
        self.assertEqual(checked.events[2].station_ids[0], "service-desk")
        visual["actors"][1]["id"] = "first-person"
        with self.assertRaisesRegex(PlanValidationError, "duplicate id"):
            validate_plan(normalize_ids(data, "test"))

    def test_initial_service_references_normalize_without_changing_event_anchors(self):
        data = process_plan()
        visual = data["scenes"][0]["visual"]
        visual["actors"][0]["id"] = "First Person"
        visual["stations"][0]["id"] = "Service Desk"
        visual.update(initialQueue=[], initialService=[{"actorId": "First Person", "stationId": "Service Desk"}],
                      events=[event("hold", end_line=3)])
        normalized = normalize_ids(data, "test")
        checked = validate_plan(normalized).scenes[0].visual
        self.assertEqual(checked.initial_service[0].actor_id, "first-person")
        self.assertEqual(checked.initial_service[0].station_id, "service-desk")
        self.assertEqual(checked.events[0].end_line, 3)

    def test_planner_handles_all_process_scenes_with_local_coverage_and_empty_highlights(self):
        data = all_process_plan()
        output = as_model_output(data)
        spec = {"projectId": "workflow", "topic": "How work moves", "audience": "Students",
                "targetDurationSec": 75, "allowedTemplates": ["process"]}
        plan, problems = review_plan(json.dumps(output), spec)
        self.assertEqual(problems, [])
        self.assertEqual({scene.template for scene in plan.scenes}, {"process"})
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient(response(output))
            saved = write_plan_run(Path(directory) / "run", spec, client)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(saved.scenes[0].visual.actor_kind, "person")
        output["scenes"][0]["narration"][0]["highlight"] = "a"
        self.assertIn('highlight must be ""', from_model_output(output)[1][0])

    def test_chapter_merge_preserves_process_state_and_local_event_indices(self):
        plan = validate_plan(process_plan())
        outline, _ = review_outline(json.dumps(outline_output()), {"targetDurationSec": 225})
        merged = merge_chapters({"projectId": "workflow"}, outline, [plan, plan, plan])
        self.assertEqual(len(merged.chapters), 3)
        self.assertEqual(merged.scenes[2].visual.events[-1].start_line, 3)
        self.assertEqual(merged.scenes[2].visual.initial_queue, ["a", "b"])
        self.assertEqual(merged.scenes[2].narration[0].id, "scene-03-line-01")

    def test_long_run_routes_to_process_and_reuses_the_compact_contract_for_all_chapters(self):
        output = as_model_output(all_process_plan())
        spec = {"projectId": "workflow", "topic": "How work moves", "audience": "Students",
                "targetDurationSec": 225}
        client = FakeClient(response({"templates": ["process"]}), response(outline_output()),
                            *(response(output) for _ in range(3)))
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "run"
            plan = write_plan_run(run, spec, client)
            self.assertEqual(len(plan.chapters), 3)
            self.assertEqual({scene.template for scene in plan.scenes}, {"process"})
            self.assertEqual(len(client.calls), 5)
            for chapter in client.calls[2:]:
                schema = chapter["output_config"]["format"]["schema"]
                self.assertEqual(schema["$defs"]["_OutputVisual"]["required"], ["title", "process"])
                self.assertIn("Allowed templates for this video: process.", chapter["messages"][0]["content"])
                self.assertNotIn("kind is move, follow-path", chapter["system"])

    def test_short_explanations_can_keep_two_coherent_scenes(self):
        self.assertEqual(scene_range(75), (2, 8))
        self.assertEqual(scene_range(90)[0], 2)

    def test_process_only_requests_explain_events_without_irrelevant_coordinate_instructions(self):
        prompt = planner_prompt(["process"])
        self.assertIn("- process:", prompt)
        self.assertIn("eight or more spoken words", prompt)
        self.assertIn("begin with a hold", prompt)
        self.assertIn("Prefer empty actor labels", prompt)
        self.assertIn("slowing accumulation even while unfinished work still grows", prompt)
        self.assertIn("actually show at least one arrival and one finish", prompt)
        self.assertIn("same observable state", prompt)
        self.assertNotIn("- motion:", prompt)
        self.assertNotIn("- map:", prompt)
        self.assertNotIn("- Icons:", prompt)
        self.assertNotIn("kind is move, follow-path", prompt)
        self.assertIn("- motion:", planner_prompt(["process", "motion"]))


if __name__ == "__main__":
    unittest.main()
