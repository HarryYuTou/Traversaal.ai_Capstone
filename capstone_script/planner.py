"""Topic -> ScenePlan with the Claude API.

Production runs first select a compact visual vocabulary. Videos up to three
minutes then take one scene-planning request; longer videos are planned chapter
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

from pydantic import ValidationError

from .scene_plan import (
    ICONS, MAP_REGIONS, TEMPLATES, WORDS_PER_SECOND, MotionAction, MotionEntity, MotionPath,
    ProcessActor, ProcessStation, ProcessOccupancy, ProcessEvent,
    PlanValidationError, _Model, dump_plan, error_problems, summarize,
    validate_plan,
)

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 16000
PROMPT_VERSION = "scene-planner-v12"
TEMPLATE_ROUTER_VERSION = "template-router-v3"
MAX_REQUEST_TEMPLATES = 3
PROMPTS = Path(__file__).resolve().parents[1] / "prompts"
# The timeline adds short pauses around lines, so speech fills about 95% of the video.
SPEECH_SHARE = 0.95
MIN_SECONDS, MAX_SECONDS = 30, 600
# One request plans at most 12 scenes, about three minutes; longer videos are planned chapter by chapter.
SINGLE_PLAN_MAX_SECONDS = 180
SINGLE_PLAN_MAX_SCENES = 12
REFERENCE_COPY = "reference.md"
# List prices for Claude Opus 5.5 in US dollars per million tokens, used to estimate what a run cost.
PRICE_PER_MILLION = {"input_tokens": 4.0, "output_tokens": 20.0}
# Structured outputs reject these JSON Schema keywords; validate_plan still enforces them.
UNSUPPORTED_KEYWORDS = {"minLength", "maxLength", "minimum", "maximum", "exclusiveMinimum",
                        "exclusiveMaximum", "multipleOf", "minItems", "maxItems", "pattern",
                        "default", "title", "discriminator", "$schema", "$id"}
FATAL_STOPS = {"refusal": "the model declined the request",
               "max_tokens": "the response hit the output limit before the plan was complete"}
# Optional ScenePlan fields that the output shape requires, with "" meaning "none".
OPTIONAL_TEXT = ("icon", "example", "prefix", "unit", "note", "context")
# The ScenePlan field that a narration line's highlight fills, by template.
HIGHLIGHT_FIELDS = {"concept": "highlightPointIndex", "flow": "highlightNodeId", "comparison": "highlightSide",
                    "definition": "highlightPart", "timeline": "highlightEventId", "stat": "highlightStatIndex",
                    "quote": "highlightQuote", "map": "highlightId"}
HIGHLIGHT_WORDS = {"comparison": ("left", "right"), "definition": ("term", "definition", "example"),
                   "quote": ("quote",)}


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
    low = 2
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


def attach_reference_url(spec: dict, url: str, text: str) -> None:
    """Record a downloaded reference in the spec; write_plan_run saves the text as reference.md."""
    if "referenceFile" in spec:
        raise ValueError("Use a reference file or a reference URL, not both.")
    spec.update(referenceUrl=url, referenceSha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def request_text(spec: dict, reference_text: str | None = None) -> str:
    seconds = spec["targetDurationSec"]
    _, target, _ = word_range(seconds)
    min_scenes, max_scenes = scene_range(seconds)
    text = (f"Write the scene plan for this explainer video.\n\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n"
            f"Length: about {seconds} seconds, so about {target} words of narration in total "
            f"(stay between {round(target * 0.95)} and {round(target * 1.05)} words).\n"
            f"Scenes: {min_scenes} to {max_scenes}. Prefer process for arrivals, waiting and service; "
            "prefer motion for other physical transfers, journeys and changing state. "
            "Use process or motion throughout when it best explains the topic; there is no minimum template variety. "
            "Prefer two or three coherent scenes when they fit the narration limits.")
    text += "\n" + template_instruction(spec)
    if reference_text and reference_text.strip():
        text += f"\n\nReference material:\n<reference>\n{reference_text.strip()}\n</reference>"
    return text


def template_instruction(spec: dict) -> str:
    """Keep the request and its restricted structured-output schema in agreement."""
    return ("Allowed templates for this video: " + ", ".join(spec.get("allowedTemplates", TEMPLATES))
            + ". Use only these templates; you do not have to use every one.")


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


# The planner's output shape. Structured outputs accept at most 24 optional and 16 union-typed
# parameters per request (anyOf, which is how `| None` is written, counts as both), so nothing here
# is nullable: fields a ScenePlan may leave out are required and take "" for "none", and each visual
# has one optional part per template. from_model_output turns the result into ScenePlan data.
class _OutputLine(_Model):
    id: str
    text: str
    # What the line points at on screen, or "": a point or number position such as "0", a node,
    # event, place or area id, "left" or "right", "term", "definition" or "example", or "quote".
    highlight: str


class _OutputConcept(_Model):
    statement: str
    points: list[str]
    icon: str


class _OutputNode(_Model):
    id: str
    label: str
    icon: str


class _OutputFlow(_Model):
    nodes: list[_OutputNode]


class _OutputColumn(_Model):
    label: str
    points: list[str]
    icon: str


class _OutputComparison(_Model):
    left: _OutputColumn
    right: _OutputColumn


class _OutputDefinition(_Model):
    term: str
    definition: str
    example: str
    icon: str


class _OutputEvent(_Model):
    id: str
    date: str
    label: str
    icon: str


class _OutputTimeline(_Model):
    events: list[_OutputEvent]


class _OutputStat(_Model):
    value: float
    prefix: str
    unit: str
    label: str
    icon: str


class _OutputStats(_Model):
    stats: list[_OutputStat]
    note: str


class _OutputQuote(_Model):
    quote: str
    author: str
    context: str


class _OutputArea(_Model):
    id: str
    label: str
    countries: list[str]


class _OutputPlace(_Model):
    id: str
    label: str
    lon: float
    lat: float


class _OutputMap(_Model):
    region: str
    areas: list[_OutputArea]
    places: list[_OutputPlace]
    route: bool


class _OutputMotion(_Model):
    # Every nested field is required, so adding motion does not spend optional/union schema slots.
    entities: list[MotionEntity]
    paths: list[MotionPath]
    actions: list[MotionAction]


class _OutputProcess(_Model):
    actor_kind: Literal["person", "packet", "box", "coin"]
    actors: list[ProcessActor]
    stations: list[ProcessStation]
    initial_queue: list[str]
    initial_service: list[ProcessOccupancy]
    events: list[ProcessEvent]


class _OutputVisual(_Model):
    title: str
    # Optional but not nullable: a scene fills only its own template's part and leaves out the rest.
    concept: _OutputConcept = None
    flow: _OutputFlow = None
    comparison: _OutputComparison = None
    definition: _OutputDefinition = None
    timeline: _OutputTimeline = None
    stat: _OutputStats = None
    quote: _OutputQuote = None
    map: _OutputMap = None
    motion: _OutputMotion = None
    process: _OutputProcess = None


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


def output_schema(templates=None) -> dict:
    """The planner's output shape as a schema for structured outputs.

    The real ScenePlan schema, a union of scene types, compiled to a grammar the API rejected as
    too large when it had only four. This shape has one kind of scene whose visual holds one part
    per template. Production requests select at most three templates first, remove the other
    visual parts and prune unreachable definitions to bound the compiled grammar;
    from_model_output turns it into ScenePlan data, validate_plan then applies each template's
    rules, and any problem goes back in the repair request. Chapters are left out because the
    program builds them.
    """
    schema = structured_schema(_OutputPlan.model_json_schema(by_alias=True))
    if templates is None:
        return schema
    templates = checked_templates(templates)
    visual = schema["$defs"]["_OutputVisual"]
    visual["properties"] = {key: value for key, value in visual["properties"].items()
                            if key == "title" or key in templates}
    if len(templates) == 1:
        visual["required"] = ["title", templates[0]]
    schema["$defs"]["_OutputScene"]["properties"]["template"]["enum"] = templates
    # Unused definitions still consume grammar compiler resources. Follow references from the
    # root rather than keeping every template's definitions in each bounded request.
    definitions = schema.pop("$defs")
    reachable = set()

    def visit(node):
        if isinstance(node, dict):
            reference = node.get("$ref", "")
            if reference.startswith("#/$defs/"):
                name = reference.removeprefix("#/$defs/")
                if name not in reachable:
                    reachable.add(name)
                    visit(definitions[name])
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema)
    schema["$defs"] = {name: value for name, value in definitions.items() if name in reachable}
    return schema


def checked_templates(templates) -> list[str]:
    """Reject ambiguous or unsupported request settings before contacting the API."""
    if not isinstance(templates, (list, tuple)) or not templates:
        raise ValueError("allowedTemplates must be a nonempty list of template names.")
    if any(not isinstance(item, str) or item not in TEMPLATES for item in templates):
        raise ValueError("allowedTemplates contains an unsupported template.")
    if len(set(templates)) != len(templates):
        raise ValueError("allowedTemplates must not contain duplicates.")
    return list(templates)


class _TemplateSelection(_Model):
    templates: list[Literal[TEMPLATES]]


def review_template_selection(text: str, candidates):
    data, problems = parse_json(text)
    if problems:
        return None, problems
    try:
        selection = _TemplateSelection.model_validate(data)
    except ValidationError as exc:
        return None, error_problems(exc)
    chosen = selection.templates
    if not 1 <= len(chosen) <= MAX_REQUEST_TEMPLATES:
        problems.append(f"templates: choose one to {MAX_REQUEST_TEMPLATES} templates")
    if len(set(chosen)) != len(chosen):
        problems.append("templates: do not repeat a template")
    if any(item not in candidates for item in chosen):
        problems.append("templates: use only the available templates: " + ", ".join(candidates))
    return (None if problems else chosen), problems


def select_templates(spec, client, reference_text, attempts, progress):
    """Select a small, topic-appropriate schema before generating any detailed scenes."""
    candidates = checked_templates(spec.get("allowedTemplates", list(TEMPLATES)))
    if len(candidates) <= MAX_REQUEST_TEMPLATES:
        return candidates, "explicit"
    schema = structured_schema(_TemplateSelection.model_json_schema(by_alias=True))
    schema["properties"]["templates"]["items"]["enum"] = candidates
    request = (f"Select the visual templates for this explainer.\n\nTopic: {spec['topic']}\n"
               f"Audience: {spec['audience']}\nLength: about {spec['targetDurationSec']} seconds.\n"
               f"Available templates: {', '.join(candidates)}.")
    if reference_text and reference_text.strip():
        request += f"\n\nReference material:\n<reference>\n{reference_text.strip()}\n</reference>"
    chosen = request_json(client, (PROMPTS / "template-router.txt").read_text(encoding="utf-8"),
                          request, schema, lambda text: review_template_selection(text, candidates),
                          "visual template selection", attempts, "template-selection", progress,
                          max_tokens=1024, effort="low")
    return chosen, "routed"


def planner_prompt(templates=None) -> str:
    """The scene planner's system prompt with the available icons and map regions filled in."""
    prompt = (PROMPTS / "scene-planner.txt").read_text(encoding="utf-8")
    if templates is not None:
        allowed = set(checked_templates(templates))
        kept, skipped = [], False
        for line in prompt.splitlines():
            match = re.match(r"^- ([a-z]+):", line)
            if match and match[1] in TEMPLATES:
                skipped = match[1] not in allowed
            elif line.startswith("- ") or (line and not line.startswith(" ")):
                skipped = False
            if skipped:
                continue
            if line.startswith("- Icons:") and not allowed & {"concept", "definition", "flow", "comparison", "timeline", "stat"}:
                continue
            if line.startswith("- Walk the viewer") and allowed <= {"process", "motion"}:
                continue
            if line.startswith("- Process actors,") and "process" not in allowed:
                continue
            if line.startswith("- Motion entities,") and "motion" not in allowed:
                continue
            kept.append(line)
        prompt = "\n".join(kept) + "\n"
    return Template(prompt).safe_substitute(
        icons=", ".join(ICONS), regions=", ".join(MAP_REGIONS))


def drop_unknown_icons(data):
    """Remove icons that are not in the list: they are decoration, not worth a repair request."""
    for scene in data.get("scenes", []) if isinstance(data, dict) else []:
        visual = scene.get("visual") if isinstance(scene, dict) else None
        if not isinstance(visual, dict):
            continue
        holders = [visual, *(item for key in ("nodes", "events", "stats")
                             for item in visual.get(key) or [] if isinstance(item, dict)),
                   *(visual[side] for side in ("left", "right") if isinstance(visual.get(side), dict))]
        for holder in holders:
            if holder.get("icon") not in ICONS:
                holder.pop("icon", None)
    return data


def drop_empty_text(data):
    """Remove optional text fields set to "", the output shape's way of leaving them out."""
    if isinstance(data, dict):
        return {key: drop_empty_text(value) for key, value in data.items()
                if not (key in OPTIONAL_TEXT and value == "")}
    if isinstance(data, list):
        return [drop_empty_text(item) for item in data]
    return data


def highlight_value(template: str, highlight):
    """The ScenePlan value of a line's highlight, or None for ""; ValueError says what is wrong."""
    if not isinstance(highlight, str):
        raise ValueError("must be text")
    highlight = highlight.strip()
    if not highlight:
        return None
    if template in ("motion", "process"):
        noun = "actions" if template == "motion" else "events"
        raise ValueError(f'a {template} scene uses narration-bound {noun}; highlight must be ""')
    if template in ("concept", "stat"):
        if not (highlight.isascii() and highlight.isdigit()):
            noun = "point" if template == "concept" else "number"
            raise ValueError(f"{highlight!r} is not a {noun} position; use \"0\", \"1\" or \"2\", or \"\" for none")
        return int(highlight)
    if template in HIGHLIGHT_WORDS:
        words = HIGHLIGHT_WORDS[template]
        if highlight not in words:
            raise ValueError(f"{highlight!r} cannot be highlighted in a {template} scene; use "
                             + ", ".join(f'"{word}"' for word in words) + ' or ""')
        return True if template == "quote" else highlight
    return highlight  # A node, event, place or area id; validation checks that it exists.


def from_model_output(data):
    """Turn the planner's output shape into ScenePlan data; return (data, problems).

    A visual keeps its title and the fields of its template's part, optional text set to "" is
    left out, and each line's highlight becomes its template's highlight field. Problems name the
    output shape's fields, so a repair request matches what the model wrote.
    """
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        return data, []
    data, problems = copy.deepcopy(data), []
    for s, scene in enumerate(data["scenes"]):
        if not isinstance(scene, dict) or scene.get("template") not in TEMPLATES:
            continue
        template, visual = scene["template"], scene.get("visual")
        if isinstance(visual, dict):
            part = visual.get(template)
            if not isinstance(part, dict):
                problems.append(f"scenes[{s}].visual.{template}: a {template} scene needs this part; fill it, "
                                "or set the template to the one whose part you filled")
                part = {}
            scene["visual"] = {"title": visual.get("title"), **drop_empty_text(part)}
        lines = scene.get("narration")
        for i, line in enumerate(lines if isinstance(lines, list) else []):
            if not isinstance(line, dict) or "highlight" not in line:
                continue
            try:
                value = highlight_value(template, line.pop("highlight"))
            except ValueError as exc:
                problems.append(f"scenes[{s}].narration[{i}].highlight: {exc}")
                continue
            if value is not None:
                line[HIGHLIGHT_FIELDS[template]] = value
    return data, problems


def output_terms(problem: str, data) -> str:
    """Name a ScenePlan problem's location as the output shape does, such as visual.flow.nodes."""
    problem = re.sub(r"\.highlight[A-Z]\w*", ".highlight", problem)
    match = re.match(r"scenes\[(\d+)\]\.visual\b(?!\.title\b)", problem)
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if match and isinstance(scenes, list) and int(match.group(1)) < len(scenes):
        scene = scenes[int(match.group(1))]
        template = scene.get("template") if isinstance(scene, dict) else None
        if template in TEMPLATES:
            problem = f"{problem[:match.end()]}.{template}{problem[match.end():]}"
    return problem


def normalize_ids(data, project_id: str):
    """Renumber scenes/lines and make visual ids path-safe; keep action references and line indices."""
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list):
        return data
    data = copy.deepcopy(data)
    data["projectId"] = project_id
    for s, scene in enumerate(data["scenes"], start=1):
        if not isinstance(scene, dict):
            continue
        scene["id"] = f"scene-{s:02d}"
        visual = scene.get("visual")
        if isinstance(visual, dict):
            for key in ("nodes", "events", "areas", "places", "entities", "paths", "actors", "stations"):
                items = visual.get(key)
                for item in items if isinstance(items, list) else []:
                    if isinstance(item, dict) and isinstance(item.get("id"), str):
                        item["id"] = slug(item["id"])
            if scene.get("template") == "motion":
                actions = visual.get("actions")
                for action in actions if isinstance(actions, list) else []:
                    if isinstance(action, dict):
                        for key in ("entityId", "pathId"):
                            if isinstance(action.get(key), str) and action[key]:
                                action[key] = slug(action[key])
            if scene.get("template") == "process":
                queue = visual.get("initialQueue")
                if isinstance(queue, list):
                    visual["initialQueue"] = [slug(value) if isinstance(value, str) else value for value in queue]
                occupancy = visual.get("initialService")
                for item in occupancy if isinstance(occupancy, list) else []:
                    if isinstance(item, dict):
                        for key in ("actorId", "stationId"):
                            if isinstance(item.get(key), str):
                                item[key] = slug(item[key])
                events = visual.get("events")
                for event in events if isinstance(events, list) else []:
                    if isinstance(event, dict):
                        for key in ("actorIds", "stationIds"):
                            if isinstance(event.get(key), list):
                                event[key] = [slug(value) if isinstance(value, str) else value for value in event[key]]
        if isinstance(scene.get("narration"), list):
            for n, line in enumerate(scene["narration"], start=1):
                if isinstance(line, dict):
                    line["id"] = f"scene-{s:02d}-line-{n:02d}"
                    for key in ("highlightNodeId", "highlightEventId", "highlightId"):
                        if isinstance(line.get(key), str):
                            line[key] = slug(line[key])
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
    # Keep require_templates in the public signature for existing callers. A coherent visual
    # explanation may use motion throughout; template variety is no longer a validity rule.
    return problems


def coverage_problems(plan) -> list[str]:
    """Every point, node, column and example on screen should be highlighted by some line."""
    problems = []
    for s, scene in enumerate(plan.scenes):
        if scene.template == "process":
            events = scene.visual.events
            if not any(event.kind != "hold" for event in events):
                problems.append(f"scenes[{s}]: a process needs at least one visible state change; "
                                "use arrive, start or finish, or choose a supporting template")
            for index in range(len(scene.narration)):
                if not any((event.start_line, event.start_offset) < (index, 1)
                           and (index, 0) < (event.end_line, event.end_offset) for event in events):
                    problems.append(f"scenes[{s}].narration[{index}]: no process event covers this line; "
                                    "show its causal change or add an explicit hold for a readable state")
        elif scene.template == "flow":
            used = {line.highlight_node_id for line in scene.narration}
            missing = [repr(node.id) for node in scene.visual.nodes if node.id not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights node {', '.join(missing)}; "
                                "give each node a line whose highlight is its id")
        elif scene.template == "concept":
            used = {line.highlight_point_index for line in scene.narration}
            missing = [str(i) for i in range(len(scene.visual.points)) if i not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights point {', '.join(missing)}; "
                                "give each point a line whose highlight is its position, counting from \"0\"")
        elif scene.template == "comparison":
            used = {line.highlight_side for line in scene.narration}
            missing = [side for side in ("left", "right") if side not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights the {' and '.join(missing)} column; "
                                "give each column a line whose highlight is \"left\" or \"right\"")
        elif scene.template == "definition" and scene.visual.example is not None:
            if "example" not in {line.highlight_part for line in scene.narration}:
                problems.append(f"scenes[{s}]: no narration line highlights the example; "
                                "give it a line whose highlight is \"example\"")
        elif scene.template == "timeline":
            used = {line.highlight_event_id for line in scene.narration}
            missing = [repr(event.id) for event in scene.visual.events if event.id not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights event {', '.join(missing)}; "
                                "give each event a line whose highlight is its id")
        elif scene.template == "stat":
            used = {line.highlight_stat_index for line in scene.narration}
            missing = [str(i) for i in range(len(scene.visual.stats)) if i not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights number {', '.join(missing)}; "
                                "give each number a line whose highlight is its position, counting from \"0\"")
        elif scene.template == "quote":
            if not any(line.highlight_quote for line in scene.narration):
                problems.append(f"scenes[{s}]: no narration line reads the quotation; give one line the "
                                "quotation's exact words and the highlight \"quote\"")
        elif scene.template == "map":
            used = {line.highlight_id for line in scene.narration}
            missing = [repr(item.id) for item in [*scene.visual.areas, *scene.visual.places] if item.id not in used]
            if missing:
                problems.append(f"scenes[{s}]: no narration line highlights {', '.join(missing)}; "
                                "give each place and area a line whose highlight is its id")
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
    data, problems = from_model_output(data)
    # A visual without its template's part also fails validation; the missing part is reported once.
    partless = tuple(problem.split(":", 1)[0] for problem in problems if ".visual." in problem)
    try:
        plan = validate_plan(normalize_ids(drop_unknown_icons(data), spec["projectId"]))
    except PlanValidationError as exc:
        found = [output_terms(problem, data) for problem in exc.problems]
        return None, problems + [problem for problem in found if not problem.startswith(partless)]
    allowed = spec.get("allowedTemplates", TEMPLATES)
    problems += [f"scenes[{index}].template: {scene.template!r} is not allowed for this video; use "
                 + ", ".join(allowed)
                 for index, scene in enumerate(plan.scenes) if scene.template not in allowed]
    problems += length_problems(plan, spec, require_templates) + coverage_problems(plan)
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
                 step: str, progress=lambda message: None, *, max_tokens=MAX_TOKENS, effort=EFFORT):
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
            model=MODEL, max_tokens=max_tokens, system=system, messages=messages,
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
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
        attempts.append({**_record(step, response, latency_ms, text, problems),
                         "effort": effort, "maxTokens": max_tokens})
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
    system = planner_prompt(spec.get("allowedTemplates"))
    return request_json(client, system, request_text(spec, reference_text), output_schema(spec.get("allowedTemplates")),
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

    spec = {**spec, "templateRouterVersion": TEMPLATE_ROUTER_VERSION}
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"Output already exists: {out_dir}. Choose a new output directory.")
    out_dir.mkdir(parents=True)
    if reference_text is not None:
        # The run keeps its own copy, so a later review finds the reference wherever the run is opened.
        (out_dir / REFERENCE_COPY).write_text(reference_text, encoding="utf-8", newline="\n")
        spec = {**spec, "referenceCopy": REFERENCE_COPY}
    write_json(out_dir / "project-spec.json", spec)
    chapters = spec["targetDurationSec"] > SINGLE_PLAN_MAX_SECONDS
    record = {"promptVersion": PROMPT_VERSION, "templateRouterVersion": TEMPLATE_ROUTER_VERSION,
              "modelRequested": MODEL, "effort": EFFORT,
              "mode": "chapters" if chapters else "single",
              "createdAt": datetime.now(timezone.utc).isoformat()}
    if chapters:
        record.update(outlinePromptVersion=OUTLINE_PROMPT_VERSION, chapterPromptVersion=CHAPTER_PROMPT_VERSION)
    attempts = []
    try:
        templates, selection_mode = select_templates(spec, client, reference_text, attempts, progress)
        spec.update(allowedTemplates=templates, templateSelection=selection_mode)
        record.update(allowedTemplates=templates, templateSelection=selection_mode)
        write_json(out_dir / "project-spec.json", spec)
        progress("Visual templates: " + ", ".join(templates))
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
