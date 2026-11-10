"""Motion contract, offline planning and synchronization with measured narration audio."""

import copy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import jsonschema

from capstone_script.long_form import Outline, merge_chapters
from capstone_script.planner import (
    _OutputPlan, coverage_problems, from_model_output, normalize_ids, output_schema,
    planner_prompt, review_plan, write_plan_run,
)
from capstone_script.review import apply_edits
from capstone_script.scene_plan import (
    PlanValidationError, dump_plan, json_schema, scene_icons, validate_plan,
)
from capstone_script.timeline import (
    CHAPTER_FRAMES, GAP_FRAMES, LEAD_FRAMES, TITLE_FRAMES, TimelineError, build_timeline,
    compile_motion_actions,
)
from test_planner import FakeClient, VALID, as_model_output, response
from test_planner_templates import complexity


def entity(identifier="craft", kind="spacecraft", **changes):
    return {"id": identifier, "kind": kind, "x": 15.0, "y": 50.0, "size": 1.0,
            "rotation": 0.0, "opacity": 1.0, "value": 0.0, "color": "accent", "label": "", **changes}


def action(kind="move", **changes):
    return {"entityId": "craft", "kind": kind, "startLine": 0, "endLine": 1,
            "startOffset": 0.0, "endOffset": 1.0, "pathId": "", "x": 80.0, "y": 50.0,
            "value": 0.0, "easing": "ease-in-out", **changes}


def visual(**changes):
    return {"title": "Approaching the Moon", "entities": [entity(), entity("moon", "moon", x=80.0)],
            "paths": [{"id": "journey", "points": [{"x": 15.0, "y": 50.0}, {"x": 80.0, "y": 50.0}],
                       "curved": True, "closed": False, "color": "muted"}],
            "actions": [action()], **changes}


def scene(**changes):
    return {"id": "scene-01", "template": "motion", "purpose": "Show the craft approaching the Moon.",
            "visual": visual(), "narration": [
                {"id": "scene-01-line-01", "text": "The spacecraft leaves its starting position."},
                {"id": "scene-01-line-02", "text": "It moves toward the Moon."}], **changes}


def plan_data(*scenes):
    return {"schemaVersion": "1", "projectId": "motion-demo", "title": "Motion explanation",
            "scenes": list(scenes) if scenes else [scene()]}


def manifest(plan, counts=(48000, 96000)):
    lines = [line for item in plan.scenes for line in item.narration]
    return {"status": "completed", "sampleRate": 48000,
            "planSha256": hashlib.sha256(dump_plan(plan).encode()).hexdigest(),
            "blocks": [{"narrationId": line.id, "sampleRate": 48000, "channels": 1,
                        "sampleCount": counts[index % len(counts)], "audioPath": f"audio/{line.id}.wav"}
                       for index, line in enumerate(lines)]}


def all_motion_plan():
    data = copy.deepcopy(VALID)
    for item in data["scenes"]:
        item["template"] = "motion"
        item["visual"] = visual()
        item["narration"] = [{"id": line["id"], "text": line["text"]} for line in item["narration"]]
    return data


class MotionContractTests(unittest.TestCase):
    def assert_problem(self, data, expected):
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(data)
        self.assertTrue(any(expected in item for item in caught.exception.problems), caught.exception.problems)

    def test_motion_round_trips_without_inventing_highlights_or_frame_times(self):
        data = plan_data()
        plan = validate_plan(data)
        self.assertEqual(json.loads(dump_plan(plan)), data)
        jsonschema.validate(data, json_schema())
        self.assertEqual(scene_icons(plan.scenes[0]), [])
        self.assertEqual(coverage_problems(plan), [])
        self.assertEqual(set(plan.scenes[0].narration[0].model_dump()), {"id", "text"})
        data["scenes"][0]["narration"][0]["highlightId"] = "craft"
        self.assert_problem(data, "highlightId")

    def test_entity_path_and_action_ranges_are_strict_and_finite(self):
        mutations = [
            (lambda v: v["entities"][0].update(x=-1), "entities[0].x"),
            (lambda v: v["entities"][0].update(y=101), "entities[0].y"),
            (lambda v: v["entities"][0].update(size=0.24), "entities[0].size"),
            (lambda v: v["entities"][0].update(opacity=1.1), "entities[0].opacity"),
            (lambda v: v["entities"][0].update(value=-0.1), "entities[0].value"),
            (lambda v: v["entities"][0].update(rotation=float("inf")), "entities[0].rotation"),
            (lambda v: v["entities"][0].update(label="x" * 33), "entities[0].label"),
            (lambda v: v["entities"][0].update(kind="unknown"), "entities[0].kind"),
            (lambda v: v["paths"][0]["points"][0].update(x=float("nan")), "paths[0].points[0].x"),
            (lambda v: v["paths"][0].update(points=[{"x": 0, "y": 0}]), "paths[0].points"),
            (lambda v: v["paths"][0].update(points=[{"x": 0, "y": 0}] * 25), "paths[0].points"),
            (lambda v: v["actions"][0].update(startLine=True), "actions[0].startLine"),
            (lambda v: v["actions"][0].update(startLine=-1), "actions[0].startLine"),
            (lambda v: v["actions"][0].update(endOffset=1.01), "actions[0].endOffset"),
            (lambda v: v["actions"][0].update(value=float("nan")), "actions[0].value"),
            (lambda v: v["actions"][0].update(x=101), "actions[0].x"),
            (lambda v: v["actions"][0].update(kind="opacity", value=2), "opacity target"),
            (lambda v: v["actions"][0].update(kind="value", value=-1), "value target"),
            (lambda v: v["actions"][0].update(kind="scale", value=0), "scale target"),
            (lambda v: v["actions"][0].update(easing="spring"), "actions[0].easing"),
        ]
        for change, expected in mutations:
            with self.subTest(expected=expected):
                data = plan_data()
                change(data["scenes"][0]["visual"])
                self.assert_problem(data, expected)

    def test_caps_and_required_fields_are_enforced(self):
        for field, count, item in (("entities", 13, entity()),
                                   ("paths", 13, visual()["paths"][0]), ("actions", 49, action())):
            with self.subTest(field=field):
                data = plan_data()
                data["scenes"][0]["visual"][field] = [copy.deepcopy(item) for _ in range(count)]
                self.assert_problem(data, f"visual.{field}")
        data = plan_data()
        del data["scenes"][0]["visual"]["actions"][0]["pathId"]
        self.assert_problem(data, "actions[0].pathId")

    def test_duplicate_ids_references_and_unused_paths_are_rejected(self):
        mutations = [
            (lambda v: v["entities"][1].update(id="craft"), "entities[1].id: duplicate"),
            (lambda v: v["paths"].append(copy.deepcopy(v["paths"][0])), "paths[1].id: duplicate"),
            (lambda v: v["actions"][0].update(entityId="missing"), "not an entity"),
            (lambda v: v["actions"][0].update(kind="follow-path", pathId="missing"), "not a path"),
            (lambda v: v["actions"][0].update(pathId="journey"), 'use "" unless kind'),
            (lambda v: v["actions"][0].update(endLine=2), "outside this scene's 2 narration"),
            (lambda v: v["actions"][0].update(endLine=0, endOffset=0), "end anchor must be after"),
            (lambda v: v["actions"][0].update(startLine=1, endLine=0), "end anchor must be after"),
        ]
        for change, expected in mutations:
            with self.subTest(expected=expected):
                data = plan_data()
                change(data["scenes"][0]["visual"])
                self.assert_problem(data, expected)

    def test_position_actions_share_a_channel_but_other_properties_can_animate_together(self):
        data = plan_data()
        actions = data["scenes"][0]["visual"]["actions"]
        actions.extend([action("opacity", value=0.5), action("scale", value=1.5),
                        action("rotate", value=720), action("value", value=0.75)])
        validate_plan(data)
        for kind, kwargs in (("move", {}), ("follow-path", {"pathId": "journey"}),
                             ("orbit", {"value": -360})):
            with self.subTest(kind=kind):
                bad = copy.deepcopy(data)
                bad["scenes"][0]["visual"]["actions"].append(action(kind, **kwargs))
                self.assert_problem(bad, "channel 'position'")
        bad = copy.deepcopy(data)
        bad["scenes"][0]["visual"]["actions"].append(action("opacity", value=0))
        self.assert_problem(bad, "channel 'opacity'")

    def test_same_channel_may_meet_at_an_endpoint_or_belong_to_different_entities(self):
        actions = [action(endLine=0, endOffset=0.5),
                   action(startLine=0, startOffset=0.5),
                   action("orbit", entityId="moon", value=180)]
        validate_plan(plan_data(scene(visual=visual(actions=actions))))
        # These anchors span only the measured inter-line pause, which is still positive time.
        validate_plan(plan_data(scene(visual=visual(actions=[action(startOffset=1, endOffset=0)]))))

    def test_lander_can_leave_its_base_on_the_surface(self):
        data = plan_data(scene(visual=visual(entities=[entity("base", "lander-base"),
                                                       entity("craft", "lander-ascent")])))
        validate_plan(data)


class MotionPlannerTests(unittest.TestCase):
    def test_motion_survives_structured_output_with_required_motion_fields(self):
        data = plan_data()
        output = as_model_output(data)
        _OutputPlan.model_validate(output)
        back, problems = from_model_output(output)
        self.assertEqual(problems, [])
        self.assertEqual(json.loads(dump_plan(validate_plan(back))), data)
        schema = output_schema()
        # Ten visual parts, four optional motion arrays, nullable rig reference,
        # and the two nullable process station options fit the API grammar budget.
        self.assertEqual(complexity(schema), (17, 3))
        self.assertEqual(complexity(output_schema(["motion"])), (5, 1))
        for name in ("_OutputMotion", "MotionEntity", "MotionPoint", "MotionPath", "MotionAction", "MotionCue"):
            definition = schema["$defs"][name]
            optional = {"cues", "rigs", "performances", "contacts"} if name == "_OutputMotion" \
                else {"rigId"} if name == "MotionEntity" else set()
            self.assertEqual(set(definition["properties"]) - optional, set(definition["required"]))
        self.assertNotIn("anyOf", schema["$defs"]["_OutputVisual"]["properties"]["motion"])

    def test_motion_highlight_must_be_empty_and_is_reported_for_repair(self):
        output = as_model_output(plan_data())
        output["scenes"][0]["narration"][0]["highlight"] = "craft"
        _, problems = from_model_output(output)
        self.assertEqual(len(problems), 1)
        self.assertIn('highlight must be ""', problems[0])

    def test_visual_ids_and_references_change_together_while_line_indices_do_not(self):
        data = plan_data()
        v = data["scenes"][0]["visual"]
        v["entities"][0]["id"] = "Apollo Craft"
        v["paths"][0]["id"] = "Moon Approach"
        v["actions"][0].update(entityId="Apollo Craft", kind="follow-path", pathId="Moon Approach")
        fixed = normalize_ids(data, "motion-demo")
        motion = validate_plan(fixed).scenes[0].visual
        self.assertEqual(motion.actions[0].entity_id, motion.entities[0].id)
        self.assertEqual(motion.actions[0].path_id, motion.paths[0].id)
        self.assertEqual((motion.actions[0].start_line, motion.actions[0].end_line), (0, 1))
        self.assertEqual(motion.entities[0].id, "apollo-craft")

    def test_slug_collisions_are_rejected_instead_of_silently_retargeting_actions(self):
        data = plan_data()
        data["scenes"][0]["visual"]["entities"][0]["id"] = "same name"
        data["scenes"][0]["visual"]["entities"][1]["id"] = "same-name"
        with self.assertRaisesRegex(PlanValidationError, "duplicate"):
            validate_plan(normalize_ids(data, "motion-demo"))

    def test_an_all_motion_video_plans_without_template_variety_or_highlights(self):
        output = as_model_output(all_motion_plan())
        spec = {"projectId": "motion-demo", "targetDurationSec": 75,
                "topic": "How a web page reaches you", "audience": "Curious adults",
                "allowedTemplates": ["motion"]}
        plan, problems = review_plan(json.dumps(output), spec)
        self.assertEqual(problems, [])
        self.assertEqual({item.template for item in plan.scenes}, {"motion"})
        with tempfile.TemporaryDirectory() as temporary:
            client = FakeClient(response(output))
            saved = write_plan_run(Path(temporary) / "run", spec, client)
            self.assertEqual(len(client.calls), 1)
            self.assertEqual(saved.scenes[0].visual.actions[0].end_line, 1)
            request = client.calls[0]["messages"][0]["content"]
            self.assertIn("Use process or motion throughout", request)
            self.assertNotIn("at least two different templates", request)
        prompt = planner_prompt()
        self.assertIn("motion:", prompt)
        self.assertNotIn("Use at least two different templates", prompt)
        self.assertIn("zero-based", prompt)

    def test_action_errors_name_the_nested_model_output_location(self):
        output = as_model_output(all_motion_plan())
        output["scenes"][0]["visual"]["motion"]["actions"][0]["entityId"] = "missing"
        plan, problems = review_plan(json.dumps(output), {"projectId": "motion-demo", "targetDurationSec": 75})
        self.assertIsNone(plan)
        self.assertIn("scenes[0].visual.motion.actions[0].entityId: 'missing' is not an entity in this scene",
                      problems)

    def test_review_and_chapter_renumbering_preserve_local_action_anchors(self):
        plan = validate_plan(plan_data())
        edited = apply_edits(plan, [SimpleNamespace(line_id="scene-01-line-01",
                                                    text="The spacecraft begins its journey.")])
        self.assertEqual(plan.scenes[0].visual, edited.scenes[0].visual)
        outline = Outline.model_validate({"title": "Two chapters", "chapters": [
            {"title": f"Chapter {n}", "goal": "Explain the movement.", "keyPoints": ["A journey"],
             "targetSeconds": 60} for n in (1, 2)]})
        merged = merge_chapters({"projectId": "motion-demo"}, outline, [plan, edited])
        self.assertEqual(merged.scenes[1].narration[0].id, "scene-02-line-01")
        self.assertEqual(merged.scenes[0].visual, merged.scenes[1].visual)
        self.assertEqual(merged.scenes[1].visual.actions[0].start_line, 0)
        self.assertEqual(merged.chapters[1].scene_ids, ["scene-02"])


class MotionTimelineTests(unittest.TestCase):
    def test_frames_follow_actual_line_lengths_and_include_inter_line_pauses(self):
        original = plan_data(scene(visual=visual(actions=[action(startOffset=0.5, endOffset=0.25)])))
        plan = validate_plan(original)
        timeline = build_timeline(plan, manifest(plan))
        first = timeline["scenes"][0]
        compiled = first["visual"]["actions"][0]
        start = TITLE_FRAMES + LEAD_FRAMES + 15
        end = TITLE_FRAMES + LEAD_FRAMES + 30 + GAP_FRAMES + 15
        self.assertEqual((compiled["from"], compiled["durationInFrames"]), (start, end - start))
        self.assertEqual({key: value for key, value in compiled.items()
                          if key not in ("from", "durationInFrames")}, original["scenes"][0]["visual"]["actions"][0])
        self.assertEqual(json.loads(dump_plan(plan)), original)
        slower = build_timeline(plan, manifest(plan, (96000, 192000)))["scenes"][0]["visual"]["actions"][0]
        self.assertEqual(slower["from"], TITLE_FRAMES + LEAD_FRAMES + 30)
        self.assertGreater(slower["durationInFrames"], compiled["durationInFrames"])

    def test_chapter_cards_are_included_in_absolute_action_frames(self):
        data = plan_data()
        data["chapters"] = [{"id": "chapter-01", "title": "The journey", "sceneIds": ["scene-01"]}]
        plan = validate_plan(data)
        first = build_timeline(plan, manifest(plan))["scenes"][0]
        self.assertEqual(first["visual"]["actions"][0]["from"], TITLE_FRAMES + CHAPTER_FRAMES + LEAD_FRAMES)

    def test_sub_frame_actions_are_rejected_after_audio_is_measured(self):
        plan = validate_plan(plan_data(scene(visual=visual(actions=[action(endLine=0, endOffset=0.001)]))))
        with self.assertRaisesRegex(TimelineError, "at least one frame"):
            build_timeline(plan, manifest(plan))

    def test_frame_compilation_rechecks_overlaps_and_bounds(self):
        v = visual(actions=[action(endLine=0), action("orbit", endLine=0, value=90)])
        lines = [{"from": 10, "durationInFrames": 30}]
        with self.assertRaisesRegex(TimelineError, "overlaps"):
            compile_motion_actions(v, lines, 0, 50)
        with self.assertRaisesRegex(TimelineError, "inside its scene"):
            compile_motion_actions(visual(actions=[action(endLine=0)]), lines, 0, 20)

    def test_narration_must_have_real_positive_sample_counts(self):
        plan = validate_plan(plan_data())
        for bad in (0, -100, 48000.5, True):
            with self.subTest(sample_count=bad):
                audio = manifest(plan)
                audio["blocks"][0]["sampleCount"] = bad
                with self.assertRaisesRegex(TimelineError, "sample count"):
                    build_timeline(plan, audio)


if __name__ == "__main__":
    unittest.main()
