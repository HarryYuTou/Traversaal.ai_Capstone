"""Bounded, atomic narration-and-visual revisions after an immutable audit.

Visual-only repair cannot resolve a claim that was incorrect in the first place.
This fallback can correct narration, but preserves scene structure, identity and
the requested duration budget. Its candidate still requires an independent audit.
"""

import json

from .planner import (MAX_REQUEST_TEMPLATES, PlannerError, coverage_problems, from_model_output,
                      output_schema, parse_json, planner_prompt, request_json)
from .scene_plan import PlanValidationError, summarize, validate_plan
from .visual_repair import repair_invariant_problems


def revision_scene_ids(plan, issues):
    """Resolve blocking findings in plan order; unknown locations affect the whole plan."""
    affected = set()
    for issue in issues:
        if not (issue.category == "sync" or issue.category == "accuracy" and issue.severity in ("medium", "high")):
            continue
        matches = {scene.id for scene in plan.scenes
                   if issue.location == scene.id or any(line.id == issue.location for line in scene.narration)}
        affected.update(matches or {scene.id for scene in plan.scenes})
    return [scene.id for scene in plan.scenes if scene.id in affected]


def check_scene_revision(text, plan, scene_ids, spec):
    """Validate all requested replacements together, without mutating the source plan."""
    from .review import review_word_range

    if not scene_ids or list(scene_ids) != [scene.id for scene in plan.scenes if scene.id in scene_ids]:
        return None, ["Requested scene ids must be a nonempty, unique subset in original plan order."]
    data, problems = parse_json(text)
    if problems:
        return None, problems
    data, problems = from_model_output(data)
    replacements = data.get("scenes") if isinstance(data, dict) else None
    if not isinstance(replacements, list) or any(not isinstance(scene, dict) for scene in replacements):
        return None, problems + ["Return the requested scenes as scene objects."]
    if [scene.get("id") for scene in replacements] != list(scene_ids):
        return None, problems + ["Return exactly the requested scene ids, in their original order, once each: "
                                 + ", ".join(scene_ids)]
    if problems:
        return None, problems
    replacement_by_id = {scene["id"]: scene for scene in replacements}
    full = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    full["scenes"] = [replacement_by_id.get(scene["id"], scene) for scene in full["scenes"]]
    try:
        candidate = validate_plan(full)
    except PlanValidationError as exc:
        return None, exc.problems
    for index, (source, revised) in enumerate(zip(plan.scenes, candidate.scenes)):
        if source.id in replacement_by_id:
            problems += [f"{source.id}: {problem}" for problem in repair_invariant_problems(
                source, revised, plan.scenes[index - 1] if index else None, allow_narration_edits=True)]
    problems += coverage_problems(candidate)
    low, target, high = review_word_range(spec)
    words = summarize(candidate)["words"]
    if not low <= words <= high:
        problems.append(f"The revised script has {words} words, but the video needs {low} to {high}; "
                        f"keep the total near {target}.")
    return (None if problems else candidate), problems


def revise_scenes(plan, issues, spec, client, reference_text=None, progress=lambda message: None,
                  attempts=None, *, round_number=1):
    """One joint revision request plus the request helper's single validation retry."""
    from .review import review_word_range

    attempts = [] if attempts is None else attempts
    scene_ids = revision_scene_ids(plan, issues)
    if not scene_ids:
        return plan, []
    templates = list(dict.fromkeys(scene.template for scene in plan.scenes if scene.id in scene_ids))
    if len(templates) > MAX_REQUEST_TEMPLATES:
        raise PlannerError(f"Scene revision needs {len(templates)} template types; the bounded request supports "
                           f"at most {MAX_REQUEST_TEMPLATES}.", attempts)
    low, target, high = review_word_range(spec)
    system = planner_prompt(templates) + (
        "\n\nAudited scene revision\n"
        "A prior immutable audit found the problems listed below. Revise the requested scenes together, "
        "using the full plan to keep comparisons and cause and effect consistent. Return exactly the requested "
        "scene ids in their original order, with the same templates. Keep narration line ids, order, count and "
        "highlights unchanged, but correct the narration text when a claim is inaccurate or cannot be shown. "
        "Keep quoted words and their attribution unchanged. Respect all ordinary narration text limits. "
        "Preserve the user's topic, explanatory mechanism and supported facts. Correct unsupported claims "
        "or show the evidence for them; do not erase the explanation, replace it with generic platitudes, "
        "or make an opening into a static already-open state to evade the mismatch. Preserve every existing "
        "object's id, kind and identity color. The only exceptions are restoring the immediately preceding "
        "scene's color for the same object id, or restoring a process station's previous id when its unique "
        "label and kind identify the same station; update all references consistently. A closed baseline "
        "station can use initialState: closed without an open event. A narrated opening needs a visible "
        "open event during its clause and a readable OPEN result hold. For comparisons, explicitly identify "
        "any replay and keep participants, service times and other assumptions consistent across conditions. "
        "Use actual visible actions to demonstrate the causal claim. Do not invent statistics. "
        "This candidate will receive another independent audit; do not mark it as approved."
    )
    request = (f"Topic: {spec['topic']}\nAudience: {spec['audience']}\nRevision round: {round_number}\n"
               f"Requested scene ids: {json.dumps(scene_ids)}\n"
               f"Total plan narration budget: {low} to {high} words, near {target}.\n"
               f"Previous audit findings: {json.dumps([issue.model_dump(by_alias=True) for issue in issues])}\n"
               "Full plan context:\n<plan>\n"
               f"{json.dumps(plan.model_dump(mode='json', by_alias=True, exclude_none=True))}\n</plan>")
    if reference_text:
        request += f"\nReference material:\n<reference>\n{reference_text}\n</reference>"
    candidate = request_json(client, system, request, output_schema(templates),
                             lambda text: check_scene_revision(text, plan, scene_ids, spec),
                             "scene revision", attempts, f"scene-revision-{round_number}", progress)
    return candidate, scene_ids
