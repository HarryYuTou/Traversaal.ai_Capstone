"""The planner's side of the timeline, stat, quote and map templates, tested without any API call."""

import copy
import json
import unittest

from capstone_script.planner import (
    UNSUPPORTED_KEYWORDS, coverage_problems, drop_unknown_icons, normalize_ids, output_schema, planner_prompt,
)
from capstone_script.review import apply_edits
from capstone_script.scene_plan import MAP_REGIONS, TEMPLATES, validate_plan
from test_visual_templates import all_scenes


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
        text = json.dumps(schema)
        for template in TEMPLATES:
            self.assertIn(f'"{template}"', text)
        for field in ("events", "stats", "quote", "author", "region", "areas", "places", "route",
                      "highlightEventId", "highlightStatIndex", "highlightQuote", "highlightId"):
            self.assertIn(f'"{field}"', text)

    def test_prompt_describes_the_new_templates_and_lists_the_regions(self):
        prompt = planner_prompt()
        for template in ("timeline:", "stat:", "quote:", "map:"):
            self.assertIn(template, prompt)
        self.assertIn(", ".join(MAP_REGIONS), prompt)
        self.assertNotIn("$", prompt.replace("\"$\"", ""))

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
