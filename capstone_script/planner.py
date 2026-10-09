"""Topic -> ScenePlan with the Claude API.

Videos up to three minutes take one request. Longer videos are planned chapter
by chapter (see long_form.py). Every response must pass the same validation as
a hand-written plan; if it does not, a single repair request lists every
problem. Raw responses and call metadata are saved for every run, including
failed ones; the API key never is.
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
from typing import Literal

from .scene_plan import (
    ICONS, TEMPLATES, WORDS_PER_SECOND, PlanValidationError, _Model, dump_plan, summarize, validate_plan,
)

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 16000
PROMPT_VERSION = "scene-planner-v5"
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
# The timeline adds short pauses around lines, so speech fills about 95% of the video.
SPEECH_SHARE = 0.95
MIN_SECONDS, MAX_SECONDS = 30, 600
# One request plans at most 12 scenes, about three minutes; longer videos are planned chapter by chapter.
SINGLE_PLAN_MAX_SECONDS = 180
SINGLE_PLAN_MAX_SCENES = 12
# List prices for Claude Opus 5.5 in US dollars per million tokens, used to estimate what a run cost.
PRICE_PER_MILLION = {"input_tokens": 4.0, "output_tokens": 20.0}
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


def scene_range(seconds: int, cap: int = SINGLE_PLAN_MAX_SCENES):
    low = 4 if seconds >= 60 else 2
    return low, min(cap, max(low + 1, round(seconds / 10)))


def make_spec(topic: str, audience: str, seconds: int, reference: Path | None = None):
    """Return the run's ProjectSpec and the reference text, if any."""
    topic, audience = topic.strip(), audience.strip()
    if not topic or not audience:
        raise ValueError("Topic and audience must not be empty.")
    if not MIN_SECONDS <= seconds <= MAX_SECONDS:
        raise ValueError(f"Duration must be between {MIN_SECONDS} and {MAX_SECONDS} seconds.")
    spec = {"schemaVersion": "1", "projectId": slug(topic), "topic": topic, "audience": audience,
            "language": "en", "targetDurationSec": seconds,
            "durationRangeSec": [round(seconds * 0.8), round(seconds * 1.2)],
            "planMode": "chapters" if seconds > SINGLE_PLAN_MAX_SECONDS else "single",
            "allowedTemplates": list(TEMPLATES)}
    reference_text = None
    if reference is not None:
        reference_text = Path(reference).read_text(encoding="utf-8-sig")
        spec["referenceFile"] = Path(reference).as_posix()
        spec["referenceSha256"] = hashlib.sha256(reference_text.encode("utf-8")).hexdigest()
    return spec, reference_text


def attach_reference_url(spec: dict, url: str, text: str, run_dir: Path) -> None:
    """Record a downloaded reference in the spec; the text itself is saved as run_dir/reference.md."""
    if "referenceFile" in spec:
        raise ValueError("Use a reference file or a reference URL, not both.")
    spec.update(referenceUrl=url, referenceFile=(Path(run_dir) / "reference.md").as_posix(),
                referenceSha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def save_reference(run_dir: Path, text: str) -> None:
    if Path(run_dir).is_dir():
        (Path(run_dir) / "reference.md").write_text(text, encoding="utf-8", newline="\n")


def request_text(spec: dict, reference_text: str | None = None) -> str:
    seconds = spec["targetDurationSec"]
    _, target, _ = word_range(seconds)
    min_scenes, max_scenes = scene_range(seconds)
    text = (f"Write the scene plan for this explainer video.\n\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n"
            f"Length: about {seconds} seconds, so about {target} words of narration in total "
            f"(stay between {round(target * 0.95)} and {round(target * 1.05)} words).\n"
            f"Scenes: {min_scenes} to {max_scenes}, using at least two different templates.")
    if reference_text and reference_text.strip():
        text += f"\n\nReference material:\n<reference>\n{reference_text.strip()}\n</reference>"
    return text


def structured_schema(schema: dict) -> dict:
    """A JSON Schema reduced to the keywords structured outputs accept."""
    def clean(node, keys_are_names=False):
        if isinstance(node, list):
            return [clean(item) for item in node]
        if not isinstance(node, dict):
            return node
        if keys_are_names:  # Property and definition names, such as "title", are not keywords.
            return {name: clean(value) for name, value in node.items()}
        return {("anyOf" if key == "oneOf" else key): clean(value, key in ("properties", "$defs"))
                for key, value in node.items() if key not in UNSUPPORTED_KEYWORDS}
    return clean(schema)


class _OutputLine(_Model):
    id: str
    text: str
    highlight_point_index: int | None = None
    highlight_node_id: str | None = None
    highlight_side: Literal["left", "right"] | None = None
    highlight_part: Literal["term", "definition", "example"] | None = None


class _OutputNode(_Model):
    id: str
    label: str
    icon: str | None = None


class _OutputColumn(_Model):
    label: str
    points: list[str]
    icon: str | None = None


class _OutputVisual(_Model):
    title: str
    statement: str | None = None
    points: list[str] | None = None
    nodes: list[_OutputNode] | None = None
    left: _OutputColumn | None = None
    right: _OutputColumn | None = None
    term: str | None = None
    definition: str | None = None
    example: str | None = None
    icon: str | None = None


class _OutputScene(_Model):
    id: str
    purpose: str
    template: Literal[TEMPLATES]
    visual: _OutputVisual
    narration: list[_OutputLine]


class _OutputPlan(_Model):
    schema_version: Literal["1"]
    project_id: str
    title: str
    scenes: list[_OutputScene]


def output_schema() -> dict:
    """A loose ScenePlan shape for structured outputs.

    The real schema, a union of four scene types, compiles to a grammar the API rejects as too
    large. This shape has one kind of scene whose template fields are all optional; validate_plan
    then applies each template's rules, and any problem goes back in the repair request. Chapters
    are left out because the program builds them.
    """
    return structured_schema(_OutputPlan.model_json_schema(by_alias=True))


def planner_prompt() -> str:
    """The scene planner's system prompt with the list of available icons filled in."""
    return Template((PROMPTS / "scene-planner.txt").read_text(encoding="utf-8")).safe_substitute(
        icons=", ".join(ICONS))


def drop_unknown_icons(data):
    """Remove icons that are not in the list: they are decoration, not worth a repair request."""
    for scene in data.get("scenes", []) if isinstance(data, dict) else []:
        visual = scene.get("visual") if isinstance(scene, dict) else None
        if not isinstance(visual, dict):
            continue
        holders = [visual, *(node for node in visual.get("nodes") or [] if isinstance(node, dict)),
                   *(visual[side] for side in ("left", "right") if isinstance(visual.get(side), dict))]
        for holder in holders:
            if holder.get("icon") not in ICONS:
                holder.pop("icon", None)
    return data


def drop_nulls(data):
    """Remove null values, which the loose output shape allows for fields a template does not use."""
    if isinstance(data, dict):
        return {key: drop_nulls(value) for key, value in data.items() if value is not None}
    if isinstance(data, list):
        return [drop_nulls(item) for item in data]
    return data


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


def length_problems(plan, spec: dict, require_templates: bool = True) -> list[str]:
    seconds = spec["targetDurationSec"]
    low, target, high = word_range(seconds)
    min_scenes, max_scenes = scene_range(seconds, spec.get("sceneCap", SINGLE_PLAN_MAX_SCENES))
    summary = summarize(plan)
    problems = []
    if not low <= summary["words"] <= high:
        change = "Add" if summary["words"] < low else "Remove"
        problems.append(f"narration: {summary['words']} words is about "
                        f"{summary['words'] / WORDS_PER_SECOND:.0f} seconds of speech, but the video needs "
                        f"{low} to {high} words. {change} about {abs(target - summary['words'])} words.")
    if not min_scenes <= summary["scenes"] <= max_scenes:
        problems.append(f"scenes: use {min_scenes} to {max_scenes} scenes, not {summary['scenes']}")
    if require_templates and len(summary["templates"]) < 2:
        problems.append("scenes: use at least two different templates")
    return problems


def coverage_problems(plan) -> list[str]:
    """Every point, node, column and example on screen should be highlighted by some line."""
    problems = []
    for s, scene in enumerate(plan.scenes):
        if scene.template == "flow":
            used = {line.highlight_node_id for line in scene.narration}
            missing = [repr(node.id) for node in scene.visual.nodes if node.id not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights node {', '.join(missing)}; "
                                "give each node a line that sets highlightNodeId")
        elif scene.template == "concept":
            used = {line.highlight_point_index for line in scene.narration}
            missing = [str(i) for i in range(len(scene.visual.points)) if i not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights point {', '.join(missing)}; "
                                "give each point a line that sets highlightPointIndex")
        elif scene.template == "comparison":
            used = {line.highlight_side for line in scene.narration}
            missing = [side for side in ("left", "right") if side not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights the {' and '.join(missing)} column; "
                                "give each column a line that sets highlightSide")
        elif scene.visual.example is not None:
            if "example" not in {line.highlight_part for line in scene.narration}:
                problems.append(f"scenes[{s}]: no narration line highlights the example; "
                                "give it a line that sets highlightPart to 'example'")
    return problems


def parse_json(text: str):
    """Return (data, problems); problems is empty when the text is valid JSON."""
    try:
        return json.loads(text), []
    except json.JSONDecodeError as exc:
        return None, [f"the response is not valid JSON: {exc}"]


def review_plan(text: str, spec: dict, require_templates: bool = True):
    """Return (plan, problems); the plan is None unless the response can be used as it is."""
    data, problems = parse_json(text)
    if problems:
        return None, problems
    try:
        plan = validate_plan(normalize_ids(drop_unknown_icons(drop_nulls(data)), spec["projectId"]))
    except PlanValidationError as exc:
        return None, exc.problems
    problems = length_problems(plan, spec, require_templates) + coverage_problems(plan)
    return (None if problems else plan), problems


def _record(step: str, response, latency_ms: int, text: str, problems: list[str]) -> dict:
    usage = getattr(response, "usage", None)
    return {"step": step, "modelServed": getattr(response, "model", None),
            "requestId": getattr(response, "_request_id", None),
            "stopReason": response.stop_reason, "latencyMs": latency_ms,
            "usage": {name: getattr(usage, name, None) for name in
                      ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")},
            "problems": problems, "rawText": text}


def request_json(client, system: str, request: str, schema: dict, review, noun: str, attempts: list,
                 step: str, progress=lambda message: None):
    """Send one structured-output request plus at most one repair and return the reviewed result.

    `review(text)` returns (result, problems); a None result goes back with its problems.
    Every response is appended to `attempts` as it arrives, so a failed run keeps the evidence.
    """
    repair = Template((PROMPTS / "repair-scene-plan.txt").read_text(encoding="utf-8"))
    messages = [{"role": "user", "content": request}]
    for attempt in (1, 2):
        progress(f"Requesting the {noun} from {MODEL} (attempt {attempt} of 2)...")
        started = perf_counter()
        response = client.beta.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=system, messages=messages,
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        )
        latency_ms = round((perf_counter() - started) * 1000)
        text = next((block.text for block in response.content if getattr(block, "type", None) == "text"), "")
        if response.stop_reason in FATAL_STOPS:
            category = getattr(getattr(response, "stop_details", None), "category", None)
            result, problems = None, [FATAL_STOPS[response.stop_reason]
                                      + (f" (category: {category})" if category else "")]
        else:
            result, problems = review(text)
        attempts.append(_record(step, response, latency_ms, text, problems))
        if result is not None:
            return result
        if response.stop_reason in FATAL_STOPS:
            break
        messages += [{"role": "assistant", "content": response.content},
                     {"role": "user", "content": repair.substitute(
                         problems="\n".join(f"- {problem}" for problem in problems))}]
    raise PlannerError(f"No usable {noun}: " + "; ".join(attempts[-1]["problems"]), attempts)


def generate_plan(spec: dict, client, reference_text: str | None = None, progress=lambda message: None,
                  attempts: list | None = None):
    """Return a plan from one request (plus one repair). Raises PlannerError when none is usable."""
    system = planner_prompt()
    return request_json(client, system, request_text(spec, reference_text), output_schema(),
                        lambda text: review_plan(text, spec), "scene plan",
                        [] if attempts is None else attempts, "plan", progress)


def estimated_cost(attempts) -> float:
    """List-price estimate in US dollars for every request in a run."""
    return round(sum((attempt["usage"].get(name) or 0) * price / 1_000_000
                     for attempt in attempts for name, price in PRICE_PER_MILLION.items()), 4)


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def write_plan_run(out_dir: Path, spec: dict, client, reference_text: str | None = None,
                   progress=lambda message: None):
    """Write project-spec.json, llm-response.json and, on success, scene-plan.json.

    Videos planned chapter by chapter also get outline.json.
    """
    from .long_form import CHAPTER_PROMPT_VERSION, OUTLINE_PROMPT_VERSION, generate_long_plan

    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"Output already exists: {out_dir}. Choose a new output directory.")
    out_dir.mkdir(parents=True)
    write_json(out_dir / "project-spec.json", spec)
    chapters = spec["targetDurationSec"] > SINGLE_PLAN_MAX_SECONDS
    record = {"promptVersion": PROMPT_VERSION, "modelRequested": MODEL, "effort": EFFORT,
              "mode": "chapters" if chapters else "single",
              "createdAt": datetime.now(timezone.utc).isoformat()}
    if chapters:
        record.update(outlinePromptVersion=OUTLINE_PROMPT_VERSION, chapterPromptVersion=CHAPTER_PROMPT_VERSION)
    attempts = []
    try:
        if chapters:
            plan, outline = generate_long_plan(spec, client, reference_text, progress, attempts)
            write_json(out_dir / "outline.json", outline)
        else:
            plan = generate_plan(spec, client, reference_text, progress, attempts)
    except Exception as exc:
        error = str(exc) if isinstance(exc, PlannerError) else f"{type(exc).__name__}: {exc}"
        write_json(out_dir / "llm-response.json", {**record, "status": "failed", "error": error,
                                                    "estimatedCostUsd": estimated_cost(attempts),
                                                    "attempts": attempts})
        raise
    write_json(out_dir / "llm-response.json", {**record, "status": "completed",
                                                "estimatedCostUsd": estimated_cost(attempts),
                                                "attempts": attempts})
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
