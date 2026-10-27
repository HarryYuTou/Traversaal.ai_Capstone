"""Script review with bounded visual repair and an immutable final audit.

The reviewer reads the whole plan the way the audience will hear it and returns
scores, the issues it found and replacement text for individual lines. Text edits
keep every id and highlight. Sync findings trigger a separate visual repair and
an audit before the result replaces the draft. A quick local scan for symbols
and abbreviations the voice may misread is sent along as hints.
Reviews run before narration; a narrated run keeps the plan it was voiced from.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, ValidationError

from .planner import (
    EFFORT, MODEL, PROMPTS, PlannerError, estimated_cost, parse_json, request_json, structured_schema, word_range,
    write_json,
)
from .scene_plan import (
    Id, LineText, PlanValidationError, _Model, dump_plan, error_problems, load_plan, summarize, text_problems,
    validate_plan,
)

PROMPT_VERSION = "script-reviewer-v9"
Note = Annotated[str, StringConstraints(min_length=1, max_length=300)]
Location = Annotated[str, StringConstraints(min_length=1, max_length=60)]

SYMBOLS = re.compile(r"[%&/+=@#<>~^*_|\\$€£()\[\]{}]")
# The voice reads common acronyms (AI, DNS, HTTPS, API, SQL) correctly, but says "e.g." as "ee-jee"
# and "vs." as "viz", so abbreviations are flagged and acronyms are not.
ABBREVIATIONS = re.compile(r"\b(?:e\.g|i\.e|etc|vs|approx|incl|esp)\.", re.IGNORECASE)


class Scores(_Model):
    clarity: int
    flow: int
    accuracy: int
    engagement: int
    audience_fit: int


class Issue(_Model):
    location: Location
    category: Literal["repetition", "flow", "clarity", "accuracy", "speech", "sync"]
    severity: Literal["high", "medium", "low"]
    problem: Note


class LineEdit(_Model):
    line_id: Id
    text: LineText


class Review(_Model):
    """What the reviewer returns: scores for the draft, the issues found and line rewrites."""

    scores: Scores
    issues: list[Issue] = Field(max_length=60)
    edits: list[LineEdit] = Field(max_length=80)


def speech_notes(plan) -> list[dict]:
    """Spots the narration voice may misread: symbols and abbreviations."""
    notes = []
    for scene in plan.scenes:
        for line in scene.narration:
            found = []
            symbols = sorted(set(SYMBOLS.findall(line.text)))
            if symbols:
                found.append(f"symbols {' '.join(symbols)} are not spoken as intended; write them as words")
            for abbreviation in ABBREVIATIONS.findall(line.text):
                found.append(f"abbreviation {abbreviation!r} may be read letter by letter; write it out")
            notes += [{"lineId": line.id, "note": note} for note in found]
    return notes


def review_request(plan, spec: dict, notes: list[dict], outline: dict | None = None,
                   reference_text: str | None = None) -> str:
    seconds = spec["targetDurationSec"]
    _, target, _ = review_word_range(spec)
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    text = (f"Review this explainer video script.\n\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n"
            f"Length: about {seconds} seconds, about {target} words of narration; "
            f"the draft has {summarize(plan)['words']} words.\n")
    if "reviewWordTarget" in spec:
        text += ("Measured narration was too short, so this draft includes additional explanatory content. "
                 "Keep that content and its word budget; do not shrink it to a generic speaking-rate estimate.\n")
    if outline:
        text += "\nChapter goals:\n" + "\n".join(
            f"{n}. {chapter['title']}: {chapter['goal']}" for n, chapter in enumerate(outline["chapters"], start=1))
        text += "\n"
    text += f"\nScene plan:\n<plan>\n{json.dumps(data, ensure_ascii=False)}\n</plan>"
    if notes:
        text += "\n\nAutomatic speech check (hints, not all are problems):\n" + "\n".join(
            f"- {note['lineId']}: {note['note']}" for note in notes)
    if reference_text and reference_text.strip():
        text += f"\n\nReference material:\n<reference>\n{reference_text.strip()}\n</reference>"
    return text


def review_word_range(spec: dict):
    """A measured duration repair keeps its content budget, not the initial rate estimate."""
    if "reviewWordTarget" in spec:
        target = int(spec["reviewWordTarget"])
        if target <= 0:
            raise ValueError("reviewWordTarget must be positive")
        return round(target * 0.98), target, round(target * 1.1)
    return word_range(spec["targetDurationSec"])


def apply_edits(plan, edits) -> object:
    """Return a new plan with the edited line texts; ids, highlights and visuals stay."""
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    texts = {edit.line_id: edit.text for edit in edits}
    for scene in data["scenes"]:
        for line in scene["narration"]:
            # A line that reads a quotation keeps its words, so the spoken quote matches the one on screen.
            if not line.get("highlightQuote"):
                line["text"] = texts.get(line["id"], line["text"])
    return validate_plan(data)


def check_review(text: str, plan, spec: dict, audit_only: bool = False):
    """Return ((review, reviewed plan), problems); the pair is None unless both can be used."""
    data, problems = parse_json(text)
    if problems:
        return None, problems
    try:
        review = Review.model_validate(data)
    except ValidationError as exc:
        return None, error_problems(exc)
    if audit_only and review.edits:
        return None, ["This is a final audit: return edits: [] and assess the exact submitted plan."]
    if any(issue.category == "sync" for issue in review.issues):
        from .visual_repair import affected_scene_ids
        affected = set(affected_scene_ids(plan, review.issues))
        protected = {line.id for scene in plan.scenes if scene.id in affected for line in scene.narration}
        if any(edit.line_id in protected for edit in review.edits):
            return None, ["Keep narration in scenes with sync issues unchanged. The visual repair step "
                          "must demonstrate the original narration, not a rewritten workaround."]
    line_ids = {line.id for scene in plan.scenes for line in scene.narration}
    for criterion, score in review.scores.model_dump(by_alias=True).items():
        if not 1 <= score <= 5:
            problems.append(f"scores.{criterion}: {score} is not between 1 and 5")
    seen = set()
    for e, edit in enumerate(review.edits):
        if edit.line_id not in line_ids:
            problems.append(f"edits[{e}].lineId: {edit.line_id!r} is not a narration line in this plan")
        elif edit.line_id in seen:
            problems.append(f"edits[{e}].lineId: {edit.line_id!r} is edited twice; give one edit per line")
        seen.add(edit.line_id)
        problems += [f"edits[{e}].text: {problem}" for problem in text_problems(edit.text)]
    if problems:
        return None, problems
    try:
        reviewed = apply_edits(plan, review.edits)
    except PlanValidationError as exc:
        return None, exc.problems
    low, target, high = review_word_range(spec)
    words = summarize(reviewed)["words"]
    if not low <= words <= high:
        problems.append(f"edits: the edited script has {words} words, but the video needs {low} to {high}; "
                        f"keep the total near {target}")
    return (None if problems else (review, reviewed)), problems


def review_plan_text(plan, spec: dict, client, outline: dict | None = None, reference_text: str | None = None,
                     progress=lambda message: None, attempts: list | None = None, *, audit_only: bool = False):
    """Return (review, reviewed plan, speech notes) from one request plus at most one repair."""
    attempts = [] if attempts is None else attempts
    notes = speech_notes(plan)
    system = (PROMPTS / "script-reviewer.txt").read_text(encoding="utf-8")
    if audit_only:
        system += ("\n\nFinal visual audit: assess this exact plan after structural repairs. "
                   "Do not rewrite any narration. Return edits: [] and report all remaining issues. "
                   "Only report sync for an actual mismatch; an explicitly announced replay is intentional. "
                   "Changing an issue's category does not resolve it: unshown comparisons and unsupported "
                   "causal claims still prevent acceptance even when classified as accuracy.")
    review, reviewed = request_json(
        client, system,
        review_request(plan, spec, notes, outline, reference_text),
        structured_schema(Review.model_json_schema(by_alias=True)),
        lambda text: check_review(text, plan, spec, audit_only), "final visual audit" if audit_only else "script review",
        attempts, "visual-recheck" if audit_only else "review", progress)
    return review, reviewed, notes


def write_review(run_dir: Path, client, reference_text: str | None = None, progress=lambda message: None):
    """Review run_dir/scene-plan.json in place; the draft is kept as scene-plan.draft.json."""
    run_dir = Path(run_dir)
    if (run_dir / "audio-manifest.json").exists() or (run_dir / "audio").exists():
        raise FileExistsError(f"{run_dir} is already narrated; review a plan before narration.")
    if (run_dir / "review.json").exists():
        raise FileExistsError(f"{run_dir} already has a review.")
    plan = load_plan(run_dir / "scene-plan.json")
    spec = json.loads((run_dir / "project-spec.json").read_text(encoding="utf-8"))
    outline_path = run_dir / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8")) if outline_path.exists() else None
    record = {"promptVersion": PROMPT_VERSION, "modelRequested": MODEL, "effort": EFFORT,
              "createdAt": datetime.now(timezone.utc).isoformat()}
    attempts = []
    visual_record = {"status": "not-needed", "repairedSceneIds": [], "remainingIssues": []}
    try:
        review, reviewed, notes = review_plan_text(plan, spec, client, outline, reference_text, progress, attempts)
        final_review = review
        needs_visual_repair = any(issue.category == "sync" for issue in review.issues)
        needs_factual_audit = any(issue.category == "accuracy" and issue.severity in {"high", "medium"}
                                 for issue in review.issues)
        if needs_visual_repair:
            from .visual_repair import repair_visuals
            progress("Repairing scenes whose actions do not match the narration...")
            visual_record["status"] = "repairing"
            reviewed, repaired_ids = repair_visuals(reviewed, review.issues, spec, client, reference_text,
                                                    progress, attempts)
            visual_record["repairedSceneIds"] = repaired_ids
        if needs_visual_repair or needs_factual_audit:
            # Validate meaning again after a structural repair, not merely JSON or geometry.
            # Factual edits also need verification, even if no issue was labeled sync.
            visual_record["status"] = "auditing"
            final_review, reviewed, notes = review_plan_text(reviewed, spec, client, outline,
                                                           reference_text, progress, attempts, audit_only=True)
            remaining = [issue.model_dump(by_alias=True) for issue in final_review.issues
                         if issue.category == "sync" or
                         (issue.category == "accuracy" and issue.severity in {"high", "medium"})]
            visual_record.update(status="needs-review" if remaining else "passed", remainingIssues=remaining)
            if remaining:
                raise PlannerError("Visual repair still has narration/action mismatches or unsupported factual claims: "
                                   + "; ".join(issue["problem"] for issue in remaining), attempts)
    except Exception as exc:
        error = str(exc) if isinstance(exc, PlannerError) else f"{type(exc).__name__}: {exc}"
        write_json(run_dir / "review.json", {**record, "status": "failed", "error": error,
                                             "visualReview": visual_record,
                                             "estimatedCostUsd": estimated_cost(attempts), "attempts": attempts})
        raise
    before = {line.id: line.text for scene in plan.scenes for line in scene.narration}
    changes = [{"lineId": line.id, "before": before[line.id], "after": line.text}
               for scene in reviewed.scenes for line in scene.narration if before[line.id] != line.text]
    edited_ids = {change["lineId"] for change in changes}
    issue_resolutions = [{**issue.model_dump(by_alias=True),
                          "resolution": "repaired-and-rechecked" if issue.category == "sync"
                          and visual_record["status"] == "passed" else "line-edited" if issue.location in edited_ids
                          else "reported"} for issue in review.issues]
    write_json(run_dir / "review.json", {
        **record, "status": "completed", "scores": review.scores.model_dump(by_alias=True),
        "issues": [issue.model_dump(by_alias=True) for issue in review.issues], "changes": changes,
        "issueResolutions": issue_resolutions, "visualReview": visual_record,
        # Ordinary text edits retain the initial findings above; only an actual
        # audit can report findings about the final plan.
        "finalIssues": ([issue.model_dump(by_alias=True) for issue in final_review.issues]
                        if needs_visual_repair or needs_factual_audit else None),
        "speechNotes": notes, "wordsBefore": summarize(plan)["words"], "wordsAfter": summarize(reviewed)["words"],
        "estimatedCostUsd": estimated_cost(attempts), "attempts": attempts})
    (run_dir / "scene-plan.draft.json").write_text(dump_plan(plan), encoding="utf-8", newline="\n")
    (run_dir / "scene-plan.json").write_text(dump_plan(reviewed), encoding="utf-8", newline="\n")
    return review, changes
