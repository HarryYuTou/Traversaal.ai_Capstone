"""Topic -> ScenePlan with one Claude API call, plus at most one repair call.

The response must pass the same validation as a hand-written plan. If it does
not, a single repair request lists every problem. Raw responses and call
metadata are saved for every run, including failed ones; the API key never is.
"""

import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from string import Template
from time import perf_counter

from .scene_plan import (
    TEMPLATES, WORDS_PER_SECOND, PlanValidationError, dump_plan, json_schema, summarize, validate_plan,
)

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 16000
PROMPT_VERSION = "scene-planner-v1"
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
# The timeline adds short pauses around lines, so speech fills about 95% of the video.
SPEECH_SHARE = 0.95
# A plan holds at most 12 scenes for now, which limits videos to about three minutes.
MIN_SECONDS, MAX_SECONDS = 30, 180
# Structured outputs reject these JSON Schema keywords; validate_plan still enforces them.
UNSUPPORTED_KEYWORDS = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
                        "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "pattern",
                        "default", "title", "discriminator", "$schema", "$id"}
FATAL_STOPS = {"refusal": "the model declined the request",
               "max_tokens": "the response hit the output limit before the plan was complete"}


class PlannerError(RuntimeError):
    def __init__(self, message, attempts=()):
        super().__init__(message)
        self.attempts = list(attempts)


def slug(text: str, limit: int = 48) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return value[:limit].rstrip("-") or "item"


def word_range(seconds: int):
    """Return (low, target, high) narration words for a video of this length."""
    words = seconds * SPEECH_SHARE * WORDS_PER_SECOND
    return round(words * 0.8), round(words), round(words * 1.2)


def scene_range(seconds: int):
    low = 4 if seconds >= 60 else 2
    return low, min(12, max(low + 1, round(seconds / 10)))


def make_spec(topic: str, audience: str, seconds: int, reference: Path | None = None):
    """Return the run's ProjectSpec and the reference text, if any."""
    topic, audience = topic.strip(), audience.strip()
    if not topic or not audience:
        raise ValueError("Topic and audience must not be empty.")
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise ValueError(f"Duration must be between {MIN_SECONDS} and {MAX_SECONDS} seconds for now.")
    spec = {"schemaVersion": "1", "projectId": slug(topic), "topic": topic, "audience": audience,
            "language": "en", "targetDurationSec": seconds,
            "durationRangeSec": [round(seconds * 0.8), round(seconds * 1.2)],
            "allowedTemplates": list(TEMPLATES)}
    reference_text = None
    if reference is not None:
        reference_text = Path(reference).read_text(encoding="utf-8-sig")
        spec["referenceFile"] = Path(reference).as_posix()
        spec["referenceSha256"] = hashlib.sha256(reference_text.encode("utf-8")).hexdigest()
    return spec, reference_text


def request_text(spec: dict, reference_text: str | None = None) -> str:
    seconds = spec["targetDurationSec"]
    _, target, _ = word_range(seconds)
    min_scenes, max_scenes = scene_range(seconds)
    text = (f"Write the scene plan for this explainer video.\n\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n"
            f"Length: about {seconds} seconds, so about {target} words of narration in total "
            f"(stay between {round(target * 0.9)} and {round(target * 1.1)} words).\n"
            f"Scenes: {min_scenes} to {max_scenes}, using both templates at least once.")
    if reference_text and reference_text.strip():
        text += f"\n\nReference material:\n<reference>\n{reference_text.strip()}\n</reference>"
    return text


def output_schema() -> dict:
    """The ScenePlan schema reduced to the keywords structured outputs accept."""
    def clean(node, keys_are_names=False):
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        if keys_are_names:  # Property and definition names, such as "title", are not keywords.
            return {name: clean(value) for name, value in node.items()}
        return {("anyOf" if key == "oneOf" else key): clean(value, key in ("properties", "$defs"))
                for key, value in node.items() if key not in UNSUPPORTED_KEYWORDS}
    return clean(json_schema())


def normalize_ids(data, project_id: str):
    """Renumber scene and line ids and make node ids path-safe; highlights move with their nodes."""
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        return data
    data = copy.deepcopy(data)
    data["projectId"] = project_id
    for s, scene in enumerate(data["scenes"], start=1):
        if not isinstance(scene, dict):
            continue
        scene["id"] = f"scene-{s:02d}"
        visual = scene.get("visual")
        if scene.get("template") == "flow" and isinstance(visual, dict) and isinstance(visual.get("nodes"), list):
            for node in visual["nodes"]:
                if isinstance(node, dict) and isinstance(node.get("id"), str):
                    node["id"] = slug(node["id"])
        if isinstance(scene.get("narration"), list):
            for n, line in enumerate(scene["narration"], start=1):
                if isinstance(line, dict):
                    line["id"] = f"scene-{s:02d}-line-{n:02d}"
                    if isinstance(line.get("highlightNodeId"), str):
                        line["highlightNodeId"] = slug(line["highlightNodeId"])
    return data


def length_problems(plan, spec: dict) -> list[str]:
    seconds = spec["targetDurationSec"]
    low, target, high = word_range(seconds)
    min_scenes, max_scenes = scene_range(seconds)
    summary = summarize(plan)
    problems = []
    if not low <= summary["words"] <= high:
        change = "Add" if summary["words"] < low else "Remove"
        problems.append(f"narration: {summary['words']} words is about "
                        f"{summary['words'] / WORDS_PER_SECOND:.0f} seconds of speech, but the video needs "
                        f"{low} to {high} words. {change} about {abs(target - summary['words'])} words.")
    if not min_scenes <= summary["scenes"] <= max_scenes:
        problems.append(f"scenes: use {min_scenes} to {max_scenes} scenes, not {summary['scenes']}")
    if summary["templates"] != sorted(TEMPLATES):
        problems.append("scenes: use at least one concept scene and one flow scene")
    return problems


def _review(text: str, spec: dict):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, [f"the response is not valid JSON: {exc}"]
    try:
        plan = validate_plan(normalize_ids(data, spec["projectId"]))
    except PlanValidationError as exc:
        return None, exc.problems
    problems = length_problems(plan, spec)
    return (None if problems else plan), problems


def _record(response, latency_ms: int, text: str, problems: list[str]) -> dict:
    usage = getattr(response, "usage", None)
    return {"modelServed": getattr(response, "model", None),
            "requestId": getattr(response, "_request_id", None),
            "stopReason": response.stop_reason, "latencyMs": latency_ms,
            "usage": {name: getattr(usage, name, None) for name in
                      ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
            "problems": problems, "rawText": text}


def generate_plan(spec: dict, client, reference_text: str | None = None, progress=lambda message: None):
    """Return (plan, attempts). Raises PlannerError when no attempt yields a usable plan."""
    system = (PROMPTS / "scene-planner.txt").read_text(encoding="utf-8")
    repair = Template((PROMPTS / "repair-scene-plan.txt").read_text(encoding="utf-8"))
    messages = [{"role": "user", "content": request_text(spec, reference_text)}]
    attempts = []
    for attempt in (1, 2):
        progress(f"Requesting the scene plan from {MODEL} (attempt {attempt} of 2)...")
        started = perf_counter()
        response = client.beta.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": output_schema()}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        latency_ms = round((perf_counter() - started) * 1000)
        text = next((block.text for block in response.content if getattr(block, "type", None) == "text"), "")
        if response.stop_reason in FATAL_STOPS:
            category = getattr(getattr(response, "stop_details", None), "category", None)
            plan, problems = None, [FATAL_STOPS[response.stop_reason]
                                    + (f" (category: {category})" if category else "")]
        else:
            plan, problems = _review(text, spec)
        attempts.append(_record(response, latency_ms, text, problems))
        if plan is not None:
            return plan, attempts
        if response.stop_reason in FATAL_STOPS:
            break
        messages += [{"role": "assistant", "content": response.content},
                     {"role": "user", "content": repair.substitute(
                         problems="\n".join(f"- {problem}" for problem in problems))}]
    raise PlannerError("No usable scene plan: " + "; ".join(attempts[-1]["problems"]), attempts)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_plan_run(out_dir: Path, spec: dict, client, reference_text: str | None = None,
                   progress=lambda message: None):
    """Write project-spec.json, llm-response.json and, on success, scene-plan.json."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"Output already exists: {out_dir}. Choose a new output directory.")
    out_dir.mkdir(parents=True)
    write_json(out_dir / "project-spec.json", spec)
    record = {"promptVersion": PROMPT_VERSION, "modelRequested": MODEL, "effort": EFFORT,
              "createdAt": datetime.now(timezone.utc).isoformat()}
    try:
        plan, attempts = generate_plan(spec, client, reference_text, progress)
    except PlannerError as exc:
        write_json(out_dir / "llm-response.json",
                    {**record, "status": "failed", "error": str(exc), "attempts": exc.attempts})
        raise
    except Exception as exc:
        write_json(out_dir / "llm-response.json",
                    {**record, "status": "failed", "error": f"{type(exc).__name__}: {exc}", "attempts": []})
        raise
    write_json(out_dir / "llm-response.json", {**record, "status": "completed", "attempts": attempts})
    (out_dir / "scene-plan.json").write_text(dump_plan(plan), encoding="utf-8", newline="\n")
    return plan


def load_env_file(path: Path = Path(".env")) -> None:
    """Set variables from a local .env file without overriding the real environment."""
    path = Path(path)
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
