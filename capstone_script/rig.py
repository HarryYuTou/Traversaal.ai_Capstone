"""Bounded, data-only geometry and articulated animation authored by the planner.

Coordinates are SVG-local units around each part's joint. These models deliberately
cannot embed markup, programs, images, URLs, event handlers or arbitrary SVG attributes.
The renderer evaluates clips from absolute frame time, keeping random-access rendering
and stable identity without calling an image or video model for individual frames.
"""

import math
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

RigId = Annotated[str, StringConstraints(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", max_length=48)]
ParentId = Annotated[str, StringConstraints(pattern=r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*)?$", max_length=48)]
Coordinate = Annotated[float, Field(allow_inf_nan=False, ge=-256, le=256)]
Dimension = Annotated[float, Field(allow_inf_nan=False, ge=0, le=512)]
Scale = Annotated[float, Field(allow_inf_nan=False, ge=0.1, le=4)]
Fraction = Annotated[float, Field(allow_inf_nan=False, ge=0, le=1)]
RigColor = Annotated[str, StringConstraints(
    pattern=r"^(?:ink|accent|secondary|muted|paper|soft|line|none|#[0-9a-fA-F]{6})$", max_length=9)]


class _RigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              alias_generator=to_camel)


class RigShape(_RigModel):
    kind: Literal["ellipse", "rect", "path"]
    x: Coordinate
    y: Coordinate
    width: Dimension
    height: Dimension
    radius: Annotated[float, Field(allow_inf_nan=False, ge=0, le=256)]
    path: Annotated[str, StringConstraints(max_length=2048)]
    fill: RigColor
    stroke: RigColor
    stroke_width: Annotated[float, Field(allow_inf_nan=False, ge=0, le=12)]


class RigPart(_RigModel):
    id: RigId
    parent_id: ParentId
    x: Coordinate
    y: Coordinate
    rotation: Annotated[float, Field(allow_inf_nan=False, ge=-3600, le=3600)]
    scale_x: Scale
    scale_y: Scale
    opacity: Fraction
    shapes: list[RigShape] = Field(max_length=8)


class RigKeyframe(_RigModel):
    at: Fraction
    value: Annotated[float, Field(allow_inf_nan=False, ge=-720, le=720)]
    easing: Literal["linear", "ease-in-out", "ease-out", "smooth"]


class RigTrack(_RigModel):
    part_id: RigId
    property: Literal["x", "y", "rotation", "scaleX", "scaleY", "opacity"]
    keyframes: list[RigKeyframe] = Field(min_length=2, max_length=16)


class RigClip(_RigModel):
    id: RigId
    tracks: list[RigTrack] = Field(min_length=1, max_length=32)


class CustomRig(_RigModel):
    id: RigId
    parts: list[RigPart] = Field(min_length=1, max_length=32)
    clips: list[RigClip] = Field(max_length=12)


class RigPerformance(_RigModel):
    entity_id: RigId
    clip_id: RigId
    start_line: Annotated[int, Field(ge=0)]
    end_line: Annotated[int, Field(ge=0)]
    start_offset: Fraction
    end_offset: Fraction
    repeat: Annotated[int, Field(ge=1, le=12)]


_PATH_TOKEN = re.compile(r"[MLQCZ]|[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?")
_PATH_ARITY = {"M": 2, "L": 2, "Q": 4, "C": 6, "Z": 0}


def path_problem(path: str) -> str | None:
    """Accept a small absolute-path grammar, never raw SVG markup or an external resource."""
    tokens, end = [], 0
    for match in _PATH_TOKEN.finditer(path):
        if path[end:match.start()].strip(" \t\r\n,"):
            return "use only absolute M, L, Q, C and Z commands with numeric coordinates"
        tokens.append(match.group())
        end = match.end()
    if path[end:].strip(" \t\r\n,") or not tokens or tokens[0] != "M":
        return "start with M and use only absolute M, L, Q, C and Z commands"
    index, commands = 0, 0
    while index < len(tokens):
        command = tokens[index]
        if command not in _PATH_ARITY:
            return "write an explicit command before each coordinate group"
        arity = _PATH_ARITY[command]
        values = tokens[index + 1:index + arity + 1]
        if len(values) != arity or any(value in _PATH_ARITY for value in values):
            return f"{command} requires exactly {arity} coordinates"
        if any(not math.isfinite(float(value)) or abs(float(value)) > 256 for value in values):
            return "all path coordinates must be finite and within -256 to 256"
        index += arity + 1
        commands += 1
    if commands > 128:
        return "use at most 128 path commands"
    return None


def rig_envelope(rig: CustomRig, performances: list[RigPerformance]) -> tuple[float, float]:
    """Conservative complete-clip bounds, matching the renderer's clipping preflight.

    Validated performances never overlap on one part/property, so its held baseline
    is the previous clip's final value. Independent channels can be bounded separately.
    Bezier control points enclose their curves; varying rotation uses a full-circle
    bound rather than sampling a few frames and missing a limb's largest excursion.
    """
    properties = ("x", "y", "rotation", "scaleX", "scaleY", "opacity")
    held = {part.id: {key: getattr(part, to_snake(key)) for key in properties} for part in rig.parts}
    ranges = {identifier: {key: (value, value) for key, value in values.items()}
              for identifier, values in held.items()}
    clips = {clip.id: clip for clip in rig.clips}
    for performance in sorted(performances, key=lambda p: (p.start_line, p.start_offset, p.clip_id)):
        for track in clips[performance.clip_id].tracks:
            initial = held[track.part_id][track.property]
            values = [initial * key.value if track.property in ("scaleX", "scaleY") else initial + key.value
                      for key in track.keyframes]
            if track.property == "opacity" and any(value < 0 or value > 1 for value in values):
                raise ValueError(f"clip {performance.clip_id!r} on part {track.part_id!r} would move "
                                 "accumulated opacity outside 0 to 1; offsets apply to the held pose")
            before = ranges[track.part_id][track.property]
            ranges[track.part_id][track.property] = (min(before[0], *values), max(before[1], *values))
            held[track.part_id][track.property] = values[-1]

    def union(boxes):
        return (min(box[0] for box in boxes), min(box[1] for box in boxes),
                max(box[2] for box in boxes), max(box[3] for box in boxes))

    def shape_bounds(shape):
        stroke = shape.stroke_width / 2 if shape.stroke != "none" else 0
        if shape.kind == "path":
            values = [float(token.group()) for token in _PATH_TOKEN.finditer(shape.path)
                      if token.group() not in _PATH_ARITY]
            box = (min(values[::2]), min(values[1::2]), max(values[::2]), max(values[1::2]))
        elif shape.kind == "ellipse":
            box = (shape.x - shape.width / 2, shape.y - shape.height / 2,
                   shape.x + shape.width / 2, shape.y + shape.height / 2)
        else:
            box = (shape.x, shape.y, shape.x + shape.width, shape.y + shape.height)
        return box[0] - stroke, box[1] - stroke, box[2] + stroke, box[3] + stroke

    def visit(part):
        boxes = [shape_bounds(shape) for shape in part.shapes]
        boxes += [visit(child) for child in rig.parts if child.parent_id == part.id]
        left, top, right, bottom = union(boxes) if boxes else (0, 0, 0, 0)
        interval = ranges[part.id]
        xs = [x * scale for x in (left, right) for scale in interval["scaleX"]]
        ys = [y * scale for y in (top, bottom) for scale in interval["scaleY"]]
        if interval["rotation"][0] != interval["rotation"][1]:
            radius = math.hypot(max(abs(x) for x in xs), max(abs(y) for y in ys))
            box = (-radius, -radius, radius, radius)
        else:
            angle = math.radians(interval["rotation"][0] % 360)
            corners = [(x * math.cos(angle) - y * math.sin(angle),
                        x * math.sin(angle) + y * math.cos(angle)) for x in xs for y in ys]
            box = (min(x for x, _ in corners), min(y for _, y in corners),
                   max(x for x, _ in corners), max(y for _, y in corners))
        return (box[0] + interval["x"][0], box[1] + interval["y"][0],
                box[2] + interval["x"][1], box[3] + interval["y"][1])

    bounds = union([visit(part) for part in rig.parts if not part.parent_id])
    return max(abs(bounds[0]), abs(bounds[2])), max(abs(bounds[1]), abs(bounds[3]))


def to_snake(key: str) -> str:
    return {"scaleX": "scale_x", "scaleY": "scale_y"}.get(key, key)


def rig_problems(visual, line_count: int, where: str) -> list[str]:
    """Validate local rig topology, clip semantics and scene-level performance references."""
    problems = []
    rigs = {}
    for index, rig in enumerate(visual.rigs or []):
        at = f"{where}.visual.rigs[{index}]"
        if rig.id in rigs:
            problems.append(f"{at}.id: duplicate rig id {rig.id!r}")
        rigs[rig.id] = rig
        parts = {}
        for part_index, part in enumerate(rig.parts):
            part_at = f"{at}.parts[{part_index}]"
            if part.id in parts:
                problems.append(f"{part_at}.id: duplicate part id {part.id!r}")
            if part.id in ("constructor", "prototype"):
                problems.append(f"{part_at}.id: reserved part id {part.id!r}")
            parts[part.id] = part
            for shape_index, shape in enumerate(part.shapes):
                shape_at = f"{part_at}.shapes[{shape_index}]"
                if shape.kind == "path":
                    problem = path_problem(shape.path)
                    if problem:
                        problems.append(f"{shape_at}.path: {problem}")
                    if any((shape.x, shape.y, shape.width, shape.height, shape.radius)):
                        problems.append(f"{shape_at}: path shapes require unused geometry fields to be zero")
                else:
                    if shape.path:
                        problems.append(f"{shape_at}.path: use an empty path for {shape.kind}")
                    if shape.width <= 0 or shape.height <= 0:
                        problems.append(f"{shape_at}: {shape.kind} width and height must be positive")
                    if shape.kind == "ellipse" and shape.radius:
                        problems.append(f"{shape_at}.radius: ellipse uses width/height; set radius to zero")
                    if shape.kind == "rect" and shape.radius > min(shape.width, shape.height) / 2:
                        problems.append(f"{shape_at}.radius: cannot exceed half the shorter rectangle side")
        if not any(part.shapes for part in rig.parts):
            problems.append(f"{at}.parts: a rig must contain visible geometry")
        for part_index, part in enumerate(rig.parts):
            part_at = f"{at}.parts[{part_index}].parentId"
            visited, current = set(), part
            while current:
                if current.id in visited:
                    problems.append(f"{part_at}: parent graph must be acyclic")
                    break
                visited.add(current.id)
                if len(visited) > 8:
                    problems.append(f"{part_at}: parent chain may contain at most eight parts")
                    break
                if current.parent_id and current.parent_id not in parts:
                    problems.append(f"{part_at}: {current.parent_id!r} is not a part in this rig")
                    break
                current = parts.get(current.parent_id)
        clips = set()
        for clip_index, clip in enumerate(rig.clips):
            clip_at = f"{at}.clips[{clip_index}]"
            if clip.id in clips:
                problems.append(f"{clip_at}.id: duplicate clip id {clip.id!r}")
            clips.add(clip.id)
            channels = set()
            for track_index, track in enumerate(clip.tracks):
                track_at = f"{clip_at}.tracks[{track_index}]"
                if track.part_id not in parts:
                    problems.append(f"{track_at}.partId: {track.part_id!r} is not a part in this rig")
                channel = (track.part_id, track.property)
                if channel in channels:
                    problems.append(f"{track_at}: duplicate part/property track")
                channels.add(channel)
                keys = track.keyframes
                if any(key.easing == "smooth" for key in keys) and not all(key.easing == "smooth" for key in keys):
                    problems.append(f"{track_at}.keyframes: smooth interpolation must be used on every key "
                                    "in a track; do not mix smooth with segment easing")
                if keys[0].at != 0 or keys[-1].at != 1:
                    problems.append(f"{track_at}.keyframes: must start at 0 and end at 1")
                if any(a.at >= b.at for a, b in zip(keys, keys[1:])):
                    problems.append(f"{track_at}.keyframes: at values must be strictly increasing")
                neutral = 1 if track.property in ("scaleX", "scaleY") else 0
                if keys[0].value != neutral:
                    problems.append(f"{track_at}.keyframes[0].value: {track.property} must begin at {neutral}")
                low, high = ((0.1, 4) if neutral else (-1, 1) if track.property == "opacity"
                             else (-720, 720) if track.property == "rotation" else (-256, 256))
                if any(not low <= key.value <= high for key in keys):
                    problems.append(f"{track_at}.keyframes: {track.property} values must be within {low} to {high}")
    entities = {entity.id: entity for entity in visual.entities}
    for index, entity in enumerate(visual.entities):
        at = f"{where}.visual.entities[{index}].rigId"
        if entity.kind == "custom":
            if entity.rig_id not in rigs:
                problems.append(f"{at}: custom entities must reference a rig in this scene")
        elif entity.rig_id is not None:
            problems.append(f"{at}: only custom entities may reference a rig")
    intervals = {}
    for index, performance in enumerate(visual.performances or []):
        at = f"{where}.visual.performances[{index}]"
        entity = entities.get(performance.entity_id)
        rig = rigs.get(entity.rig_id) if entity is not None and entity.kind == "custom" else None
        clip = next((clip for clip in rig.clips if clip.id == performance.clip_id), None) if rig else None
        if entity is None or entity.kind != "custom":
            problems.append(f"{at}.entityId: must name a custom entity in this scene")
        elif clip is None:
            problems.append(f"{at}.clipId: {performance.clip_id!r} is not a clip of this entity's rig")
        for name, line in (("startLine", performance.start_line), ("endLine", performance.end_line)):
            if line >= line_count:
                problems.append(f"{at}.{name}: {line} is outside this scene's {line_count} narration lines")
        start = (performance.start_line, performance.start_offset)
        end = (performance.end_line, performance.end_offset)
        if end <= start:
            problems.append(f"{at}: the end anchor must be after the start anchor")
        if clip is None:
            continue
        for track in clip.tracks:
            if performance.repeat > 1 and track.keyframes[0].value != track.keyframes[-1].value:
                problems.append(f"{at}.repeat: repeated clips must have matching endpoint values on every track")
            channel = (performance.entity_id, track.part_id, track.property)
            for other_start, other_end, other_index in intervals.get(channel, []):
                if start < other_end and other_start < end:
                    problems.append(f"{at}: overlaps performance {other_index} on part/property {channel[1:]!r}")
            intervals.setdefault(channel, []).append((start, end, index))
    if not problems:
        for index, entity in enumerate(visual.entities):
            if entity.kind != "custom":
                continue
            try:
                extents = rig_envelope(rigs[entity.rig_id], [p for p in visual.performances or []
                                                            if p.entity_id == entity.id])
            except ValueError as exc:
                problems.append(f"{where}.visual.entities[{index}]: {exc}")
                continue
            if any(not math.isfinite(value) or value > 800 for value in extents):
                problems.append(f"{where}.visual.entities[{index}]: derived rig motion envelope exceeds "
                                "800 local units; reduce cumulative part scale, travel or geometry")
    return problems
