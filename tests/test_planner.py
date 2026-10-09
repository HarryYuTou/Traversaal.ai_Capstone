"""Planner tests with a scripted fake client: no network calls and no API key."""

from contextlib import redirect_stdout
import copy
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from capstone_script.__main__ import main
from capstone_script.planner import (
    MODEL, UNSUPPORTED_KEYWORDS, PlannerError, load_env_file, make_spec, normalize_ids,
    request_text, word_range, write_plan_run,
)

ROOT = Path(__file__).resolve().parents[1]
VALID = json.loads((ROOT / "fixtures" / "scene-plan.valid.json").read_text(encoding="utf-8"))
TOPIC = "What happens after you enter a website address?"


def model_output(change=None):
    """The valid fixture as a model might return it: placeholder ids and an unsafe node id."""
    data = copy.deepcopy(VALID)
    data["projectId"] = "placeholder"
    for s, scene in enumerate(data["scenes"], start=1):
        scene["id"] = f"scene-{s}"
        for n, line in enumerate(scene["narration"], start=1):
            line["id"] = f"s{s}-l{n}"
    data["scenes"][1]["visual"]["nodes"][1]["id"] = "DNS"
    data["scenes"][1]["narration"][1]["highlightNodeId"] = "DNS"
    if change:
        change(data)
    return data


def response(data=None, text=None, stop_reason="end_turn", stop_details=None):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""),
                 SimpleNamespace(type="text", text=json.dumps(data) if text is None else text)],
        model=MODEL, stop_reason=stop_reason, stop_details=stop_details, _request_id="req_test",
        usage=SimpleNamespace(input_tokens=1200, output_tokens=3400,
                              cache_read_input_tokens=0, cache_creation_input_tokens=0))


class FakeClient:
    def __init__(self, *responses):
        self.calls = []
        self.queue = list(responses)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        return self.queue.pop(0)


def broken_highlight(data):
    data["scenes"][2]["narration"][0]["highlightNodeId"] = "router"


class PlannerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="capstone-plan-test-")
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name) / "run"
        self.spec, _ = make_spec(TOPIC, "University students with no networking background", 75)

    def saved(self, name):
        return json.loads((self.out / name).read_text(encoding="utf-8"))

    def test_first_valid_response_is_saved_with_normalized_ids(self):
        client = FakeClient(response(model_output()))
        write_plan_run(self.out, self.spec, client)
        expected = copy.deepcopy(VALID)
        expected["projectId"] = "what-happens-after-you-enter-a-website-address"
        self.assertEqual(self.saved("scene-plan.json"), expected)
        record = self.saved("llm-response.json")
        self.assertEqual(record["status"], "completed")
        self.assertEqual([a["usage"]["output_tokens"] for a in record["attempts"]], [3400])
        self.assertEqual(record["attempts"][0]["requestId"], "req_test")
        self.assertEqual(self.saved("project-spec.json")["topic"], TOPIC)
        self.assertEqual(len(client.calls), 1)

    def test_request_sends_only_schema_keywords_that_structured_outputs_accept(self):
        client = FakeClient(response(model_output()))
        write_plan_run(self.out, self.spec, client)
        call = client.calls[0]
        self.assertEqual(call["model"], "claude-opus-5-5")
        self.assertEqual(call["output_config"]["effort"], "high")
        self.assertEqual(call["fallbacks"], "default")
        self.assertIn("server-side-fallback-2026-07-01", call["betas"])
        self.assertIn("about 185 words", call["messages"][0]["content"])
        schema = call["output_config"]["format"]["schema"]

        def walk(node, names=False):
            if isinstance(node, list):
                for item in node:
                    walk(item)
            elif isinstance(node, dict):
                if names:
                    for value in node.values():
                        walk(value)
                    return
                self.assertFalse(UNSUPPORTED_KEYWORDS & node.keys(), sorted(node))
                self.assertNotIn("oneOf", node)
                if node.get("type") == "object":
                    self.assertIs(node.get("additionalProperties"), False)
                for key, value in node.items():
                    walk(value, key in ("properties", "$defs"))

        walk(schema)
        self.assertIn("title", schema["properties"])  # A property name, not the keyword.

    def test_invalid_plan_gets_one_repair_request_listing_the_problems(self):
        client = FakeClient(response(model_output(broken_highlight)), response(model_output()))
        write_plan_run(self.out, self.spec, client)
        messages = client.calls[1]["messages"]
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertIn("'router' is not a node in this scene", messages[2]["content"])
        self.assertEqual(len(self.saved("llm-response.json")["attempts"]), 2)
        self.assertTrue((self.out / "scene-plan.json").exists())

    def test_short_script_is_sent_back_with_a_word_target(self):
        def keep_first_lines(data):
            for scene in data["scenes"]:
                scene["narration"] = scene["narration"][:1]
        client = FakeClient(response(model_output(keep_first_lines)), response(model_output()))
        write_plan_run(self.out, self.spec, client)
        repair = client.calls[1]["messages"][2]["content"]
        self.assertIn("the video needs 148 to 222 words. Add about", repair)

    def test_points_and_nodes_without_a_highlight_are_sent_back(self):
        def drop_highlights(data):
            data["scenes"][0]["narration"][4].pop("highlightPointIndex")
            data["scenes"][3]["narration"][2].pop("highlightNodeId")
        client = FakeClient(response(model_output(drop_highlights)), response(model_output()))
        write_plan_run(self.out, self.spec, client)
        repair = client.calls[1]["messages"][2]["content"]
        self.assertIn("scenes[0]: no narration line highlights point 2", repair)
        self.assertIn("scenes[3]: no narration line highlights node 'page'", repair)

    def test_second_failure_keeps_the_evidence_and_publishes_no_plan(self):
        client = FakeClient(response(model_output(broken_highlight)), response(model_output(broken_highlight)))
        with self.assertRaisesRegex(PlannerError, "router"):
            write_plan_run(self.out, self.spec, client)
        record = self.saved("llm-response.json")
        self.assertEqual(record["status"], "failed")
        self.assertEqual(len(record["attempts"]), 2)
        self.assertTrue(record["attempts"][1]["rawText"])
        self.assertFalse((self.out / "scene-plan.json").exists())

    def test_refusal_is_reported_without_a_repair_request(self):
        client = FakeClient(response(text="", stop_reason="refusal",
                                     stop_details=SimpleNamespace(category="cyber", explanation="")))
        with self.assertRaisesRegex(PlannerError, r"declined the request \(category: cyber\)"):
            write_plan_run(self.out, self.spec, client)
        self.assertEqual(len(client.calls), 1)

    def test_api_error_is_recorded_then_raised(self):
        client = FakeClient()
        client.beta.messages.create = Mock(side_effect=ConnectionError("network unreachable"))
        with self.assertRaises(ConnectionError):
            write_plan_run(self.out, self.spec, client)
        record = self.saved("llm-response.json")
        self.assertEqual(record["status"], "failed")
        self.assertIn("network unreachable", record["error"])

    def test_existing_output_is_refused_before_any_request(self):
        self.out.mkdir()
        client = FakeClient()
        with self.assertRaises(FileExistsError):
            write_plan_run(self.out, self.spec, client)
        self.assertEqual(client.calls, [])

    def test_reference_material_is_sent_and_hashed(self):
        path = Path(self.temporary.name) / "facts.md"
        path.write_text("- DNS turns names into IP addresses.\n", encoding="utf-8")
        spec, text = make_spec("DNS basics", "Students", 60, path)
        self.assertEqual(len(spec["referenceSha256"]), 64)
        self.assertIn("<reference>\n- DNS turns names into IP addresses.\n</reference>",
                      request_text(spec, text))

    def test_length_targets_and_input_limits(self):
        self.assertEqual(word_range(75), (148, 185, 222))
        for seconds in (29, 181):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                make_spec("Topic", "Audience", seconds)
        with self.assertRaises(ValueError):
            make_spec("   ", "Audience", 75)

    def test_normalized_node_ids_keep_their_highlights(self):
        scene = normalize_ids(model_output(), "demo")["scenes"][1]
        self.assertEqual(scene["visual"]["nodes"][1]["id"], "dns")
        self.assertEqual(scene["narration"][1]["highlightNodeId"], "dns")
        self.assertEqual(scene["narration"][1]["id"], "scene-02-line-02")

    def test_env_file_fills_only_missing_variables(self):
        env = Path(self.temporary.name) / ".env"
        env.write_text('# local secrets\nANTHROPIC_API_KEY="test-key"\nEXISTING=from-file\n', encoding="utf-8")
        with patch.dict(os.environ, {"EXISTING": "kept"}):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            load_env_file(env)
            self.assertEqual(os.environ["ANTHROPIC_API_KEY"], "test-key")
            self.assertEqual(os.environ["EXISTING"], "kept")


class PlanCommandTests(unittest.TestCase):
    def test_plan_command_writes_a_run(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary) / "run"
            stdout = io.StringIO()
            with patch("capstone_script.__main__._client", return_value=FakeClient(response(model_output()))), \
                    patch("capstone_script.__main__.load_env_file"), redirect_stdout(stdout):
                code = main(["plan", "--topic", TOPIC, "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("5 scenes | 18 lines", stdout.getvalue())
            self.assertTrue((out / "scene-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
