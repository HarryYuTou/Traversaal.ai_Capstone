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
    HIGHLIGHT_FIELDS, MODEL, UNSUPPORTED_KEYWORDS, PlannerError, coverage_problems, length_problems,
    load_env_file, make_spec, normalize_ids, request_text, word_range, write_plan_run,
)
from capstone_script.scene_plan import validate_plan
from test_scene_plan import with_new_templates

ROOT = Path(__file__).resolve().parents[1]
VALID = json.loads((ROOT / "fixtures" / "scene-plan.valid.json").read_text(encoding="utf-8"))
TOPIC = "What happens after you enter a website address?"


# Fields the output shape requires where a ScenePlan may leave them out.
PART_DEFAULTS = {"concept": {"points": [], "icon": ""}, "definition": {"example": "", "icon": ""},
                 "stat": {"note": ""}, "quote": {"context": ""}, "map": {"areas": [], "places": [], "route": False}}
ITEM_DEFAULTS = {"nodes": {"icon": ""}, "left": {"icon": ""}, "right": {"icon": ""}, "events": {"icon": ""},
                 "stats": {"prefix": "", "unit": "", "icon": ""}}


def as_model_output(plan):
    """ScenePlan data in the planner's output shape: one visual part per scene, one highlight per line."""
    data = copy.deepcopy(plan)
    for scene in data["scenes"]:
        template, visual = scene["template"], scene["visual"]
        part = {**PART_DEFAULTS.get(template, {}), **{key: value for key, value in visual.items() if key != "title"}}
        for key, defaults in ITEM_DEFAULTS.items():
            if template == "process":
                continue
            items = part.get(key)
            for item in items if isinstance(items, list) else [items] if isinstance(items, dict) else []:
                for name, value in defaults.items():
                    item.setdefault(name, value)
        scene["visual"] = {"title": visual["title"], template: part}
        for line in scene["narration"]:
            highlight = ""
            for field in HIGHLIGHT_FIELDS.values():
                if field in line:
                    value = line.pop(field)
                    highlight = "quote" if value is True else "" if value is False or value is None else str(value)
            line["highlight"] = highlight
    return data


def model_plan(change=None):
    """The valid fixture as a model might plan it: placeholder ids and an unsafe node id."""
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


def model_output(change=None):
    """model_plan as the model returns it, in the planner's output shape."""
    return as_model_output(model_plan(change))


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
        self.spec["allowedTemplates"] = ["concept", "flow"]

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
        self.assertIn("scenes[2].narration[0].highlight: 'router' is not a node in this scene", messages[2]["content"])
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

    def test_columns_and_examples_need_a_highlighting_line(self):
        data = with_new_templates(copy.deepcopy(VALID))
        data["scenes"][5]["narration"][1].pop("highlightSide")
        data["scenes"][6]["narration"][1]["highlightPart"] = "term"
        self.assertEqual(coverage_problems(validate_plan(data)), [
            "scenes[5]: no narration line highlights the right column; give each column a line whose "
            "highlight is \"left\" or \"right\"",
            "scenes[6]: no narration line highlights the example; give it a line whose highlight is \"example\"",
        ])

    def test_a_plan_can_use_one_template_when_it_fits_the_explanation(self):
        def concepts_only(data):
            data["scenes"] = [scene for scene in data["scenes"] if scene["template"] == "concept"]
        plan = validate_plan(normalize_ids(model_plan(concepts_only), "demo"))
        self.assertNotIn("scenes: use at least two different templates", length_problems(plan, self.spec))

    def test_request_prefers_process_animation_without_requiring_template_variety(self):
        text = request_text(self.spec)
        self.assertIn("Scenes: 2 to 8.", text)
        self.assertIn("Prefer process for arrivals, waiting and service", text)
        self.assertIn("Use process or motion throughout", text)
        self.assertIn("no minimum template variety", text)
        self.assertNotIn("at least two different templates", text)

    def test_unknown_icons_from_the_model_are_dropped_without_a_repair(self):
        def add_icons(data):
            data["scenes"][0]["visual"]["icon"] = "lightbulb"
            data["scenes"][1]["visual"]["nodes"][0]["icon"] = "web-browser"
        client = FakeClient(response(model_output(add_icons)))
        plan = write_plan_run(self.out, self.spec, client)
        self.assertEqual(plan.scenes[0].visual.icon, "lightbulb")
        self.assertIsNone(plan.scenes[1].visual.nodes[0].icon)
        self.assertIn("chosen from this list: activity, ", client.calls[0]["system"])
        self.assertNotIn("$icons", client.calls[0]["system"])

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
        self.assertEqual(make_spec("Topic", "Audience", 180)[0]["planMode"], "single")
        self.assertEqual(make_spec("Topic", "Audience", 600)[0]["planMode"], "chapters")
        for seconds in (29, 601):
            with self.subTest(seconds=seconds), self.assertRaises(ValueError):
                make_spec("Topic", "Audience", seconds)
        with self.assertRaises(ValueError):
            make_spec("   ", "Audience", 75)

    def test_normalized_node_ids_keep_their_highlights(self):
        scene = normalize_ids(model_plan(), "demo")["scenes"][1]
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
            with patch("capstone_script.__main__._client", return_value=FakeClient(
                    response({"templates": ["concept", "flow"]}), response(model_output()))), \
                    patch("capstone_script.__main__.load_env_file"), redirect_stdout(stdout):
                code = main(["plan", "--topic", TOPIC, "--out", str(out)])
            self.assertEqual(code, 0)
            self.assertIn("5 scenes | 18 lines", stdout.getvalue())
            self.assertTrue((out / "scene-plan.json").exists())


if __name__ == "__main__":
    unittest.main()
