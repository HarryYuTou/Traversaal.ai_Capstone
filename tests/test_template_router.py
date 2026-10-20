"""Routing keeps API grammars bounded without restricting saved ScenePlans."""

import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from capstone_script.planner import (
    TEMPLATE_ROUTER_VERSION, PlannerError, make_spec, output_schema, review_plan,
    review_template_selection, write_plan_run,
)
from test_long_form import outline_output
from test_motion import all_motion_plan
from test_planner import TOPIC, FakeClient, as_model_output, model_output, response


class TemplateRouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / "run"
        self.spec, _ = make_spec(TOPIC, "Curious adults", 75)

    def saved(self, name):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def test_routes_then_plans_and_records_the_selected_vocabulary(self):
        client = FakeClient(response({"templates": ["concept", "flow"]}), response(model_output()))
        write_plan_run(self.out, self.spec, client)
        self.assertEqual(len(client.calls), 2)
        route, plan = client.calls
        self.assertEqual(route["max_tokens"], 1024)
        self.assertEqual(route["output_config"]["effort"], "low")
        self.assertIn("one to three", route["system"])
        self.assertIn("Allowed templates for this video: concept, flow.", plan["messages"][0]["content"])
        schema = plan["output_config"]["format"]["schema"]
        self.assertEqual(set(schema["$defs"]["_OutputVisual"]["properties"]), {"title", "concept", "flow"})
        self.assertNotIn("MotionAction", schema["$defs"])
        for name in ("project-spec.json", "llm-response.json"):
            record = self.saved(name)
            self.assertEqual(record["allowedTemplates"], ["concept", "flow"])
            self.assertEqual(record["templateRouterVersion"], TEMPLATE_ROUTER_VERSION)
            self.assertEqual(record["templateSelection"], "routed")
        self.assertEqual([item["step"] for item in self.saved("llm-response.json")["attempts"]],
                         ["template-selection", "plan"])
        self.assertEqual([item["effort"] for item in self.saved("llm-response.json")["attempts"]],
                         ["low", "high"])

    def test_motion_only_schema_requires_its_part_and_has_no_unreachable_definitions(self):
        schema = output_schema(["motion"])
        visual = schema["$defs"]["_OutputVisual"]
        self.assertEqual(visual["required"], ["title", "motion"])
        self.assertEqual(schema["$defs"]["_OutputScene"]["properties"]["template"]["enum"], ["motion"])
        output = as_model_output(all_motion_plan())
        jsonschema.validate(output, schema)
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(model_output(), schema)
        self.assertNotIn("_OutputConcept", schema["$defs"])
        self.assertNotIn("_OutputMap", schema["$defs"])
        references = set()

        def walk(node):
            if isinstance(node, dict):
                if "$ref" in node:
                    references.add(node["$ref"].removeprefix("#/$defs/"))
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        walk(schema)
        self.assertEqual(references, set(schema["$defs"]))

    def test_an_explicit_small_allowlist_skips_routing(self):
        self.spec["allowedTemplates"] = ["motion"]
        client = FakeClient(response(as_model_output(all_motion_plan())))
        write_plan_run(self.out, self.spec, client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(self.saved("project-spec.json")["templateSelection"], "explicit")
        self.assertEqual(self.saved("llm-response.json")["allowedTemplates"], ["motion"])

    def test_routing_repairs_invalid_selection_before_planning(self):
        client = FakeClient(response({"templates": ["concept", "flow", "map", "stat"]}),
                            response({"templates": ["concept", "flow"]}), response(model_output()))
        write_plan_run(self.out, self.spec, client)
        self.assertIn("choose one to 3 templates", client.calls[1]["messages"][2]["content"])
        self.assertEqual([item["step"] for item in self.saved("llm-response.json")["attempts"]],
                         ["template-selection", "template-selection", "plan"])

    def test_failed_routing_keeps_responses_and_never_requests_scenes(self):
        client = FakeClient(response({"templates": []}), response({"templates": []}))
        with self.assertRaisesRegex(PlannerError, "No usable visual template selection"):
            write_plan_run(self.out, self.spec, client)
        record = self.saved("llm-response.json")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["templateRouterVersion"], TEMPLATE_ROUTER_VERSION)
        self.assertEqual(len(record["attempts"]), 2)
        self.assertGreater(record["estimatedCostUsd"], 0)
        self.assertFalse((self.out / "scene-plan.json").exists())

    def test_selected_templates_are_enforced_by_local_review(self):
        spec = {**self.spec, "allowedTemplates": ["motion"]}
        plan, problems = review_plan(json.dumps(model_output()), spec)
        self.assertIsNone(plan)
        self.assertTrue(all("is not allowed for this video" in item for item in problems))
        self.assertEqual(len(problems), 5)

    def test_selector_cannot_expand_an_explicit_candidate_set(self):
        for output in ({"templates": ["motion"]}, {"templates": ["concept", "concept"]}):
            with self.subTest(output=output):
                chosen, problems = review_template_selection(json.dumps(output), ["concept", "flow"])
                self.assertIsNone(chosen)
                self.assertTrue(problems)

    def test_long_video_routes_once_and_reuses_subset_for_every_chapter(self):
        self.spec["targetDurationSec"] = 225
        client = FakeClient(response({"templates": ["concept", "flow"]}), response(outline_output()),
                            *(response(model_output()) for _ in range(3)))
        write_plan_run(self.out, self.spec, client)
        self.assertEqual(len(client.calls), 5)
        for chapter in client.calls[2:]:
            schema = chapter["output_config"]["format"]["schema"]
            self.assertEqual(set(schema["$defs"]["_OutputVisual"]["properties"]), {"title", "concept", "flow"})
            self.assertIn("Allowed templates for this video: concept, flow.",
                          chapter["messages"][0]["content"])

    def test_invalid_explicit_template_settings_fail_before_any_request(self):
        for templates in ([], ["motion", "motion"], ["unknown"], "motion"):
            with self.subTest(templates=templates), tempfile.TemporaryDirectory() as directory:
                client = FakeClient()
                with self.assertRaises(ValueError):
                    write_plan_run(Path(directory) / "run", {**self.spec, "allowedTemplates": templates}, client)
                self.assertEqual(client.calls, [])


if __name__ == "__main__":
    unittest.main()
