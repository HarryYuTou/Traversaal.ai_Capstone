"""ScenePlan: the scene-by-scene script that the planner writes.

A plan says what each scene shows (one of four visual templates) and what the
narrator says, one short line at a time. Long plans also group their scenes
into chapters. A plan never contains audio paths, durations or frame numbers;
later stages measure those from real audio.

The Pydantic models hold the structural rules and are exported as JSON Schema
for the renderer. Cross-reference rules (unique IDs, valid highlights, word
limits, English text) are checked in Python by `semantic_problems`. JSON Schema
cannot express them, so other languages must not assume the schema covers them.
"""

import json
from pathlib import Path
from typing import Annotated, Literal, Union
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from pydantic.alias_generators import to_camel

SCHEMA_VERSION = "1"
TEMPLATES = ("concept", "flow", "comparison", "definition")
MAX_SCENES = 60
MAX_CHAPTERS = 10
MAX_LINES_PER_SCENE = 8
MAX_LINE_WORDS = 25
# Measured with capstone_tts at speed 1.0, one line at a time: the 214-word fixture
# took 81.0 s (2.64 words/s). Whole paragraphs read faster, about 2.9 words/s.
WORDS_PER_SECOND = 2.6

# IDs become file names (audio/<narrationId>.wav), so they must be path-safe.
Id = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=48)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=60)]
Label = Annotated[str, StringConstraints(min_length=1, max_length=24)]
Point = Annotated[str, StringConstraints(min_length=1, max_length=60)]
ColumnPoint = Annotated[str, StringConstraints(min_length=1, max_length=48)]
Statement = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Term = Annotated[str, StringConstraints(min_length=1, max_length=40)]
Definition = Annotated[str, StringConstraints(min_length=1, max_length=140)]
Example = Annotated[str, StringConstraints(min_length=1, max_length=100)]
Purpose = Annotated[str, StringConstraints(min_length=1, max_length=200)]
# A character cap the schema can express; the word limit is a semantic check.
LineText = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              alias_generator=to_camel)


class ConceptLine(_Model):
    id: Id
    text: LineText
    highlight_point_index: Annotated[int, Field(ge=0)] | None = None


class FlowLine(_Model):
    id: Id
    text: LineText
    highlight_node_id: Id | None = None


class ComparisonLine(_Model):
    id: Id
    text: LineText
    highlight_side: Literal["left", "right"] | None = None


class DefinitionLine(_Model):
    id: Id
    text: LineText
    highlight_part: Literal["term", "definition", "example"] | None = None


class FlowNode(_Model):
    id: Id
    label: Label


class ConceptVisual(_Model):
    title: Title
    statement: Statement
    points: list[Point] = Field(default_factory=list, max_length=3)


class FlowVisual(_Model):
    title: Title
    nodes: list[FlowNode] = Field(min_length=2, max_length=4)


class ComparisonColumn(_Model):
    label: Label
    points: list[ColumnPoint] = Field(min_length=1, max_length=3)


class ComparisonVisual(_Model):
    title: Title
    left: ComparisonColumn
    right: ComparisonColumn


class DefinitionVisual(_Model):
    title: Title
    term: Term
    definition: Definition
    example: Example | None = None


class ConceptScene(_Model):
    """A title, one core statement and up to three points."""

    id: Id
    purpose: Purpose
    template: Literal["concept"]
    visual: ConceptVisual
    narration: list[ConceptLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class FlowScene(_Model):
    """A title and two to four nodes connected in order."""

    id: Id
    purpose: Purpose
    template: Literal["flow"]
    visual: FlowVisual
    narration: list[FlowLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class ComparisonScene(_Model):
    """A title and two labelled columns that contrast two things, with up to three points each."""

    id: Id
    purpose: Purpose
    template: Literal["comparison"]
    visual: ComparisonVisual
    narration: list[ComparisonLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class DefinitionScene(_Model):
    """A title, one key term, its plain-language definition and an optional example."""

    id: Id
    purpose: Purpose
    template: Literal["definition"]
    visual: DefinitionVisual
    narration: list[DefinitionLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


Scene = Annotated[Union[ConceptScene, FlowScene, ComparisonScene, DefinitionScene],
                  Field(discriminator="template")]


class Chapter(_Model):
    """A named run of consecutive scenes in a long video."""

    id: Id
    title: Title
    scene_ids: list[Id] = Field(min_length=1, max_length=MAX_SCENES)


class ScenePlan(_Model):
    """Scene-by-scene script: what each scene shows and what the narrator says."""

    schema_version: Literal["1"]
    project_id: Id
    title: Title
    scenes: list[Scene] = Field(min_length=1, max_length=MAX_SCENES)
    # Optional: when present, the chapters list every scene once, in plan order.
    chapters: list[Chapter] | None = Field(default=None, min_length=1, max_length=MAX_CHAPTERS)


class PlanValidationError(ValueError):
    """Every problem found in a plan, each prefixed with its JSON location."""

    def __init__(self, problems):
        self.problems = list(problems)
        super().__init__(f"{len(self.problems)} problem(s): " + "; ".join(self.problems))


def text_words(text: str) -> list[str]:
    return [word for word in text.split() if any(c.isalnum() for c in word)]


def text_problems(text: str) -> list[str]:
    problems = []
    words = text_words(text)
    if not words:
        problems.append("must contain spoken words")
    elif len(words) > MAX_LINE_WORDS:
        problems.append(f"has {len(words)} words; split it into lines of at most {MAX_LINE_WORDS}")
    # Same rule as capstone_tts: the voice only reads Latin-script English.
    if any(c.isalpha() and "LATIN" not in unicodedata.name(c, "") for c in text):
        problems.append("must be English; the narration voice only supports Latin script")
    return problems


def semantic_problems(plan: ScenePlan) -> list[str]:
    problems = []
    scene_ids, line_ids = set(), set()
    for s, scene in enumerate(plan.scenes):
        where = f"scenes[{s}]"
        if scene.id in scene_ids:
            problems.append(f"{where}.id: duplicate scene id {scene.id!r}")
        scene_ids.add(scene.id)
        if scene.template == "flow":
            node_ids = [node.id for node in scene.visual.nodes]
            for n, node_id in enumerate(node_ids):
                if node_id in node_ids[:n]:
                    problems.append(f"{where}.visual.nodes[{n}].id: duplicate node id {node_id!r}")
        for i, line in enumerate(scene.narration):
            at = f"{where}.narration[{i}]"
            if line.id in line_ids:
                problems.append(f"{at}.id: duplicate narration id {line.id!r}; "
                                "narration ids must be unique across the plan")
            line_ids.add(line.id)
            problems += [f"{at}.text: {problem}" for problem in text_problems(line.text)]
            if scene.template == "flow":
                if line.highlight_node_id is not None and line.highlight_node_id not in node_ids:
                    problems.append(f"{at}.highlightNodeId: {line.highlight_node_id!r} "
                                    "is not a node in this scene")
            elif scene.template == "concept":
                if (line.highlight_point_index is not None
                        and line.highlight_point_index >= len(scene.visual.points)):
                    problems.append(f"{at}.highlightPointIndex: {line.highlight_point_index} is out of range; "
                                    f"this scene has {len(scene.visual.points)} points")
            elif scene.template == "definition":
                if line.highlight_part == "example" and scene.visual.example is None:
                    problems.append(f"{at}.highlightPart: 'example' is set, but this scene has no example")
    return problems + chapter_problems(plan)


def chapter_problems(plan: ScenePlan) -> list[str]:
    if plan.chapters is None:
        return []
    problems, chapter_ids = [], set()
    scene_ids = [scene.id for scene in plan.scenes]
    for c, chapter in enumerate(plan.chapters):
        if chapter.id in chapter_ids:
            problems.append(f"chapters[{c}].id: duplicate chapter id {chapter.id!r}")
        chapter_ids.add(chapter.id)
        problems += [f"chapters[{c}].sceneIds[{k}]: {scene_id!r} is not a scene in this plan"
                     for k, scene_id in enumerate(chapter.scene_ids) if scene_id not in scene_ids]
    listed = [scene_id for chapter in plan.chapters for scene_id in chapter.scene_ids]
    if not problems and listed != scene_ids:
        problems.append("chapters: together the chapters must list every scene exactly once, in plan order")
    return problems


def _location(loc) -> str:
    text = ""
    for i, part in enumerate(loc):
        if isinstance(part, int):
            text += f"[{part}]"
        elif part in TEMPLATES and i > 0 and isinstance(loc[i - 1], int):
            continue  # Pydantic inserts the union tag after the scene index.
        else:
            text += f".{part}" if text else str(part)
    return text or "plan"


def error_problems(exc: ValidationError) -> list[str]:
    """One problem per Pydantic error, prefixed with its JSON location."""
    return [f"{_location(e['loc'])}: {e['msg']}" for e in exc.errors()]


def validate_plan(data) -> ScenePlan:
    try:
        plan = ScenePlan.model_validate(data)
    except ValidationError as exc:
        raise PlanValidationError(error_problems(exc)) from None
    problems = semantic_problems(plan)
    if problems:
        raise PlanValidationError(problems)
    return plan


def load_plan(path: Path) -> ScenePlan:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise PlanValidationError([f"not valid JSON: {exc}"]) from None
    return validate_plan(data)


def dump_plan(plan: ScenePlan) -> str:
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def json_schema() -> dict:
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "scene-plan.schema.json", **ScenePlan.model_json_schema(by_alias=True)}


def schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


def summarize(plan: ScenePlan) -> dict:
    lines = [line for scene in plan.scenes for line in scene.narration]
    words = sum(len(text_words(line.text)) for line in lines)
    return {"scenes": len(plan.scenes), "chapters": len(plan.chapters or ()), "lines": len(lines),
            "words": words, "estimatedSpeechSeconds": round(words / WORDS_PER_SECOND, 1),
            "templates": sorted({scene.template for scene in plan.scenes})}
