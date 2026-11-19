"""The timeline, stat, quote and map templates: structure, cross-references, schema and frame timeline."""

import copy
import hashlib
import json
import unittest

import jsonschema

from pathlib import Path

from capstone_script.scene_plan import (
    MAP_COUNTRIES, MAP_REGIONS, PlanValidationError, country_problems, dump_plan, json_schema, resolve_country,
    summarize, validate_plan,
)
from capstone_script.timeline import build_timeline


def timeline_scene():
    return {"id": "scene-01", "purpose": "Place the war's start and end in time.", "template": "timeline",
            "visual": {"title": "Six years of war",
                       "events": [{"id": "invasion", "date": "1939", "label": "Germany invades Poland",
                                   "icon": "flag"},
                                  {"id": "surrender", "date": "1945", "label": "Japan surrenders"}]},
            "narration": [{"id": "scene-01-line-01", "text": "The war began in Europe in 1939.",
                           "highlightEventId": "invasion"},
                          {"id": "scene-01-line-02", "text": "It ended in Asia six years later.",
                           "highlightEventId": "surrender"}]}


def stat_scene():
    return {"id": "scene-02", "purpose": "Show the war's scale.", "template": "stat",
            "visual": {"title": "The cost", "stats": [{"value": 70, "unit": "million", "label": "people killed",
                                                       "icon": "users"},
                                                      {"value": 2.5, "prefix": "$", "unit": "trillion",
                                                       "label": "spent by all sides"}],
                       "note": "Estimates vary by source."},
            "narration": [{"id": "scene-02-line-01", "text": "At least seventy million people died.",
                           "highlightStatIndex": 0},
                          {"id": "scene-02-line-02", "text": "The money spent is almost impossible to picture.",
                           "highlightStatIndex": 1}]}


def quote_scene():
    return {"id": "scene-03", "purpose": "Hear the moment in his words.", "template": "quote",
            "visual": {"title": "First words on the Moon",
                       "quote": "That's one small step for a man, one giant leap for mankind.",
                       "author": "Neil Armstrong", "context": "July 20, 1969"},
            "narration": [{"id": "scene-03-line-01", "text": "Armstrong stepped down and spoke.",
                           "highlightQuote": False},
                          {"id": "scene-03-line-02",
                           "text": "That's one small step for a man, one giant leap for mankind.",
                           "highlightQuote": True}]}


def map_scene():
    return {"id": "scene-04", "purpose": "Show where the trade route ran.", "template": "map",
            "visual": {"title": "The Silk Road", "region": "eurasia",
                       "areas": [{"id": "han", "label": "Han China", "countries": ["China"]},
                                 {"id": "rome", "label": "Rome", "countries": ["Italy"]}],
                       "places": [{"id": "changan", "label": "Chang'an", "lon": 108.9, "lat": 34.3},
                                  {"id": "samarkand", "label": "Samarkand", "lon": 66.97, "lat": 39.65}],
                       "route": True},
            "narration": [{"id": "scene-04-line-01", "text": "The road began in Chang'an.",
                           "highlightId": "changan"},
                          {"id": "scene-04-line-02", "text": "It crossed deserts to Samarkand.",
                           "highlightId": "samarkand"},
                          {"id": "scene-04-line-03", "text": "Silk reached Rome by sea and land.",
                           "highlightId": "rome"}]}


def plan_data(*scenes):
    return {"schemaVersion": "1", "projectId": "new-templates", "title": "Four new templates",
            "scenes": [copy.deepcopy(scene) for scene in scenes]}


def all_scenes():
    return plan_data(timeline_scene(), stat_scene(), quote_scene(), map_scene())


class VisualTemplateTests(unittest.TestCase):
    def problems(self, data):
        with self.assertRaises(PlanValidationError) as caught:
            validate_plan(data)
        return caught.exception.problems

    def assert_problem(self, data, expected):
        problems = self.problems(data)
        self.assertTrue(any(expected in problem for problem in problems), problems)

    def test_the_four_templates_validate_and_round_trip(self):
        data = all_scenes()
        plan = validate_plan(data)
        self.assertEqual(json.loads(dump_plan(plan)), data)
        self.assertEqual(summarize(plan)["templates"], ["map", "quote", "stat", "timeline"])

    def test_the_exported_schema_accepts_them(self):
        jsonschema.validate(all_scenes(), json_schema())

    def test_timeline_events_and_highlights(self):
        data = all_scenes()
        events = data["scenes"][0]["visual"]["events"]
        events[1]["id"] = "invasion"
        self.assert_problem(data, "scenes[0].visual.events[1].id: duplicate event id 'invasion'")
        data = all_scenes()
        data["scenes"][0]["narration"][0]["highlightEventId"] = "armistice"
        self.assert_problem(data, "scenes[0].narration[0].highlightEventId: 'armistice' is not an event")
        data = all_scenes()
        data["scenes"][0]["visual"]["events"] = events[:1]
        self.assert_problem(data, "scenes[0].visual.events")

    def test_stat_highlight_must_name_a_number(self):
        data = all_scenes()
        data["scenes"][1]["narration"][0]["highlightStatIndex"] = 2
        self.assert_problem(data, "scenes[1].narration[0].highlightStatIndex: 2 is out of range")
        data = all_scenes()
        data["scenes"][1]["visual"]["stats"][0]["value"] = "seventy"
        self.assert_problem(data, "scenes[1].visual.stats[0].value")

    def test_quote_needs_an_author(self):
        data = all_scenes()
        del data["scenes"][2]["visual"]["author"]
        self.assert_problem(data, "scenes[2].visual.author")

    def test_map_country_names_that_mean_one_country_are_corrected_with_a_note(self):
        data = all_scenes()
        data["scenes"][3]["visual"]["areas"][0]["countries"] = ["USA", "Phillipines", "the Netherlands", "China"]
        original = copy.deepcopy(data)
        notes = []
        plan = validate_plan(data, notes)
        self.assertEqual(plan.scenes[3].visual.areas[0].countries,
                         ["United States of America", "Philippines", "Netherlands", "China"])
        self.assertEqual(notes, [
            "scenes[3].visual.areas[0].countries[0]: 'USA' was read as 'United States of America'",
            "scenes[3].visual.areas[0].countries[1]: 'Phillipines' was read as 'Philippines'",
            "scenes[3].visual.areas[0].countries[2]: 'the Netherlands' was read as 'Netherlands'",
        ])
        self.assertEqual(data, original)  # The caller's data is left as it was.
        self.assertEqual(country_problems(plan), [])

    def test_resolving_country_names(self):
        cases = {"United States of America": "United States of America", "india": "India", "UK": "United Kingdom",
                 "Cote d'Ivoire": "Côte d'Ivoire", "Bosnia & Herzegovina": "Bosnia and Herz.",
                 "St Lucia": "Saint Lucia", "Saint Kitts and Nevis": "St. Kitts and Nevis", "Kazakstan": "Kazakhstan",
                 "Gemany": "Germany", "Soviet Union": None, "Korea": None, "Persia": None, "Han China": None}
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(resolve_country(name), expected)

    def test_a_country_that_matches_nothing_is_kept_but_reported_to_the_planner(self):
        data = all_scenes()
        data["scenes"][3]["visual"]["areas"][0]["countries"] = ["Soviet Union"]
        data["scenes"][3]["visual"]["areas"][1]["countries"] = ["Korea"]
        notes = []
        plan = validate_plan(data, notes)  # Saved plans with such names still load and render, unshaded.
        self.assertEqual(notes, [])
        problems = country_problems(plan)
        self.assertEqual(len(problems), 2, problems)
        self.assertTrue(problems[0].startswith(
            "scenes[3].visual.areas[0].countries[0]: 'Soviet Union' is not a country on the map; "), problems[0])
        self.assertIn("list a former state as the countries now on its land", problems[0])
        self.assertIn("did you mean 'North Korea' or 'South Korea'?", problems[1])

    def test_a_corrected_country_cannot_be_shaded_twice(self):
        data = all_scenes()
        data["scenes"][3]["visual"]["areas"][1]["countries"] = ["china"]
        self.assert_problem(data, "scenes[3].visual.areas[1].countries[0]: 'China' is already in another area")

    def test_the_map_country_list_and_the_handwritten_examples_agree(self):
        names = MAP_COUNTRIES["names"]
        self.assertEqual(len(names), len(set(names)))
        for alias, name in MAP_COUNTRIES["aliases"].items():
            with self.subTest(alias=alias):
                self.assertIn(name, names)
                self.assertNotIn(alias, names)
                self.assertEqual(resolve_country(alias), name)
        examples = Path(__file__).resolve().parents[1] / "examples"
        for path in sorted(examples.rglob("*.json")):
            plan = json.loads(path.read_text(encoding="utf-8"))
            for scene in plan.get("scenes", []) if isinstance(plan, dict) else []:
                for area in scene.get("visual", {}).get("areas", []) if scene.get("template") == "map" else []:
                    for country in area["countries"]:
                        with self.subTest(example=path.name, country=country):
                            self.assertIn(country, names)

    def test_map_checks_region_countries_ids_and_route(self):
        cases = [
            (lambda v: v.update(region="atlantis"), "scenes[3].visual.region: 'atlantis' is not a map region"),
            (lambda v: v["areas"][1]["countries"].append("China"), "'China' is already in another area"),
            (lambda v: v["places"][1].update(id="han"), "duplicate area or place id 'han'"),
            (lambda v: v.update(places=v["places"][:1]), "a route needs at least two places"),
            (lambda v: v["places"][0].update(lat=95), "scenes[3].visual.places[0].lat"),
        ]
        for change, expected in cases:
            with self.subTest(expected=expected):
                data = all_scenes()
                change(data["scenes"][3]["visual"])
                self.assert_problem(data, expected)
        data = all_scenes()
        data["scenes"][3]["visual"].update(areas=[], places=[], route=False)
        data["scenes"][3]["narration"] = data["scenes"][3]["narration"][:1]
        del data["scenes"][3]["narration"][0]["highlightId"]
        self.assert_problem(data, "a map needs at least one area or place")
        data = all_scenes()
        data["scenes"][3]["narration"][0]["highlightId"] = "athens"
        self.assert_problem(data, "highlightId: 'athens' is not a place or area on this map")

    def test_icons_on_events_and_numbers_come_from_the_shared_list(self):
        data = all_scenes()
        data["scenes"][0]["visual"]["events"][0]["icon"] = "not-an-icon"
        data["scenes"][1]["visual"]["stats"][0]["icon"] = "also-not-an-icon"
        problems = self.problems(data)
        self.assertIn("scenes[0].visual.events[0].icon: 'not-an-icon' is not an available icon; "
                      "see schemas/icons.json", problems)
        self.assertTrue(any(problem.startswith("scenes[1].visual.stats[0].icon") for problem in problems))

    def test_regions_have_usable_bounds(self):
        for name, bounds in MAP_REGIONS.items():
            with self.subTest(region=name):
                self.assertLess(bounds["west"], bounds["east"])
                self.assertLess(bounds["south"], bounds["north"])
                self.assertTrue(-180 <= bounds["west"] and bounds["east"] <= 180)
                self.assertTrue(-80 <= bounds["south"] and bounds["north"] <= 84)

    def test_the_frame_timeline_keeps_their_highlights(self):
        plan = validate_plan(all_scenes())
        lines = [line for scene in plan.scenes for line in scene.narration]
        manifest = {"status": "completed", "sampleRate": 24000,
                    "planSha256": hashlib.sha256(dump_plan(plan).encode("utf-8")).hexdigest(),
                    "blocks": [{"narrationId": line.id, "sampleRate": 24000, "channels": 1, "sampleCount": 24000,
                                "audioPath": f"audio/{line.id}.wav"} for line in lines]}
        timeline = build_timeline(plan, manifest)
        by_id = {line["id"]: line for scene in timeline["scenes"] for line in scene["lines"]}
        self.assertEqual(by_id["scene-01-line-02"]["highlightEventId"], "surrender")
        self.assertEqual(by_id["scene-02-line-01"]["highlightStatIndex"], 0)
        self.assertIs(by_id["scene-03-line-02"]["highlightQuote"], True)
        self.assertEqual(by_id["scene-04-line-03"]["highlightId"], "rome")
        self.assertEqual(timeline["scenes"][3]["visual"]["places"][0]["label"], "Chang'an")


if __name__ == "__main__":
    unittest.main()
