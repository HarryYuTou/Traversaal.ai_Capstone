"""A grammar-size fallback must not bypass custom geometry and motion validation."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from capstone_script.planner import PlannerError, from_model_output, output_schema, request_json
from capstone_script.scene_plan import PlanValidationError, validate_plan
from test_planner import as_model_output, response


class ServiceError(RuntimeError):
    def __init__(self, message, status_code=400):
        super().__init__(message)
        self.status_code = status_code
        self.request_id = "request-grammar-limit"


class PlannerGrammarFallbackTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "fixtures/scene-plan.custom-rigs.json"
        self.output = as_model_output(json.loads(path.read_text()))

    def request(self, responses, attempts):
        create = Mock(side_effect=responses)
        client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))

        def review(text):
            data, problems = from_model_output(json.loads(text))
            try:
                plan = validate_plan(data)
            except PlanValidationError as exc:
                return None, problems + exc.problems
            return (None if problems else plan), problems

        result = request_json(client, "Write a scene plan.", "Demonstrate new articulated objects.",
                              output_schema(["motion"]), review, "scene plan", attempts, "plan")
        return result, create

    def test_grammar_rejection_retries_once_without_disabling_local_validation(self):
        attempts = []
        plan, create = self.request([ServiceError("The compiled grammar is too large"),
                                     response(self.output)], attempts)
        self.assertEqual(len(plan.scenes), 3)
        self.assertEqual(create.call_count, 2)
        self.assertIn("format", create.call_args_list[0].kwargs["output_config"])
        self.assertNotIn("format", create.call_args_list[1].kwargs["output_config"])
        self.assertEqual(create.call_args_list[1].kwargs["output_config"]["effort"], "medium")
        self.assertIn('"CustomRig"', create.call_args_list[1].kwargs["system"])
        self.assertEqual([item["outputMode"] for item in attempts], ["json-schema", "validated-json"])
        self.assertEqual(attempts[0]["stopReason"], "grammar_limit")

    def test_invalid_geometry_still_uses_the_bounded_repair(self):
        invalid = copy.deepcopy(self.output)
        invalid["scenes"][0]["visual"]["motion"]["rigs"][0]["parts"][0]["parentId"] = "missing-joint"
        attempts = []
        _, create = self.request([ServiceError("The compiled grammar is too large"),
                                  response(invalid), response(self.output)], attempts)
        self.assertEqual(create.call_count, 3)
        self.assertTrue(attempts[1]["problems"])
        self.assertIn("missing-joint", " ".join(attempts[1]["problems"]))
        self.assertNotIn("format", create.call_args_list[2].kwargs["output_config"])
        with self.assertRaises(PlannerError):
            self.request([ServiceError("The compiled grammar is too large"),
                          response(invalid), response(invalid)], [])

    def test_other_service_errors_never_activate_fallback(self):
        for error in [ServiceError("Invalid authentication", 401),
                      ServiceError("The compiled grammar is too large", 500),
                      ServiceError("Another invalid request"), RuntimeError("Connection error")]:
            with self.subTest(error=error), self.assertRaises(type(error)):
                self.request([error], [])


if __name__ == "__main__":
    unittest.main()
