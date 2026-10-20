"""ScenePlan: the scene-by-scene script that the planner writes.

A plan says what each scene shows (a motion explanation or a slide template) and what the
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
TEMPLATES = ("concept", "flow", "comparison", "definition", "timeline", "stat", "quote", "map", "motion", "process")
MAX_SCENES = 60
MAX_CHAPTERS = 10
MAX_LINES_PER_SCENE = 8
MAX_LINE_WORDS = 25
# Measured with capstone_tts at speed 1.0, one line at a time: the 214-word fixture
# took 81.0 s (2.64 words/s). Whole paragraphs read faster, about 2.9 words/s.
WORDS_PER_SECOND = 2.6

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
# Icon names from Lucide (ISC license) that renderers can draw; see schemas/icons.json.
ICONS = tuple(json.loads((SCHEMAS / "icons.json").read_text(encoding="utf-8")))
# Map regions with their bounds; the renderer reads the same file to frame each map.
MAP_REGIONS = json.loads((SCHEMAS / "map-regions.json").read_text(encoding="utf-8"))

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
DateText = Annotated[str, StringConstraints(min_length=1, max_length=20)]
EventLabel = Annotated[str, StringConstraints(min_length=1, max_length=48)]
Affix = Annotated[str, StringConstraints(min_length=1, max_length=12)]
QuoteText = Annotated[str, StringConstraints(min_length=1, max_length=220)]
Attribution = Annotated[str, StringConstraints(min_length=1, max_length=60)]
QuoteContext = Annotated[str, StringConstraints(min_length=1, max_length=80)]
Country = Annotated[str, StringConstraints(min_length=1, max_length=48)]
Number = Annotated[float, Field(allow_inf_nan=False, ge=-1e12, le=1e12)]
Finite = Annotated[float, Field(allow_inf_nan=False)]
StagePosition = Annotated[float, Field(allow_inf_nan=False, ge=0, le=100)]
Fraction = Annotated[float, Field(allow_inf_nan=False, ge=0, le=1)]
MotionSize = Annotated[float, Field(allow_inf_nan=False, ge=0.25, le=3)]
MotionColor = Literal["ink", "accent", "secondary", "muted"]
MotionKind = Literal["planet", "moon", "spacecraft", "lander", "lander-base", "lander-ascent", "rocket", "satellite", "person", "packet",
                     "server", "laptop", "cloud", "coin", "box", "marker", "gauge", "counter", "workbench"]
ActionKind = Literal["move", "follow-path", "orbit", "opacity", "scale", "rotate", "value"]
MotionEasing = Literal["linear", "ease-in-out", "ease-out"]


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


class TimelineLine(_Model):
    id: Id
    text: LineText
    highlight_event_id: Id | None = None


class StatLine(_Model):
    id: Id
    text: LineText
    highlight_stat_index: Annotated[int, Field(ge=0)] | None = None


class QuoteLine(_Model):
    id: Id
    text: LineText
    # True on the line that reads the quotation aloud; the quote appears word by word as it is spoken.
    highlight_quote: bool | None = None


class MapLine(_Model):
    id: Id
    text: LineText
    # The id of a place or an area on this scene's map.
    highlight_id: Id | None = None


class MotionLine(_Model):
    id: Id
    text: LineText


class FlowNode(_Model):
    id: Id
    label: Label
    icon: Id | None = None


class ConceptVisual(_Model):
    title: Title
    statement: Statement
    points: list[Point] = Field(default_factory=list, max_length=3)
    icon: Id | None = None


class FlowVisual(_Model):
    title: Title
    nodes: list[FlowNode] = Field(min_length=2, max_length=4)


class ComparisonColumn(_Model):
    label: Label
    points: list[ColumnPoint] = Field(min_length=1, max_length=3)
    icon: Id | None = None


class ComparisonVisual(_Model):
    title: Title
    left: ComparisonColumn
    right: ComparisonColumn


class DefinitionVisual(_Model):
    title: Title
    term: Term
    definition: Definition
    example: Example | None = None
    icon: Id | None = None


class TimelineEvent(_Model):
    id: Id
    date: DateText
    label: EventLabel
    icon: Id | None = None


class TimelineVisual(_Model):
    title: Title
    events: list[TimelineEvent] = Field(min_length=2, max_length=5)


class Stat(_Model):
    value: Number
    # Shown before and after the number, as in "$" 4 "billion" or 75 "%".
    prefix: Affix | None = None
    unit: Affix | None = None
    label: Point
    icon: Id | None = None


class StatVisual(_Model):
    title: Title
    stats: list[Stat] = Field(min_length=1, max_length=3)
    note: Statement | None = None


class QuoteVisual(_Model):
    title: Title
    quote: QuoteText
    author: Attribution
    context: QuoteContext | None = None


class MapArea(_Model):
    """Countries grouped together, such as the Allies or the Axis, named with today's borders."""

    id: Id
    label: Label
    countries: list[Country] = Field(min_length=1, max_length=40)


class MapPlace(_Model):
    id: Id
    label: Label
    lon: Annotated[float, Field(ge=-180, le=180)]
    lat: Annotated[float, Field(ge=-80, le=84)]


class MapVisual(_Model):
    title: Title
    region: Annotated[str, StringConstraints(pattern=r"^[a-z]+(?:-[a-z]+)*$", max_length=24)]
    areas: list[MapArea] = Field(default_factory=list, max_length=3)
    places: list[MapPlace] = Field(default_factory=list, max_length=8)
    # Draw a line through the places in order, each leg as the narration reaches the next place.
    route: bool = False


class MotionEntity(_Model):
    """Initial state on a stage measured in percentages, independent of output resolution."""

    id: Id
    kind: MotionKind
    x: StagePosition
    y: StagePosition
    size: MotionSize
    rotation: Finite
    opacity: Fraction
    value: Fraction
    color: MotionColor
    label: Annotated[str, StringConstraints(max_length=32)]


class MotionPoint(_Model):
    x: StagePosition
    y: StagePosition


class MotionPath(_Model):
    id: Id
    points: list[MotionPoint] = Field(min_length=2, max_length=24)
    curved: bool
    closed: bool
    color: MotionColor


class MotionAction(_Model):
    """Animate one property between fractional positions in narration lines, before audio exists.

    The end line is included: endOffset=1 reaches its audio endpoint. Timeline compilation
    produces the absolute frame interval [from, from + durationInFrames).
    """

    entity_id: Id
    kind: ActionKind
    start_line: Annotated[int, Field(ge=0)]
    end_line: Annotated[int, Field(ge=0)]
    start_offset: Fraction
    end_offset: Fraction
    path_id: Annotated[str, StringConstraints(pattern=r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*)?$", max_length=48)]
    x: StagePosition
    y: StagePosition
    value: Finite
    easing: MotionEasing


class MotionVisual(_Model):
    title: Title
    entities: list[MotionEntity] = Field(min_length=1, max_length=12)
    paths: list[MotionPath] = Field(max_length=12)
    actions: list[MotionAction] = Field(max_length=48)


class ProcessActor(_Model):
    id: Id
    color: MotionColor
    label: Annotated[str, StringConstraints(max_length=24)]


class ProcessStation(_Model):
    id: Id
    label: Label
    kind: Literal["counter", "server", "workbench"]
    color: MotionColor


class ProcessOccupancy(_Model):
    actor_id: Id
    station_id: Id


class ProcessEvent(_Model):
    """A causal state change or deliberate hold, before layout and measured speech timing."""

    kind: Literal["arrive", "start", "finish", "hold"]
    actor_ids: list[Id] = Field(max_length=8)
    station_ids: list[Id] = Field(max_length=2)
    start_line: Annotated[int, Field(ge=0)]
    end_line: Annotated[int, Field(ge=0)]
    start_offset: Fraction
    end_offset: Fraction


class ProcessVisual(_Model):
    title: Title
    actor_kind: Literal["person", "packet", "box", "coin"]
    actors: list[ProcessActor] = Field(min_length=1, max_length=8)
    stations: list[ProcessStation] = Field(min_length=1, max_length=2)
    initial_queue: list[Id] = Field(max_length=8)
    initial_service: list[ProcessOccupancy] = Field(max_length=2)
    events: list[ProcessEvent] = Field(max_length=48)


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


class TimelineScene(_Model):
    """A title and two to five dated events along a line, in time order."""

    id: Id
    purpose: Purpose
    template: Literal["timeline"]
    visual: TimelineVisual
    narration: list[TimelineLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class StatScene(_Model):
    """A title and one to three large numbers that count up, each with a short label."""

    id: Id
    purpose: Purpose
    template: Literal["stat"]
    visual: StatVisual
    narration: list[StatLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class QuoteScene(_Model):
    """A title and one short quotation with who said it."""

    id: Id
    purpose: Purpose
    template: Literal["quote"]
    visual: QuoteVisual
    narration: list[QuoteLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class MapScene(_Model):
    """A map of one region with shaded country groups, labelled places and an optional route."""

    id: Id
    purpose: Purpose
    template: Literal["map"]
    visual: MapVisual
    narration: list[MapLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class MotionScene(_Model):
    """Entities whose movement and property changes explain the narrated process."""

    id: Id
    purpose: Purpose
    template: Literal["motion"]
    visual: MotionVisual
    narration: list[MotionLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


class ProcessScene(_Model):
    """A bounded arrival, waiting and processing workflow with explicit state transitions."""

    id: Id
    purpose: Purpose
    template: Literal["process"]
    visual: ProcessVisual
    narration: list[MotionLine] = Field(min_length=1, max_length=MAX_LINES_PER_SCENE)


Scene = Annotated[Union[ConceptScene, FlowScene, ComparisonScene, DefinitionScene,
                        TimelineScene, StatScene, QuoteScene, MapScene, MotionScene, ProcessScene],
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
        elif scene.template == "timeline":
            event_ids = [event.id for event in scene.visual.events]
            for n, event_id in enumerate(event_ids):
                if event_id in event_ids[:n]:
                    problems.append(f"{where}.visual.events[{n}].id: duplicate event id {event_id!r}")
        elif scene.template == "map":
            map_ids = [area.id for area in scene.visual.areas] + [place.id for place in scene.visual.places]
            problems += map_problems(scene.visual, where)
        elif scene.template == "motion":
            problems += motion_problems(scene.visual, len(scene.narration), where)
        elif scene.template == "process":
            problems += process_problems(scene.visual, len(scene.narration), where)
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
            elif scene.template == "timeline":
                if line.highlight_event_id is not None and line.highlight_event_id not in event_ids:
                    problems.append(f"{at}.highlightEventId: {line.highlight_event_id!r} "
                                    "is not an event in this scene")
            elif scene.template == "stat":
                if (line.highlight_stat_index is not None
                        and line.highlight_stat_index >= len(scene.visual.stats)):
                    problems.append(f"{at}.highlightStatIndex: {line.highlight_stat_index} is out of range; "
                                    f"this scene has {len(scene.visual.stats)} numbers")
            elif scene.template == "map":
                if line.highlight_id is not None and line.highlight_id not in map_ids:
                    problems.append(f"{at}.highlightId: {line.highlight_id!r} "
                                    "is not a place or area on this map")
    return problems + icon_problems(plan) + chapter_problems(plan)


def map_problems(visual: MapVisual, where: str) -> list[str]:
    problems = []
    if visual.region not in MAP_REGIONS:
        problems.append(f"{where}.visual.region: {visual.region!r} is not a map region; "
                        f"use one of {', '.join(MAP_REGIONS)}")
    if not visual.areas and not visual.places:
        problems.append(f"{where}.visual: a map needs at least one area or place")
    ids = [area.id for area in visual.areas] + [place.id for place in visual.places]
    problems += [f"{where}.visual: duplicate area or place id {item!r}"
                 for n, item in enumerate(ids) if item in ids[:n]]
    shaded = set()
    for a, area in enumerate(visual.areas):
        for c, country in enumerate(area.countries):
            if country in shaded:
                problems.append(f"{where}.visual.areas[{a}].countries[{c}]: {country!r} is already in another area")
            shaded.add(country)
    if visual.route and len(visual.places) < 2:
        problems.append(f"{where}.visual.route: a route needs at least two places")
    return problems


def motion_channel(kind: str) -> str:
    """Only one action may drive a given entity property at a time."""
    return "position" if kind in ("move", "follow-path", "orbit") else kind


def process_problems(visual: ProcessVisual, line_count: int, where: str) -> list[str]:
    """Validate workflow state as well as references; geometry belongs to the compiler."""
    problems = []
    prefix = f"{where}.visual"
    actors = {actor.id for actor in visual.actors}
    stations = {station.id for station in visual.stations}
    for key in ("actors", "stations"):
        ids = [item.id for item in getattr(visual, key)]
        problems += [f"{prefix}.{key}[{index}].id: duplicate id {item!r}"
                     for index, item in enumerate(ids) if item in ids[:index]]
    if actors & stations:
        problems.append(f"{prefix}: actor and station ids must be distinct")
    queue = list(visual.initial_queue)
    if len(set(queue)) != len(queue):
        problems.append(f"{prefix}.initialQueue: an actor cannot occupy two queue positions")
    if any(item not in actors for item in queue):
        problems.append(f"{prefix}.initialQueue: every id must name an actor in this scene")
    occupied, seen = {}, set(queue)
    for index, item in enumerate(visual.initial_service):
        at = f"{prefix}.initialService[{index}]"
        if item.actor_id not in actors:
            problems.append(f"{at}.actorId: {item.actor_id!r} is not an actor in this scene")
        if item.station_id not in stations:
            problems.append(f"{at}.stationId: {item.station_id!r} is not a station in this scene")
        if item.actor_id in seen:
            problems.append(f"{at}.actorId: {item.actor_id!r} already occupies a queue or service position")
        if item.station_id in occupied:
            problems.append(f"{at}.stationId: {item.station_id!r} is already occupied")
        occupied[item.station_id] = item.actor_id
        seen.add(item.actor_id)
    previous_end = None
    for index, event in enumerate(visual.events):
        at = f"{prefix}.events[{index}]"
        before = len(problems)
        start, end = (event.start_line, event.start_offset), (event.end_line, event.end_offset)
        for name, anchor in (("startLine", event.start_line), ("endLine", event.end_line)):
            if anchor >= line_count:
                problems.append(f"{at}.{name}: {anchor} is outside this scene's {line_count} narration lines")
        if end <= start:
            problems.append(f"{at}: the end anchor must be after the start anchor")
        if previous_end is not None and start < previous_end:
            problems.append(f"{at}: events must be chronological and must not overlap; "
                            "put simultaneous actors in the same event")
        previous_end = max(previous_end or end, end)
        for key, values, known in (("actorIds", event.actor_ids, actors),
                                    ("stationIds", event.station_ids, stations)):
            if len(set(values)) != len(values):
                problems.append(f"{at}.{key}: ids must not repeat within an event")
            if any(value not in known for value in values):
                problems.append(f"{at}.{key}: every id must reference this scene's "
                                + ("actors" if key == "actorIds" else "stations"))
        if event.kind == "hold":
            if event.actor_ids or event.station_ids:
                problems.append(f"{at}: hold requires empty actorIds and stationIds")
        elif not event.actor_ids:
            problems.append(f"{at}.actorIds: {event.kind} needs at least one actor")
        if event.kind == "arrive":
            if event.station_ids:
                problems.append(f"{at}.stationIds: arrive requires an empty list")
            if any(actor in seen for actor in event.actor_ids):
                problems.append(f"{at}.actorIds: arrivals must be new actors; a visible or departed actor cannot arrive again")
        elif event.kind in ("start", "finish"):
            if len(event.actor_ids) != len(event.station_ids):
                problems.append(f"{at}: pair each actor with exactly one station")
            if event.kind == "start":
                if event.actor_ids != queue[:len(event.actor_ids)]:
                    problems.append(f"{at}.actorIds: start must take the next actors from the front of the queue, in order")
                if any(station in occupied for station in event.station_ids):
                    problems.append(f"{at}.stationIds: start requires free stations")
            elif any(occupied.get(station) != actor
                     for actor, station in zip(event.actor_ids, event.station_ids)):
                problems.append(f"{at}: finish must pair each actor with the station currently serving that actor")
        if len(problems) != before:
            continue
        if event.kind == "arrive":
            queue.extend(event.actor_ids)
            seen.update(event.actor_ids)
        elif event.kind == "start":
            del queue[:len(event.actor_ids)]
            occupied.update(zip(event.station_ids, event.actor_ids))
        elif event.kind == "finish":
            for station in event.station_ids:
                del occupied[station]
    return problems


def motion_problems(visual: MotionVisual, line_count: int, where: str) -> list[str]:
    problems = []
    for key in ("entities", "paths"):
        ids = [item.id for item in getattr(visual, key)]
        problems += [f"{where}.visual.{key}[{index}].id: duplicate id {item!r}"
                     for index, item in enumerate(ids) if item in ids[:index]]
    entity_ids = {entity.id for entity in visual.entities}
    path_ids = {path.id for path in visual.paths}
    intervals = {}
    for index, action in enumerate(visual.actions):
        at = f"{where}.visual.actions[{index}]"
        if action.entity_id not in entity_ids:
            problems.append(f"{at}.entityId: {action.entity_id!r} is not an entity in this scene")
        if action.kind == "follow-path":
            if action.path_id not in path_ids:
                problems.append(f"{at}.pathId: {action.path_id!r} is not a path in this scene")
        elif action.path_id:
            problems.append(f'{at}.pathId: use "" unless kind is "follow-path"')
        if action.kind in ("opacity", "value") and not 0 <= action.value <= 1:
            problems.append(f"{at}.value: {action.kind} target must be between 0 and 1")
        elif action.kind == "scale" and not 0.25 <= action.value <= 3:
            problems.append(f"{at}.value: scale target must be between 0.25 and 3")
        for name, line_index in (("startLine", action.start_line), ("endLine", action.end_line)):
            if line_index >= line_count:
                problems.append(f"{at}.{name}: {line_index} is outside this scene's {line_count} narration lines")
        start = (action.start_line, action.start_offset)
        end = (action.end_line, action.end_offset)
        if end <= start:
            problems.append(f"{at}: the end anchor must be after the start anchor")
            continue
        channel = (action.entity_id, motion_channel(action.kind))
        for other_start, other_end, other_index in intervals.get(channel, []):
            if start < other_end and other_start < end:
                problems.append(f"{at}: overlaps action {other_index} on entity {action.entity_id!r} "
                                f"channel {channel[1]!r}")
        intervals.setdefault(channel, []).append((start, end, index))
    return problems


def scene_icons(scene) -> list[tuple[str, str | None]]:
    """Every (location, icon) pair of a scene's visual, including unset icons."""
    visual = scene.visual
    if scene.template == "flow":
        return [(f"visual.nodes[{n}].icon", node.icon) for n, node in enumerate(visual.nodes)]
    if scene.template == "comparison":
        return [(f"visual.{side}.icon", getattr(visual, side).icon) for side in ("left", "right")]
    if scene.template == "timeline":
        return [(f"visual.events[{n}].icon", event.icon) for n, event in enumerate(visual.events)]
    if scene.template == "stat":
        return [(f"visual.stats[{n}].icon", stat.icon) for n, stat in enumerate(visual.stats)]
    if scene.template in ("quote", "map", "motion", "process"):
        return []
    return [("visual.icon", visual.icon)]


def icon_problems(plan: ScenePlan) -> list[str]:
    return [f"scenes[{s}].{where}: {icon!r} is not an available icon; see schemas/icons.json"
            for s, scene in enumerate(plan.scenes) for where, icon in scene_icons(scene)
            if icon is not None and icon not in ICONS]


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
