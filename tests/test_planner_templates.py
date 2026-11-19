"""The planner's side of the timeline, stat, quote and map templates, tested without any API call."""

import copy
import json
from pathlib import Path
import unittest

from capstone_script.long_form import Outline
from capstone_script.planner import (
    UNSUPPORTED_KEYWORDS, _OutputPlan, coverage_problems, drop_unknown_icons, from_model_output, normalize_ids,
    output_schema, planner_prompt, request_plan, review_plan, structured_schema,
)
from capstone_script.review import Review, apply_edits
from capstone_script.scene_plan import MAP_REGIONS, TEMPLATES, dump_plan, validate_plan
from test_planner import VALID, FakeClient, as_model_output, response
from test_scene_plan import with_new_templates
from test_visual_templates import all_scenes

# Structured outputs accept at most this many optional and union-typed (anyOf) parameters per
# request; see "Schema complexity limits" in Claude's structured-outputs documentation.
MAX_OPTIONAL, MAX_UNION = 24, 16


def complexity(schema):
    """(optional, union-typed) parameter counts across a schema and its definitions."""
    optional = union = 0
    for node in [schema, *schema.get("$defs", {}).values()]:
        required = set(node.get("required", ()))
        for name, prop in (node.get("properties") or {}).items():
            optional += name not in required
            union += "anyOf" in prop or isinstance(prop.get("type"), list)
    return optional, union


def keywords(node):
    """Every JSON Schema keyword used anywhere in a schema (property names excluded)."""
    found = set()
    if isinstance(node, dict):
        for key, value in node.items():
            found.add(key)
            found |= set().union(*(keywords(item) for item in value.values())) if key in ("properties", "$defs") \
                else keywords(value)
    elif isinstance(node, list):
        for item in node:
            found |= keywords(item)
    return found


class PlannerTemplateTests(unittest.TestCase):
    def test_output_shape_offers_every_template_and_its_fields(self):
        schema = output_schema()
        self.assertFalse(keywords(schema) & set(UNSUPPORTED_KEYWORDS))
        self.assertEqual(set(schema["$defs"]["_OutputVisual"]["properties"]), {"title", *TEMPLATES})
        self.assertEqual(set(schema["$defs"]["_OutputLine"]["properties"]), {"id", "text", "highlight"})
        text = json.dumps(schema)
        for field in ("events", "stats", "quote", "author", "region", "areas", "places", "route"):
            self.assertIn(f'"{field}"', text)

    def test_every_request_schema_stays_within_the_structured_output_limits(self):
        schemas = {"plan": output_schema(), "outline": structured_schema(Outline.model_json_schema(by_alias=True)),
                   "review": structured_schema(Review.model_json_schema(by_alias=True))}
        for name, schema in schemas.items():
            with self.subTest(schema=name):
                optional, union = complexity(schema)
                self.assertLessEqual(optional, MAX_OPTIONAL)
                self.assertLessEqual(union, MAX_UNION)

    def test_every_template_survives_the_output_shape(self):
        for plan in (with_new_templates(copy.deepcopy(VALID)), all_scenes()):
            output = as_model_output(plan)
            _OutputPlan.model_validate(output)  # What structured outputs would let the model write.
            back, problems = from_model_output(output)
            self.assertEqual(problems, [])
            for line in (line for scene in plan["scenes"] for line in scene["narration"]):
                if line.get("highlightQuote") is False:
                    del line["highlightQuote"]  # Means the same as leaving it out, which the shape does.
            self.assertEqual(dump_plan(validate_plan(back)), dump_plan(validate_plan(plan)))

    def test_a_highlight_the_template_cannot_use_is_sent_back(self):
        output = as_model_output(all_scenes())
        output["scenes"][1]["narration"][0]["highlight"] = "first"
        output["scenes"][2]["narration"][0]["highlight"] = "yes"
        self.assertEqual(from_model_output(output)[1], [
            "scenes[1].narration[0].highlight: 'first' is not a number position; use \"0\", \"1\" or \"2\", "
            "or \"\" for none",
            "scenes[2].narration[0].highlight: 'yes' cannot be highlighted in a quote scene; use \"quote\" or \"\"",
        ])

    def test_problems_name_the_fields_the_model_wrote(self):
        output = as_model_output(all_scenes())
        output["scenes"][0]["visual"]["timeline"]["events"][0]["label"] = "x" * 60
        output["scenes"][3]["visual"]["stat"] = output["scenes"][3]["visual"].pop("map")
        plan, problems = review_plan(json.dumps(output), {"projectId": "new-templates", "targetDurationSec": 120})
        self.assertIsNone(plan)
        self.assertEqual(problems, [
            "scenes[3].visual.map: a map scene needs this part; fill it, or set the template to the one whose "
            "part you filled",
            "scenes[0].visual.timeline.events[0].label: String should have at most 48 characters",
        ])

    def test_prompt_describes_the_new_templates_and_lists_the_regions(self):
        prompt = planner_prompt()
        for template in ("timeline:", "stat:", "quote:", "map:"):
            self.assertIn(template, prompt)
        self.assertIn(", ".join(MAP_REGIONS), prompt)
        self.assertNotIn("$", prompt.replace("\"$\"", ""))

    @staticmethod
    def map_review():
        """A plan the review accepts as it is: every place and area highlighted, at a length that fits."""
        data = all_scenes()
        del data["scenes"][2]  # Three scenes fit a 20-second video; the map is the last of them.
        data["scenes"][2]["narration"].append({"id": "scene-04-line-04", "text": "Han China guarded the start.",
                                               "highlightId": "han"})
        return {"projectId": "new-templates", "targetDurationSec": 20}, data

    def test_country_names_are_corrected_without_a_repair_request(self):
        spec, data = self.map_review()
        self.assertEqual(review_plan(json.dumps(as_model_output(data)), spec)[1], [])
        output = as_model_output(data)
        output["scenes"][2]["visual"]["map"]["areas"][0]["countries"] = ["Peoples Republic of Chna"]
        self.assertIsNone(review_plan(json.dumps(output), spec)[0])  # Too far from any name: sent back.

        output["scenes"][2]["visual"]["map"]["areas"][0]["countries"] = ["Chna"]
        notes, messages = [], []
        plan, problems = review_plan(json.dumps(output), spec, notes=notes)
        self.assertEqual(problems, [])
        self.assertEqual(plan.scenes[2].visual.areas[0].countries, ["China"])
        self.assertEqual(notes, ["scenes[2].visual.areas[0].countries[0]: 'Chna' was read as 'China'"])

        client, attempts = FakeClient(response(output)), []
        plan = request_plan(client, "system", "request", {}, spec, "scene plan", attempts, "plan", messages.append)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(attempts[-1]["problems"], [])
        self.assertEqual(attempts[-1]["notes"], notes)
        self.assertIn("Corrected a map country name: " + notes[0], messages)

    def test_a_country_that_matches_nothing_is_sent_back_once(self):
        spec, data = self.map_review()
        unknown = as_model_output(data)
        unknown["scenes"][2]["visual"]["map"]["areas"][1]["countries"] = ["Soviet Union"]
        client, attempts = FakeClient(response(unknown), response(as_model_output(data))), []
        plan = request_plan(client, "system", "request", {}, spec, "scene plan", attempts, "plan")
        self.assertEqual(plan.scenes[2].visual.areas[1].countries, ["Italy"])
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(any("'Soviet Union' is not a country on the map" in problem
                            for problem in attempts[0]["problems"]), attempts[0]["problems"])
        self.assertNotIn("notes", attempts[-1])

    def test_prompts_send_geographic_relations_to_the_map(self):
        prompt = planner_prompt()
        self.assertIn("show it with a map scene", prompt)
        self.assertIn("Do not stand for those places with location markers or icons placed in a row", prompt)
        self.assertIn('"Dem. Rep. Congo"', prompt)
        self.assertNotIn("show it with a map scene", planner_prompt(["motion", "concept"]))
        router = (Path(__file__).resolve().parents[1] / "prompts" / "template-router.txt").read_text(encoding="utf-8")
        self.assertIn("rather than showing those places as markers in a row", router)

    def test_motion_prompt_explains_rendered_meaning_and_visible_object_lifecycles(self):
        prompt = planner_prompt()
        self.assertIn("Labels do not change the drawing", prompt)
        self.assertIn("A gauge renders value as a percentage, including a visible number", prompt)
        self.assertIn("derive every initial and target value from the stated fraction", prompt)
        self.assertIn("then fade to opacity zero after arrival there", prompt)
        self.assertIn("Do not cut away merely because the next sentence begins", prompt)
        self.assertIn("the renderer does not carry state between scenes automatically", prompt)

    def test_every_event_number_quote_place_and_area_needs_a_line(self):
        def covered():
            data = all_scenes()
            data["scenes"][3]["narration"].append({"id": "scene-04-line-04", "text": "Han China guarded the start.",
                                                   "highlightId": "han"})
            return data

        self.assertEqual(coverage_problems(validate_plan(covered())), [])
        changes = {
            "event 'surrender'": lambda d: d["scenes"][0]["narration"][1].pop("highlightEventId"),
            "number 1": lambda d: d["scenes"][1]["narration"][1].pop("highlightStatIndex"),
            "reads the quotation": lambda d: d["scenes"][2]["narration"][1].update(highlightQuote=False),
            "'samarkand'": lambda d: d["scenes"][3]["narration"][1].pop("highlightId"),
        }
        for expected, change in changes.items():
            with self.subTest(expected=expected):
                data = covered()
                change(data)
                problems = coverage_problems(validate_plan(data))
                self.assertEqual(len(problems), 1, problems)
                self.assertIn(expected, problems[0])

    def test_ids_from_the_model_are_made_path_safe_with_their_highlights(self):
        data = all_scenes()
        data["scenes"][0]["visual"]["events"][0]["id"] = "Invasion of Poland"
        data["scenes"][0]["narration"][0]["highlightEventId"] = "Invasion of Poland"
        data["scenes"][3]["visual"]["places"][0]["id"] = "Chang'an"
        data["scenes"][3]["narration"][0]["highlightId"] = "Chang'an"
        fixed = normalize_ids(data, "new-templates")
        event_id = fixed["scenes"][0]["visual"]["events"][0]["id"]
        place_id = fixed["scenes"][3]["visual"]["places"][0]["id"]
        self.assertEqual(fixed["scenes"][0]["narration"][0]["highlightEventId"], event_id)
        self.assertEqual(fixed["scenes"][3]["narration"][0]["highlightId"], place_id)
        validate_plan(fixed)

    def test_unknown_icons_on_events_and_numbers_are_dropped(self):
        data = all_scenes()
        data["scenes"][0]["visual"]["events"][1]["icon"] = "made-up"
        data["scenes"][1]["visual"]["stats"][1]["icon"] = "made-up"
        cleaned = drop_unknown_icons(copy.deepcopy(data))
        self.assertNotIn("icon", cleaned["scenes"][0]["visual"]["events"][1])
        self.assertNotIn("icon", cleaned["scenes"][1]["visual"]["stats"][1])
        self.assertEqual(cleaned["scenes"][0]["visual"]["events"][0]["icon"], "flag")

    def test_review_never_rewrites_a_quotation(self):
        plan = validate_plan(all_scenes())
        edits = [type("Edit", (), {"line_id": "scene-03-line-02", "text": "Something he never said."})(),
                 type("Edit", (), {"line_id": "scene-03-line-01", "text": "Armstrong climbed down and spoke."})()]
        lines = {line.id: line.text for scene in apply_edits(plan, edits).scenes for line in scene.narration}
        self.assertEqual(lines["scene-03-line-02"], "That's one small step for a man, one giant leap for mankind.")
        self.assertEqual(lines["scene-03-line-01"], "Armstrong climbed down and spoke.")


if __name__ == "__main__":
    unittest.main()
