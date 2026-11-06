"""Semantic performance survives authoring and measured compilation without rewriting the story."""

import copy
import hashlib
import json
from pathlib import Path
import unittest

import jsonschema

from capstone_script.planner import _OutputPlan, from_model_output, normalize_ids, output_schema, planner_prompt
from capstone_script.scene_plan import CUE_ENTITY_KINDS, PlanValidationError, dump_plan, load_plan, validate_plan
from capstone_script.timeline import TimelineError, build_timeline, compile_motion_actions
from test_motion import action, entity, manifest, plan_data, scene, visual
from test_planner import as_model_output
from test_process_contract import event, process_plan
from test_process_timeline import build


def cue(kind="thrust", **changes):
    return {"entityId": "craft", "kind": kind, "startLine": 0, "endLine": 1,
            "startOffset": 0.25, "endOffset": 0.75, **changes}


class SemanticCueTests(unittest.TestCase):
    def test_each_supported_pair_roundtrips_and_compiles_without_changing_actions(self):
        for kind, entities in CUE_ENTITY_KINDS.items():
            for entity_kind in sorted(entities):
                with self.subTest(cue=kind, entity=entity_kind):
                    data = plan_data(scene(visual=visual(entities=[entity(kind=entity_kind)], cues=[cue(kind)])))
                    original = copy.deepcopy(data)
                    plan = validate_plan(data)
                    output = as_model_output(data)
                    _OutputPlan.model_validate(output)
                    jsonschema.validate(output, output_schema(["motion"]))
                    restored, problems = from_model_output(output)
                    self.assertEqual(problems, [])
                    self.assertEqual(json.loads(dump_plan(validate_plan(restored))), data)
                    compiled_scene = build_timeline(plan, manifest(plan))["scenes"][0]
                    compiled = compiled_scene["visual"]["cues"][0]
                    first, last = compiled_scene["lines"]
                    self.assertEqual(compiled["from"], first["from"] + round(first["durationInFrames"] * .25))
                    self.assertEqual(compiled["from"] + compiled["durationInFrames"],
                                     last["from"] + round(last["durationInFrames"] * .75))
                    # Both a cue and travel may occupy the same interval; the cue cannot alter travel.
                    without_cue = copy.deepcopy(data)
                    del without_cue["scenes"][0]["visual"]["cues"]
                    plain = validate_plan(without_cue)
                    plain_scene = build_timeline(plain, manifest(plain))["scenes"][0]
                    for field in ("entities", "paths", "actions"):
                        self.assertEqual(compiled_scene["visual"][field], plain_scene["visual"][field])
                    self.assertEqual(data, original)

    def test_cues_reject_wrong_assets_references_overlaps_and_bad_anchors(self):
        mutations = [
            ([cue("pack")], "cannot act on entity kind"),
            ([cue(entityId="missing")], "not an entity"),
            ([cue(endLine=2)], "outside this scene"),
            ([cue(endLine=0, endOffset=0.1)], "end anchor must be after"),
            ([cue(), cue(startOffset=.3)], "overlaps cue"),
            ([cue(complete=False)], "Extra inputs are not permitted"),
        ]
        for cues, expected in mutations:
            with self.subTest(expected=expected):
                with self.assertRaises(PlanValidationError) as caught:
                    validate_plan(plan_data(scene(visual=visual(cues=cues))))
                self.assertTrue(any(expected in item for item in caught.exception.problems), caught.exception.problems)

    def test_adjacent_operations_and_separate_entity_operations_are_valid(self):
        data = plan_data(scene(visual=visual(entities=[entity(kind="packet"), entity("receiver", "server")],
            cues=[cue("send", endLine=0, endOffset=.5), cue("receive", startOffset=.5),
                  cue("receive", entityId="receiver")])))
        validate_plan(data)

    def test_subframe_and_outside_intervals_fail_after_narration_measurement(self):
        data = plan_data(scene(visual=visual(cues=[cue(endLine=0, startOffset=0, endOffset=.001)])))
        plan = validate_plan(data)
        with self.assertRaisesRegex(TimelineError, "Motion cue 0 must span at least one frame"):
            build_timeline(plan, manifest(plan))
        lines = [{"from": 3, "durationInFrames": 30}]
        with self.assertRaisesRegex(TimelineError, "Motion cue 0 must span at least one frame"):
            compile_motion_actions(visual(actions=[], cues=[cue(startOffset=0, endLine=0, endOffset=1)]), lines, 0, 20)

    def test_slug_references_and_empty_cues_do_not_change_legacy_plans(self):
        data = plan_data(scene(visual=visual(cues=[cue()])))
        data["scenes"][0]["visual"]["entities"][0]["id"] = "Our Craft"
        data["scenes"][0]["visual"]["actions"][0]["entityId"] = "Our Craft"
        data["scenes"][0]["visual"]["cues"][0]["entityId"] = "Our Craft"
        plan = validate_plan(normalize_ids(data, "cue-test"))
        self.assertEqual(plan.scenes[0].visual.cues[0].entity_id, "our-craft")
        legacy = plan_data()
        self.assertEqual(json.loads(dump_plan(validate_plan(legacy))), legacy)

    def test_new_optional_fields_preserve_preexisting_narration_plan_hashes(self):
        # Captured from the pre-cue serializer; key ordering and float formatting are part of the hash.
        expected = ("b6d54a24a75e9b2983a24ffa82c12bd56b33f263e134a2ea659177d69a90e21d",
                    "f23584966beea9c490c20650cd3b0c488f03a55eea189098764321de6c9fa9f7")
        for legacy, previous in zip((plan_data(), process_plan()), expected):
            current = dump_plan(validate_plan(legacy))
            self.assertEqual(hashlib.sha256(current.encode()).hexdigest(), previous)

    def test_authoring_prompt_maps_semantics_and_preserves_orbital_physics(self):
        prompt = planner_prompt(["motion", "process"])
        for phrase in ("operation pack", "Same-entity cues must not overlap", "engine burn",
                       "one linear orbit action", "does not move it", "packing from a box alone"):
            # The prompt's explicit operation contract must remain available after template filtering.
            self.assertIn(phrase, prompt)


class ProcessOperationTests(unittest.TestCase):
    def operation_plan(self, operation, actor="box", station="workbench"):
        data = process_plan()
        v = data["scenes"][0]["visual"]
        v["actorKind"] = actor
        for item in v["stations"]:
            item.update(kind=station, operation=operation)
        return data

    def test_pack_uses_measured_service_and_only_an_authored_finish_seals(self):
        data = self.operation_plan("pack")
        scene_data = build(data)["scenes"][0]
        self.assertEqual({item["entityId"] for item in scene_data["visual"]["cues"]}, {"a", "b"})
        for item in scene_data["visual"]["cues"]:
            work = next(a for a in scene_data["visual"]["activities"]
                        if a["entityId"] == item["entityId"] and a["kind"] == "work")
            self.assertEqual((item["from"], item["durationInFrames"]), (work["from"], work["durationInFrames"]))
            self.assertTrue(item["complete"])
        data["scenes"][0]["visual"]["events"] = [event("start", ("a",), ("one",)),
                                                     event("hold", line=1, end_line=3)]
        ongoing = build(data)["scenes"][0]
        packing = ongoing["visual"]["cues"][0]
        self.assertFalse(packing["complete"])
        self.assertEqual(packing["from"] + packing["durationInFrames"],
                         ongoing["from"] + ongoing["durationInFrames"])
        self.assertFalse(any(item["kind"] == "complete" for item in ongoing["visual"]["activities"]))

    def test_operations_preserve_geometry_counts_and_explicit_event_schedule(self):
        for operation, actor, station, expected_targets in (
            ("pack", "box", "workbench", {"a", "b"}),
            ("scan", "box", "workbench", {"a", "b"}),
            ("scan", "packet", "server", {"a", "b"}),
            ("compute", "packet", "server", {"a", "b", "one", "two"}),
        ):
            with self.subTest(operation=operation, actor=actor):
                data = self.operation_plan(operation, actor, station)
                enhanced = build(data)["scenes"][0]
                for item in data["scenes"][0]["visual"]["stations"]:
                    item.pop("operation")
                generic = build(data)["scenes"][0]
                self.assertNotIn("cues", generic["visual"])
                self.assertEqual(enhanced["processTrace"], generic["processTrace"])
                enhanced_geometry = {key: value for key, value in enhanced["visual"].items() if key != "cues"}
                enhanced_geometry["entities"] = [{key: value for key, value in entity.items() if key != "packingState"}
                                                  for entity in enhanced_geometry["entities"]]
                self.assertEqual(enhanced_geometry, generic["visual"])
                self.assertEqual({item["entityId"] for item in enhanced["visual"]["cues"]}, expected_targets)
                self.assertTrue(all(item["kind"] == operation for item in enhanced["visual"]["cues"]))

    def test_invalid_operation_asset_combinations_are_rejected(self):
        for operation, actor, station in (("pack", "person", "workbench"), ("pack", "box", "counter"),
                                          ("compute", "box", "server"), ("scan", "coin", "server")):
            with self.subTest(operation=operation, actor=actor, station=station):
                with self.assertRaisesRegex(PlanValidationError, "operation"):
                    validate_plan(self.operation_plan(operation, actor, station))

    def test_initial_service_packing_continues_without_reopening(self):
        for finishes in (True, False):
            with self.subTest(finishes=finishes):
                data = self.operation_plan("pack")
                v = data["scenes"][0]["visual"]
                v.update(initialQueue=["b"], initialService=[{"actorId": "a", "stationId": "one"}])
                v["events"] = ([event("hold"), event("finish", ("a",), ("one",), 1),
                                event("hold", line=2, end_line=3)] if finishes else
                               [event("hold", end_line=3)])
                item = build(data)["scenes"][0]["visual"]["cues"][0]
                self.assertTrue(item["continued"])
                self.assertEqual(item["complete"], finishes)

    def test_waiting_parcels_stay_open_across_scenes_before_their_first_packing_cue(self):
        first = self.operation_plan("pack")
        first_visual = first["scenes"][0]["visual"]
        first_visual.update(initialQueue=["a", "b", "c"], initialService=[], events=[
            event("start", ("a",), ("one",)), event("hold", line=1),
            event("finish", ("a",), ("one",), 2), event("hold", line=3)])
        second = copy.deepcopy(first)
        second["scenes"][0]["visual"].update(initialQueue=["b", "c"], events=[
            event("start", ("b",), ("one",)), event("hold", line=1),
            event("finish", ("b",), ("one",), 2), event("hold", line=3)])
        shots = [build(data)["scenes"][0]["visual"] for data in (first, second)]
        self.assertEqual([{cue["entityId"] for cue in shot["cues"]} for shot in shots], [{"a"}, {"b"}])
        for shot in shots:
            self.assertEqual({entity["id"]: entity.get("packingState") for entity in shot["entities"]
                              if entity["kind"] == "box"}, {"a": "open", "b": "open", "c": "open"})
        second["scenes"][0]["visual"].update(initialQueue=["c"],
            initialService=[{"actorId": "b", "stationId": "one"}], events=[event("hold", end_line=3)])
        continuation = build(second)["scenes"][0]["visual"]
        self.assertEqual(next(entity for entity in continuation["entities"] if entity["id"] == "b")["packingState"], "prepared")
        generic = self.operation_plan("generic")
        self.assertTrue(all("packingState" not in entity for entity in build(generic)["scenes"][0]["visual"]["entities"]))

    def test_checked_in_samples_compile_actual_cues(self):
        fixtures = Path(__file__).resolve().parents[1] / "fixtures"
        packing = json.loads((fixtures / "scene-plan.process-packing.json").read_text())
        scene_data = build(packing)["scenes"][0]
        self.assertEqual([cue["kind"] for cue in scene_data["visual"]["cues"]], ["pack", "pack"])
        self.assertEqual(scene_data["processTrace"]["completed"], ["parcel-a", "parcel-b"])
        network = load_plan(fixtures / "scene-plan.motion-network.json")
        rendered = build_timeline(network, manifest(network))["scenes"][0]
        self.assertEqual({cue["kind"] for cue in rendered["visual"]["cues"]}, {"send", "receive", "compute"})


if __name__ == "__main__":
    unittest.main()
