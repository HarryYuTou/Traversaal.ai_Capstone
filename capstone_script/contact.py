"""Narration-bound anchor contacts between independently drawn motion entities.

A contact constrains translation only: after its acquisition interval the source
anchor follows the target anchor exactly. Parts name custom-rig joints; an empty
part ID names an entity's origin. Rotation, rig articulation and scale remain authored.
"""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from .rig import Coordinate, Fraction, ParentId, RigId


class MotionContact(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True,
                              alias_generator=to_camel)

    entity_id: RigId
    part_id: ParentId
    x: Coordinate
    y: Coordinate
    target_id: RigId
    target_part_id: ParentId
    target_x: Coordinate
    target_y: Coordinate
    start_line: Annotated[int, Field(ge=0)]
    end_line: Annotated[int, Field(ge=0)]
    start_offset: Fraction
    end_offset: Fraction
    approach: Annotated[float, Field(allow_inf_nan=False, ge=0, le=0.5)]


def contact_problems(visual, line_count: int, where: str) -> list[str]:
    """Validate references and deterministic, acyclic ownership of entity translation."""
    problems = []
    entities = {entity.id: entity for entity in visual.entities}
    rigs = {rig.id: rig for rig in visual.rigs or []}
    intervals, graph = {}, {}
    for index, contact in enumerate(visual.contacts or []):
        at = f"{where}.visual.contacts[{index}]"
        for entity_key, part_key, identifier, part_id in (
            ("entityId", "partId", contact.entity_id, contact.part_id),
            ("targetId", "targetPartId", contact.target_id, contact.target_part_id),
        ):
            entity = entities.get(identifier)
            if entity is None:
                problems.append(f"{at}.{entity_key}: {identifier!r} is not an entity in this scene")
            elif part_id:
                rig = rigs.get(entity.rig_id) if entity.kind == "custom" else None
                if rig is None or part_id not in {part.id for part in rig.parts}:
                    problems.append(f"{at}.{part_key}: nonempty part IDs must name a part of this entity's custom rig")
        if contact.entity_id == contact.target_id:
            problems.append(f"{at}.targetId: an entity cannot contact itself")
        graph.setdefault(contact.entity_id, set()).add(contact.target_id)
        for name, line in (("startLine", contact.start_line), ("endLine", contact.end_line)):
            if line >= line_count:
                problems.append(f"{at}.{name}: {line} is outside this scene's {line_count} narration lines")
        start = (contact.start_line, contact.start_offset)
        end = (contact.end_line, contact.end_offset)
        if contact.approach == 0 and start != (0, 0):
            problems.append(f"{at}.approach: zero approach is allowed only for a scene-initial contact "
                            "at startLine 0 and startOffset 0; later contacts need a positive approach")
        if end <= start:
            problems.append(f"{at}: the end anchor must be after the start anchor")
            continue
        for previous_start, previous_end, previous_index in intervals.get(contact.entity_id, []):
            if start < previous_end and previous_start < end:
                problems.append(f"{at}: overlaps contact {previous_index} on source entity {contact.entity_id!r}")
        intervals.setdefault(contact.entity_id, []).append((start, end, index))
        for action_index, action in enumerate(visual.actions):
            if action.entity_id != contact.entity_id or action.kind not in ("move", "follow-path", "orbit"):
                continue
            action_start = (action.start_line, action.start_offset)
            action_end = (action.end_line, action.end_offset)
            if start < action_end and action_start < end:
                problems.append(f"{at}: source travel action {action_index} overlaps its contact; "
                                "move the target or schedule source travel after release")

    visiting, visited = set(), set()

    def cyclic(identifier):
        if identifier in visiting:
            return True
        if identifier in visited:
            return False
        visiting.add(identifier)
        if any(cyclic(target) for target in graph.get(identifier, ())):
            return True
        visiting.remove(identifier)
        visited.add(identifier)
        return False

    if any(cyclic(identifier) for identifier in graph):
        problems.append(f"{where}.visual.contacts: source-to-target graph must be acyclic across all contacts "
                        "in this scene, including contacts at different times")
    return problems
