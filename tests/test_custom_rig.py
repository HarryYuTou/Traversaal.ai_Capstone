"""Planner-authored rigs: safe geometry, composable performances and actual audio anchors."""

import copy
import hashlib
import json
import unittest

import jsonschema

from capstone_script.planner import _OutputPlan, from_model_output, normalize_ids, output_schema, planner_prompt
from capstone_script.rig import path_problem, rig_envelope
from capstone_script.scene_plan import PlanValidationError, dump_plan, json_schema, validate_plan
from capstone_script.timeline import TimelineError, build_timeline, compile_motion_actions
from test_motion import entity, manifest, plan_data, scene, visual
from test_planner import as_model_output


def shape(**changes):
    return {"kind": "ellipse", "x": 0, "y": 0, "width": 24, "height": 16, "radius": 0,
            "path": "", "fill": "accent", "stroke": "ink", "strokeWidth": 1.5, **changes}


def part(identifier="body", **changes):
    return {"id": identifier, "parentId": "", "x": 0, "y": 0, "rotation": 0, "scaleX": 1,
            "scaleY": 1, "opacity": 1, "shapes": [shape()], **changes}


def track(identifier="wing", property="rotation", values=(0, -25, 0), **changes):
    return {"partId": identifier, "property": property, "keyframes": [
        {"at": index / (len(values) - 1), "value": value, "easing": "ease-in-out"}
        for index, value in enumerate(values)], **changes}


def rig(**changes):
    return {"id": "bird-rig", "parts": [part(), part("wing", parentId="body", x=-4)],
            "clips": [{"id": "wingbeat", "tracks": [track()]}], **changes}


def performance(**changes):
    return {"entityId": "bird", "clipId": "wingbeat", "startLine": 0, "endLine": 1,
            "startOffset": 0, "endOffset": 1, "repeat": 3, **changes}


def custom_visual(**changes):
    return visual(entities=[entity("bird", "custom", rigId="bird-rig")], paths=[], actions=[],
                  rigs=[rig()], performances=[performance()], **changes)


class CustomRigTests(unittest.TestCase):
    def assert_problem(self, v, expected):
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(plan_data(scene(visual=v)))
        self.assertTrue(any(expected in item for item in caught.exception.problems), caught.exception.problems)

    def test_custom_geometry_round_trips_through_real_planner_shape(self):
        data = plan_data(scene(visual=custom_visual()))
        output = as_model_output(data)
        _OutputPlan.model_validate(output)
        jsonschema.validate(output, output_schema(["motion"]))
        back, problems = from_model_output(output)
        self.assertEqual(problems, [])
        plan = validate_plan(back)
        self.assertEqual(json.loads(dump_plan(plan)), data)
        jsonschema.validate(data, json_schema())

    def test_stock_plan_dump_and_hash_are_unchanged(self):
        data = plan_data()
        # Captured with the pre-rig ScenePlan model on this exact stock fixture.
        self.assertEqual(hashlib.sha256(dump_plan(validate_plan(data)).encode()).hexdigest(),
                         "b6d54a24a75e9b2983a24ffa82c12bd56b33f263e134a2ea659177d69a90e21d")

    def test_shapes_have_explicit_semantics_and_reject_markup_and_external_sources(self):
        mutations = [
            ({"path": "<svg onload='alert(1)'>"}, "empty path"),
            ({"kind": "path", "width": 0, "height": 0, "path": "M 0 0 L 10 10", "href": "x"}, "href"),
            ({"fill": "url(https://example.com/a.svg)"}, "fill"),
            ({"fill": "#12345"}, "fill"), ({"width": 0}, "must be positive"),
            ({"radius": 2}, "ellipse uses"),
            ({"kind": "rect", "radius": 20}, "half the shorter"),
            ({"x": float("inf")}, "x"), ({"width": 513}, "width"),
        ]
        for changes, expected in mutations:
            with self.subTest(changes=changes):
                v = custom_visual()
                v["rigs"][0]["parts"][0]["shapes"][0].update(changes)
                self.assert_problem(v, expected)
        v = custom_visual()
        v["rigs"][0]["parts"][0]["shapes"] = [shape(kind="path", width=0, height=0,
            path="M -10 -10 L 10 -10 Q 20 0 10 10 C 5 15 -5 15 -10 10 Z", fill="#e97243")]
        validate_plan(plan_data(scene(visual=v)))

    def test_path_grammar_is_bounded_and_explicit(self):
        for invalid in ("", "M 0 0 l 1 1", "M 0 0 A 1 1 0 0 1 2 2", "M 0 0 L 999 2",
                        "M 0 0 L 1e999 0", "M 0 0 L 1", "M 0 0 1 1", "M0 0<script>",
                        "https://example.com", "M0 0" + " L0 0" * 128):
            with self.subTest(path=invalid):
                self.assertIsNotNone(path_problem(invalid))
        self.assertIsNone(path_problem("M -1.5,2 L 2e1,0 Q1 2 3 4 C0 1 2 3 4 5 Z"))

    def test_missing_references_cycles_duplicates_and_deep_hierarchies_fail(self):
        mutations = [
            (lambda v: v["entities"][0].pop("rigId"), "reference a rig"),
            (lambda v: v["entities"][0].update(kind="box"), "only custom"),
            (lambda v: v["rigs"][0]["parts"][0].update(parentId="wing"), "acyclic"),
            (lambda v: v["rigs"][0]["parts"][1].update(parentId="missing"), "not a part"),
            (lambda v: v["rigs"][0]["parts"][1].update(id="body"), "duplicate part"),
            (lambda v: v["rigs"].append(copy.deepcopy(v["rigs"][0])), "duplicate rig"),
            (lambda v: v["rigs"][0]["clips"].append(copy.deepcopy(v["rigs"][0]["clips"][0])), "duplicate clip"),
            (lambda v: v["performances"][0].update(entityId="missing"), "custom entity"),
            (lambda v: v["performances"][0].update(clipId="missing"), "not a clip"),
        ]
        for mutation, expected in mutations:
            with self.subTest(expected=expected):
                v = custom_visual()
                mutation(v)
                self.assert_problem(v, expected)
        v = custom_visual()
        v["rigs"][0]["parts"] = [part(f"p-{i}", parentId=f"p-{i-1}" if i else "") for i in range(9)]
        self.assert_problem(v, "eight parts")

    def test_keyframes_and_relative_values_cannot_snap_or_go_out_of_bounds(self):
        mutations = [
            (lambda t: t.update(partId="missing"), "not a part"),
            (lambda t: t["keyframes"][0].update(at=0.1), "start at 0"),
            (lambda t: t["keyframes"][-1].update(at=0.8), "end at 1"),
            (lambda t: t["keyframes"][1].update(at=0), "strictly increasing"),
            (lambda t: t["keyframes"][0].update(value=10), "begin at 0"),
            (lambda t: t.update(property="x", keyframes=track(values=(0, 300, 0))["keyframes"]), "-256"),
            (lambda t: t.update(property="opacity", keyframes=track(values=(0, 2, 0))["keyframes"]), "-1"),
            (lambda t: t.update(property="scaleX"), "begin at 1"),
            (lambda t: t.update(property="scaleY", keyframes=track(values=(1, 5, 1))["keyframes"]), "0.1"),
        ]
        for mutation, expected in mutations:
            with self.subTest(expected=expected):
                v = custom_visual()
                mutation(v["rigs"][0]["clips"][0]["tracks"][0])
                self.assert_problem(v, expected)
        v = custom_visual()
        v["rigs"][0]["clips"][0]["tracks"].append(track())
        self.assert_problem(v, "duplicate part/property")

    def test_repetitions_require_closed_cycles_and_finite_budget(self):
        for repeat in (0, 13, 1.5, True):
            v = custom_visual()
            v["performances"][0]["repeat"] = repeat
            self.assert_problem(v, "repeat")
        v = custom_visual()
        v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"][-1]["value"] = 20
        self.assert_problem(v, "matching endpoint")
        v["performances"][0]["repeat"] = 1
        validate_plan(plan_data(scene(visual=v)))

    def test_smooth_tracks_round_trip_with_schema_and_timeline(self):
        v = custom_visual()
        keys = v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"]
        for key in keys:
            key["easing"] = "smooth"
        data = plan_data(scene(visual=v))
        output = as_model_output(data)
        _OutputPlan.model_validate(output)
        jsonschema.validate(output, output_schema(["motion"]))
        back, problems = from_model_output(output)
        self.assertEqual(problems, [])
        plan = validate_plan(back)
        self.assertEqual(json.loads(dump_plan(plan)), data)
        rendered = build_timeline(plan, manifest(plan))["scenes"][0]["visual"]
        self.assertEqual(rendered["rigs"][0]["clips"][0]["tracks"][0]["keyframes"], keys)

    def test_smooth_interpolation_must_cover_the_whole_track(self):
        for smooth_index in (0, 1, 2):
            with self.subTest(smooth_index=smooth_index):
                v = custom_visual()
                v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"][smooth_index]["easing"] = "smooth"
                self.assert_problem(v, "smooth interpolation must be used on every key")
        v = custom_visual()
        keys = v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"]
        for key, curve in zip(keys, ("linear", "ease-out", "ease-in-out")):
            key["easing"] = curve
        validate_plan(plan_data(scene(visual=v)))

    def test_smooth_does_not_relax_repeat_endpoints_or_value_bounds(self):
        v = custom_visual()
        keys = v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"]
        for key in keys:
            key["easing"] = "smooth"
        keys[-1]["value"] = 15
        self.assert_problem(v, "matching endpoint")
        v["performances"][0]["repeat"] = 1
        validate_plan(plan_data(scene(visual=v)))
        keys[1]["value"] = 721
        self.assert_problem(v, "value")

    def test_simultaneous_clips_require_disjoint_joint_properties(self):
        v = custom_visual()
        v["rigs"][0]["clips"].append({"id": "squash", "tracks": [track("body", "scaleY", (1, .8, 1))]})
        v["performances"].append(performance(clipId="squash"))
        validate_plan(plan_data(scene(visual=v)))
        v["rigs"][0]["clips"][1]["tracks"] = [track()]
        self.assert_problem(v, "overlaps performance")

    def test_complete_motion_envelope_accounts_for_hierarchy_and_held_scale(self):
        v = custom_visual()
        v["rigs"][0]["parts"] = [part(shapes=[]), part("wing", parentId="body", x=20,
            shapes=[shape(width=20, height=10, strokeWidth=0)])]
        v["rigs"][0]["clips"] = [{"id": "grow", "tracks": [track("body", "scaleX", (1, 2))]}]
        v["performances"] = [performance(clipId="grow", endLine=0, repeat=1),
                             performance(clipId="grow", startLine=1, repeat=1)]
        plan = validate_plan(plan_data(scene(visual=v)))
        visual_model = plan.scenes[0].visual
        # Child rightmost point 30, scaled twice by 2; its height stays unchanged.
        self.assertEqual(rig_envelope(visual_model.rigs[0], visual_model.performances), (120, 5))
        v["rigs"][0]["parts"][0]["scaleX"] = 4
        v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"][-1]["value"] = 4
        self.assert_problem(v, "exceeds 800")

    def test_opacity_offsets_use_held_state_and_never_silently_saturate(self):
        v = custom_visual()
        v["rigs"][0]["clips"] = [{"id": "fade", "tracks": [track("body", "opacity", (0, -.6))]}]
        v["performances"] = [performance(clipId="fade", endLine=0, repeat=1),
                             performance(clipId="fade", startLine=1, repeat=1)]
        # Both individually bounded offsets are invalid when accumulated: 1 -.6 -.6 < 0.
        self.assert_problem(v, "accumulated opacity outside")
        v["performances"].pop()
        validate_plan(plan_data(scene(visual=v)))
        v["rigs"][0]["clips"][0]["tracks"][0]["keyframes"][-1]["value"] = 1
        self.assert_problem(v, "accumulated opacity outside")

    def test_shape_and_part_complexity_limits_apply_before_rendering(self):
        mutations = [
            (lambda v: v["rigs"][0]["parts"][0].update(id="constructor"), "reserved part"),
            (lambda v: v["rigs"][0]["parts"][0].update(shapes=[shape()] * 9), "shapes"),
            (lambda v: v["rigs"][0].update(parts=[part(f"part-{i}") for i in range(33)]), "parts"),
            (lambda v: v.update(rigs=[rig(id=f"rig-{i}") for i in range(7)]), "rigs"),
            (lambda v: v.update(performances=[performance()] * 49), "performances"),
        ]
        for mutation, expected in mutations:
            with self.subTest(expected=expected):
                v = custom_visual()
                mutation(v)
                self.assert_problem(v, expected)

    def test_identity_persists_across_scenes_but_base_pose_can_continue(self):
        first, second = scene(visual=custom_visual()), scene(visual=custom_visual(), id="next")
        for index, line in enumerate(second["narration"]):
            line["id"] = f"next-{index}"
        second["visual"]["rigs"][0]["parts"][1]["rotation"] = 20
        validate_plan(plan_data(first, second))
        second["visual"]["rigs"][0]["parts"][1]["shapes"][0]["width"] = 30
        with self.assertRaisesRegex(PlanValidationError, "preserve its ordered parts"):
            validate_plan(plan_data(first, second))
        second["visual"] = custom_visual()
        second["visual"]["rigs"][0]["id"] = "another-bird"
        second["visual"]["entities"][0]["rigId"] = "another-bird"
        with self.assertRaisesRegex(PlanValidationError, "preserve its kind and rigId"):
            validate_plan(plan_data(first, second))

    def test_planner_normalizes_every_nested_reference_without_changing_geometry(self):
        v = custom_visual()
        v["entities"][0].update(id="Bird 1", rigId="Bird Rig")
        v["rigs"][0]["id"] = "Bird Rig"
        v["rigs"][0]["parts"][0]["id"] = "Body Joint"
        v["rigs"][0]["parts"][1].update(id="Wing Joint", parentId="Body Joint")
        v["rigs"][0]["clips"][0].update(id="Wing Beat")
        v["rigs"][0]["clips"][0]["tracks"][0]["partId"] = "Wing Joint"
        v["performances"][0].update(entityId="Bird 1", clipId="Wing Beat")
        plan = validate_plan(normalize_ids(plan_data(scene(visual=v)), "bird"))
        result = plan.scenes[0].visual
        self.assertEqual(result.entities[0].rig_id, "bird-rig")
        self.assertEqual(result.rigs[0].parts[1].parent_id, "body-joint")
        self.assertEqual(result.rigs[0].clips[0].tracks[0].part_id, "wing-joint")
        self.assertEqual(result.performances[0].clip_id, "wing-beat")
        self.assertIn("create a custom rig", planner_prompt(["motion"]))
        self.assertNotIn("Custom objects:", planner_prompt(["concept"]))

    def test_audio_compilation_preserves_geometry_and_uses_measured_frames(self):
        plan = validate_plan(plan_data(scene(visual=custom_visual())))
        timeline = build_timeline(plan, manifest(plan))
        rendered = timeline["scenes"][0]
        perf = rendered["visual"]["performances"][0]
        lines = rendered["lines"]
        self.assertEqual(perf["from"], lines[0]["from"])
        self.assertEqual(perf["durationInFrames"], lines[-1]["from"] + lines[-1]["durationInFrames"] - perf["from"])
        self.assertEqual(rendered["visual"]["rigs"], custom_visual()["rigs"])

    def test_frame_compiler_rejects_collapses_and_same_track_overlap(self):
        lines = [{"from": 10, "durationInFrames": 10}]
        v = custom_visual()
        v["performances"] = [performance(endLine=0, startOffset=.01, endOffset=.02, repeat=1)]
        with self.assertRaisesRegex(TimelineError, "at least one frame"):
            compile_motion_actions(v, lines, 0, 30)
        v["performances"] = [performance(endLine=0, endOffset=.1, repeat=3)]
        with self.assertRaisesRegex(TimelineError, "four frames per repeated cycle"):
            compile_motion_actions(v, lines, 0, 30)
        v["performances"] = [performance(endLine=0, repeat=3)]
        with self.assertRaisesRegex(TimelineError, "four frames per repeated cycle"):
            compile_motion_actions(v, lines, 0, 30)
        compiled = compile_motion_actions(v, [{"from": 10, "durationInFrames": 12}], 0, 30)
        self.assertEqual(compiled["performances"][0]["durationInFrames"], 12)
        v["performances"] = [performance(endLine=0, repeat=1), performance(endLine=0, repeat=1)]
        with self.assertRaisesRegex(TimelineError, "after frame compilation"):
            compile_motion_actions(v, lines, 0, 30)


if __name__ == "__main__":
    unittest.main()
