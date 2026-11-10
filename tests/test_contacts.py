"""Generic anchor contacts: reference graph, source ownership and measured acquisition timing."""

import copy
import hashlib
import json
import unittest

import jsonschema

from capstone_script.planner import _OutputPlan, from_model_output, normalize_ids, output_schema, planner_prompt
from capstone_script.scene_plan import PlanValidationError, dump_plan, json_schema, validate_plan
from capstone_script.timeline import TimelineError, build_timeline, compile_motion_actions
from test_custom_rig import custom_visual, part, rig
from test_motion import action, entity, manifest, plan_data, scene
from test_planner import as_model_output


def contact(**changes):
    return {"entityId": "bird", "partId": "wing", "x": 0, "y": 10,
            "targetId": "support", "targetPartId": "", "targetX": 0, "targetY": -20,
            "startLine": 0, "endLine": 1, "startOffset": 0, "endOffset": 1,
            "approach": 0, **changes}


def contact_visual():
    v = custom_visual()
    v["entities"].append(entity("support", "box", x=50, y=70))
    v["contacts"] = [contact()]
    return v


class ContactTests(unittest.TestCase):
    def assert_problem(self, v, expected):
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(plan_data(scene(visual=v)))
        self.assertTrue(any(expected in item for item in caught.exception.problems), caught.exception.problems)

    def test_contact_round_trip_through_real_planner_schema(self):
        data = plan_data(scene(visual=contact_visual()))
        output = as_model_output(data)
        _OutputPlan.model_validate(output)
        jsonschema.validate(output, output_schema(["motion"]))
        back, problems = from_model_output(output)
        self.assertEqual(problems, [])
        validated = validate_plan(back)
        self.assertEqual(json.loads(dump_plan(validated)), data)
        jsonschema.validate(data, json_schema())

    def test_omitted_contacts_preserve_legacy_plan_hash(self):
        dumped = dump_plan(validate_plan(plan_data()))
        self.assertNotIn('"contacts"', dumped)
        self.assertEqual(hashlib.sha256(dumped.encode()).hexdigest(),
                         "b6d54a24a75e9b2983a24ffa82c12bd56b33f263e134a2ea659177d69a90e21d")
        v = contact_visual()
        v.pop("contacts")
        plan = validate_plan(plan_data(scene(visual=v)))
        compiled = build_timeline(plan, manifest(plan))
        self.assertNotIn("contacts", compiled["scenes"][0]["visual"])

    def test_anchor_coordinates_approach_and_complexity_are_bounded(self):
        for field, value in (("x", 257), ("y", -257), ("targetX", float("nan")),
                             ("targetY", float("inf")), ("approach", -.01), ("approach", .51),
                             ("approach", True), ("startLine", -1)):
            with self.subTest(field=field, value=value):
                v = contact_visual()
                v["contacts"][0][field] = value
                self.assert_problem(v, field)
        v = contact_visual()
        v["contacts"] *= 25
        self.assert_problem(v, "at most 24")
        v = contact_visual()
        v["contacts"][0]["mode"] = "script"
        self.assert_problem(v, "mode")

    def test_entity_and_part_references_are_explicit(self):
        cases = [({"entityId": "missing"}, "entityId"), ({"targetId": "missing"}, "targetId"),
                 ({"partId": "missing"}, "partId"), ({"targetPartId": "arm"}, "targetPartId"),
                 ({"targetId": "bird", "targetPartId": "body"}, "cannot contact itself")]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                v = contact_visual()
                v["contacts"][0].update(changes)
                self.assert_problem(v, expected)
        v = contact_visual()
        v["contacts"][0]["partId"] = ""
        validate_plan(plan_data(scene(visual=v)))
        # Stock roots can also be a source; nonempty part references cannot.
        v["contacts"] = [contact(entityId="support", partId="", targetId="bird", targetPartId="body")]
        validate_plan(plan_data(scene(visual=v)))
        v["contacts"][0]["partId"] = "body"
        self.assert_problem(v, "custom rig")

    def test_custom_target_joint_and_acyclic_contact_chain_are_supported(self):
        v = contact_visual()
        v["entities"][1].update(kind="custom", rigId="support-rig")
        v["rigs"].append(rig(id="support-rig", parts=[part("surface")], clips=[]))
        v["contacts"][0]["targetPartId"] = "surface"
        v["entities"].append(entity("floor", "box"))
        v["contacts"].append(contact(entityId="support", partId="", targetId="floor"))
        validate_plan(plan_data(scene(visual=v)))

    def test_relationship_graph_rejects_cycles_even_at_different_times(self):
        v = contact_visual()
        v["contacts"] = [contact(endLine=0), contact(entityId="support", partId="", targetId="bird",
                                                   startLine=1, approach=.2)]
        self.assert_problem(v, "graph must be acyclic")
        v["entities"].append(entity("third", "box"))
        v["contacts"] = [contact(), contact(entityId="support", partId="", targetId="third"),
                         contact(entityId="third", partId="", targetId="bird")]
        self.assert_problem(v, "graph must be acyclic")

    def test_source_contacts_cannot_overlap_even_on_different_parts(self):
        v = contact_visual()
        v["contacts"].append(contact(partId="body"))
        self.assert_problem(v, "overlaps contact")
        v["contacts"] = [contact(endLine=0, endOffset=.5),
                         contact(startLine=0, startOffset=.5, approach=.2)]
        validate_plan(plan_data(scene(visual=v)))

    def test_source_travel_conflicts_but_target_travel_and_articulation_do_not(self):
        for kind in ("move", "follow-path", "orbit"):
            with self.subTest(kind=kind):
                v = contact_visual()
                v["actions"] = [action(kind, entityId="bird", pathId="route" if kind == "follow-path" else "")]
                v["paths"] = [{"id": "route", "points": [{"x": 10, "y": 10}, {"x": 50, "y": 50}],
                               "curved": False, "closed": False, "color": "muted"}]
                self.assert_problem(v, "source travel action")
        v = contact_visual()
        v["actions"] = [action(entityId="support"), action("rotate", entityId="bird", value=45),
                        action("scale", entityId="bird", value=1.5)]
        validate_plan(plan_data(scene(visual=v)))

    def test_anchor_order_and_zero_approach_rules_reject_teleporting_late_contacts(self):
        for changes, expected in (({"startLine": 1}, "later contacts need a positive approach"),
                                  ({"startOffset": .01}, "zero approach"),
                                  ({"endLine": 2}, "outside this scene"),
                                  ({"endLine": 0, "endOffset": 0}, "end anchor")):
            with self.subTest(changes=changes):
                v = contact_visual()
                v["contacts"][0].update(changes)
                self.assert_problem(v, expected)

    def test_nested_contact_ids_normalize_without_altering_anchors(self):
        v = contact_visual()
        v["entities"][0]["id"] = "Bird One"
        v["entities"][1]["id"] = "Support Object"
        v["rigs"][0]["parts"][1]["id"] = "Wing Joint"
        v["rigs"][0]["clips"][0]["tracks"][0]["partId"] = "Wing Joint"
        v["performances"][0]["entityId"] = "Bird One"
        v["contacts"][0].update(entityId="Bird One", partId="Wing Joint", targetId="Support Object")
        plan = validate_plan(normalize_ids(plan_data(scene(visual=v)), "contacts"))
        item = plan.scenes[0].visual.contacts[0]
        self.assertEqual((item.entity_id, item.part_id, item.target_id, item.target_part_id),
                         ("bird-one", "wing-joint", "support-object", ""))
        self.assertEqual((item.x, item.y, item.target_x, item.target_y), (0, 10, 0, -20))
        self.assertIn("FREE, UNCONSTRAINED", planner_prompt(["motion"]))
        self.assertNotIn("Contacts:", planner_prompt(["concept"]))

    def test_initial_contact_covers_silent_scene_lead_before_speech(self):
        plan = validate_plan(plan_data(scene(visual=contact_visual())))
        compiled = build_timeline(plan, manifest(plan))
        shot = compiled["scenes"][0]
        item = shot["visual"]["contacts"][0]
        self.assertEqual(item["from"], shot["from"])
        self.assertLess(item["from"], shot["lines"][0]["from"])
        self.assertEqual(item["approachFrames"], 0)
        self.assertEqual(item["from"] + item["durationInFrames"],
                         shot["lines"][-1]["from"] + shot["lines"][-1]["durationInFrames"])

    def test_later_acquisition_uses_measured_duration_and_keeps_authored_free_trajectory(self):
        v = contact_visual()
        v["performances"] = []
        v["contacts"] = [contact(startOffset=.25, endLine=0, approach=.2)]
        v["actions"] = [action(entityId="bird", startLine=1, x=80, y=40)]
        plan = validate_plan(plan_data(scene(visual=v)))
        shot = build_timeline(plan, manifest(plan))["scenes"][0]
        item = shot["visual"]["contacts"][0]
        first = shot["lines"][0]
        self.assertEqual(item["from"], first["from"] + round(.25 * first["durationInFrames"]))
        self.assertEqual(item["approachFrames"], round(item["durationInFrames"] * .2))
        travel = shot["visual"]["actions"][0]
        self.assertGreaterEqual(travel["from"], item["from"] + item["durationInFrames"])
        self.assertEqual((travel["x"], travel["y"]), (80, 40))
        self.assertEqual((v["actions"][0]["x"], v["actions"][0]["y"]), (80, 40))

    def test_rounded_acquisition_requires_two_frames_and_a_real_locked_interval(self):
        v = contact_visual()
        v["performances"] = []
        v["contacts"] = [contact(endLine=0, approach=.1)]
        lines = [{"from": 6, "durationInFrames": 10}]
        with self.assertRaisesRegex(TimelineError, "two acquisition frames"):
            compile_motion_actions(v, lines, 0, 30)
        v["contacts"][0]["approach"] = .2
        item = compile_motion_actions(v, lines, 0, 30)["contacts"][0]
        self.assertEqual((item["from"], item["durationInFrames"], item["approachFrames"]), (6, 10, 2))
        v["contacts"][0].update(startOffset=.01, endOffset=.02)
        with self.assertRaisesRegex(TimelineError, "at least one frame"):
            compile_motion_actions(v, lines, 0, 30)

    def test_compilation_rechecks_overlap_and_late_zero_approach(self):
        v = contact_visual()
        v["performances"] = []
        lines = [{"from": 6, "durationInFrames": 30}, {"from": 39, "durationInFrames": 60}]
        v["contacts"].append(copy.deepcopy(v["contacts"][0]))
        with self.assertRaisesRegex(TimelineError, "overlaps contact.*after frame compilation"):
            compile_motion_actions(v, lines, 0, 105)
        v["contacts"].pop()
        v["actions"] = [action(entityId="bird")]
        with self.assertRaisesRegex(TimelineError, "overlaps source travel.*after frame compilation"):
            compile_motion_actions(v, lines, 0, 105)
        v["actions"] = []
        v["contacts"][0]["startLine"] = 1
        with self.assertRaisesRegex(TimelineError, "zero is allowed only"):
            compile_motion_actions(v, lines, 0, 105)


if __name__ == "__main__":
    unittest.main()
