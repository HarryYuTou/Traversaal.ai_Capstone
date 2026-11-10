"""Bounded repair of scenes whose narration and visible events disagree.

The existing plan remains authoritative. Repairs cannot rewrite narration,
rename continuing objects, or silently change their identity to justify a claim.
Every replacement passes the ordinary full-plan and event-coverage validators.
"""

import json
from collections import Counter

from .planner import coverage_problems, from_model_output, output_schema, parse_json, planner_prompt, request_json
from .scene_plan import PlanValidationError, validate_plan


def affected_scene_ids(plan, issues):
    """Resolve scene/line locations; a plan-wide issue may affect any template."""
    result = []
    for issue in issues:
        if issue.category != "sync":
            continue
        matches = [scene.id for scene in plan.scenes
                   if issue.location == scene.id or any(line.id == issue.location for line in scene.narration)]
        if not matches:
            matches = [scene.id for scene in plan.scenes]
        for scene_id in matches:
            if scene_id not in result:
                result.append(scene_id)
    return result


def _identities(scene):
    if scene.template == "process":
        return {**{actor.id: (scene.visual.actor_kind, actor.color) for actor in scene.visual.actors},
                **{station.id: (station.kind, station.color) for station in scene.visual.stations}}
    if scene.template == "motion":
        return {entity.id: (entity.kind, entity.color) for entity in scene.visual.entities}
    return {}


def _rig_identity(scene, entity):
    """A repair may change acting, but cannot quietly redraw a continuing character."""
    rig = next((rig for rig in scene.visual.rigs or () if rig.id == entity.rig_id), None)
    if rig is None:
        return None
    return (entity.rig_id, [(part.id, part.parent_id,
                            [shape.model_dump(mode="json", by_alias=True) for shape in part.shapes])
                           for part in rig.parts])


def repair_invariant_problems(source, repaired, previous_scene=None, *, allow_narration_edits=False):
    """Shared scene/identity limits for visual repairs and audited scene revisions."""
    problems = []
    for field in ("id", "template"):
        if getattr(repaired, field) != getattr(source, field):
            problems.append(f"Keep the original scene {field} unchanged.")
    if not allow_narration_edits:
        if repaired.narration != source.narration:
            problems.append("Keep the original scene narration unchanged; repair only its visual and purpose.")
    else:
        original_lines = [line.model_dump(by_alias=True, exclude_none=True) for line in source.narration]
        revised_lines = [line.model_dump(by_alias=True, exclude_none=True) for line in repaired.narration]
        if ([{key: value for key, value in line.items() if key != "text"} for line in original_lines]
                != [{key: value for key, value in line.items() if key != "text"} for line in revised_lines]):
            problems.append("Keep narration line ids, order, count and highlights unchanged.")
        revised_texts = {line.id: line.text for line in repaired.narration}
        for line in original_lines:
            if line.get("highlightQuote") and revised_texts.get(line["id"]) != line["text"]:
                problems.append(f"Keep quoted narration words unchanged for {line['id']!r}.")
        if source.template == "quote" and repaired.template == "quote":
            if source.visual.quote != repaired.visual.quote or source.visual.author != repaired.visual.author:
                problems.append("Keep quotation words and attribution unchanged.")
    if source.template != repaired.template:
        return problems
    identities = _identities(repaired)
    previous = _identities(previous_scene) if previous_scene is not None else {}
    station_aliases = {}
    if source.template == "process" and previous_scene is not None and previous_scene.template == "process":
        for station in source.visual.stations:
            matches = [old for old in previous_scene.visual.stations
                       if old.label == station.label and old.kind == station.kind]
            if len(matches) == 1 and matches[0].id != station.id:
                station_aliases[station.id] = matches[0].id
    for entity_id, identity in _identities(source).items():
        allowed = {identity}
        # A continuing object's established color can repair accidental identity drift.
        # Never infer identity from a similar label or recolor unrelated/new objects.
        if entity_id in previous and previous[entity_id][0] == identity[0]:
            allowed.add(previous[entity_id])
        alias = station_aliases.get(entity_id)
        restored_alias = alias and entity_id not in identities and identities.get(alias) == previous[alias]
        if identities.get(entity_id) not in allowed and not restored_alias:
            problems.append(f"Preserve object {entity_id!r}, its kind and its identity color.")
    if source.template == "motion":
        relation = lambda contact: (contact.entity_id, contact.part_id, contact.target_id, contact.target_part_id)
        before = Counter(relation(contact) for contact in source.visual.contacts or ())
        after = Counter(relation(contact) for contact in repaired.visual.contacts or ())
        if before - after:
            problems.append("Preserve authored contact relationships and their source/target parts; "
                            "repair anchor coordinates and timing without dropping the physical relationship.")
        revised_entities = {entity.id: entity for entity in repaired.visual.entities}
        for entity in source.visual.entities:
            revised = revised_entities.get(entity.id)
            if entity.kind == "custom" and revised is not None and revised.kind == "custom":
                if _rig_identity(source, entity) != _rig_identity(repaired, revised):
                    problems.append(f"Preserve custom object {entity.id!r}, its rigId, part hierarchy and shapes; "
                                    "repair its poses, clips or timing without changing its identity.")
    return problems


def check_visual_repair(text, plan, scene_id, *, allow_narration_edits=False):
    data, problems = parse_json(text)
    if problems:
        return None, problems
    data, problems = from_model_output(data)
    if not isinstance(data, dict) or not isinstance(data.get("scenes"), list) or len(data["scenes"]) != 1:
        return None, problems + ["Return exactly one repaired scene."]
    replacement = data["scenes"][0]
    source = next(scene for scene in plan.scenes if scene.id == scene_id)
    original = source.model_dump(mode="json", by_alias=True, exclude_none=True)
    if not isinstance(replacement, dict):
        return None, ["The repaired scene must be an object."]
    protected_fields = ("id", "template") if allow_narration_edits else ("id", "template", "narration")
    for field in protected_fields:
        if replacement.get(field) != original[field]:
            problems.append(f"Keep the original scene {field} unchanged; repair only its visual and purpose.")
    if problems:
        return None, problems
    full = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    full["scenes"] = [replacement if scene["id"] == scene_id else scene for scene in full["scenes"]]
    try:
        candidate = validate_plan(full)
    except PlanValidationError as exc:
        return None, exc.problems
    repaired = next(scene for scene in candidate.scenes if scene.id == scene_id)
    index = next(index for index, scene in enumerate(plan.scenes) if scene.id == scene_id)
    previous_scene = plan.scenes[index - 1] if index else None
    problems += repair_invariant_problems(source, repaired, previous_scene,
                                         allow_narration_edits=allow_narration_edits)
    problems += coverage_problems(candidate)
    return (None if problems else candidate), problems


def repair_visuals(plan, issues, spec, client, reference_text=None, progress=lambda message: None, attempts=None):
    """One repair per affected scene, with the request helper's single schema retry."""
    attempts = [] if attempts is None else attempts
    scene_ids = affected_scene_ids(plan, issues)
    for scene_id in scene_ids:
        index = next(index for index, scene in enumerate(plan.scenes) if scene.id == scene_id)
        scene = plan.scenes[index]
        nearby = plan.scenes[max(0, index - 1):index + 2]
        system = planner_prompt([scene.template]) + (
            "\n\nVisual repair\n"
            "Return exactly the one requested scene using the planner output shape. Preserve its id, template, "
            "all narration ids and words, and all existing object kinds. Preserve object ids, except restoring "
            "a continuing process station's previous id when its unique label and kind identify the same station. "
            "Update every station reference consistently. Preserve identity colors, except restoring "
            "the immediately preceding scene's established color for the same object id. "
            "For custom objects, preserve rigId, ordered part ids, parentId hierarchy and shape geometry/colors; "
            "change part poses, clips and performances to repair the action. Preserve existing contact "
            "relationships and source/target parts; you may repair their anchor coordinates and timing. Narration highlights "
            "must also stay unchanged (use the normal planner highlight field). Repair only the visual and "
            "purpose so its actual events demonstrate the narration. Do not invent statistics or change "
            "the story to disguise a mismatch. Preserve a continuing scene's established state and identity. "
            "A process station can use initialState: closed and stay closed for the entire scene without "
            "an open event. Use that state for an inactive counter in a baseline; preserve its identity "
            "instead of deleting it or inventing an unspoken opening to force it initially closed. "
            "If an opening is described, author an open event during its spoken clause, followed by "
            "a readable OPEN result hold before a cut or replay explanation; if a comparison is described, demonstrate "
            "both conditions with the same assumptions. Scene count and narration count cannot change."
        )
        request = (f"Topic: {spec['topic']}\nAudience: {spec['audience']}\nRepair scene: {scene_id}\n"
                   f"Issues: {json.dumps([issue.model_dump(by_alias=True) for issue in issues if issue.category == 'sync'])}\n"
                   f"Scene and neighboring context: {json.dumps([item.model_dump(mode='json', by_alias=True, exclude_none=True) for item in nearby])}")
        if reference_text:
            request += f"\nReference material:\n<reference>\n{reference_text}\n</reference>"
        plan = request_json(client, system, request, output_schema([scene.template]),
                            lambda text: check_visual_repair(text, plan, scene_id), "visual repair", attempts,
                            f"visual-repair-{scene_id}", progress)
    return plan, scene_ids
