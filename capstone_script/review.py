"""Script review: one Claude request scores a finished plan and rewrites weak lines.

The reviewer reads the whole plan the way the audience will hear it and returns
scores, the issues it found and replacement text for individual lines. Edits
keep every id, highlight and visual, so a reviewed plan has the same structure
as its draft and still passes the same checks. A quick local scan for symbols
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

PROMPT_VERSION = "script-reviewer-v6"
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
    _, target, _ = word_range(seconds)
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    text = (f"Review this explainer video script.\n\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n"
            f"Length: about {seconds} seconds, about {target} words of narration; "
            f"the draft has {summarize(plan)['words']} words.\n")
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


def check_review(text: str, plan, spec: dict):
    """Return ((review, reviewed plan), problems); the pair is None unless both can be used."""
    data, problems = parse_json(text)
    if problems:
        return None, problems
    try:
        review = Review.model_validate(data)
    except ValidationError as exc:
        return None, error_problems(exc)
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
    low, target, high = word_range(spec["targetDurationSec"])
    words = summarize(reviewed)["words"]
    if not low <= words <= high:
        problems.append(f"edits: the edited script has {words} words, but the video needs {low} to {high}; "
                        f"keep the total near {target}")
    return (None if problems else (review, reviewed)), problems


def review_plan_text(plan, spec: dict, client, outline: dict | None = None, reference_text: str | None = None,
                     progress=lambda message: None, attempts: list | None = None):
    """Return (review, reviewed plan, speech notes) from one request plus at most one repair."""
    attempts = [] if attempts is None else attempts
    notes = speech_notes(plan)
    review, reviewed = request_json(
        client, (PROMPTS / "script-reviewer.txt").read_text(encoding="utf-8"),
        review_request(plan, spec, notes, outline, reference_text),
        structured_schema(Review.model_json_schema(by_alias=True)),
        lambda text: check_review(text, plan, spec), "script review", attempts, "review", progress)
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
    try:
        review, reviewed, notes = review_plan_text(plan, spec, client, outline, reference_text, progress, attempts)
    except Exception as exc:
        error = str(exc) if isinstance(exc, PlannerError) else f"{type(exc).__name__}: {exc}"
        write_json(run_dir / "review.json", {**record, "status": "failed", "error": error,
                                             "estimatedCostUsd": estimated_cost(attempts), "attempts": attempts})
        raise
    before = {line.id: line.text for scene in plan.scenes for line in scene.narration}
    changes = [{"lineId": edit.line_id, "before": before[edit.line_id], "after": edit.text}
               for edit in review.edits if before[edit.line_id] != edit.text]
    write_json(run_dir / "review.json", {
        **record, "status": "completed", "scores": review.scores.model_dump(by_alias=True),
        "issues": [issue.model_dump(by_alias=True) for issue in review.issues], "changes": changes,
        "speechNotes": notes, "wordsBefore": summarize(plan)["words"], "wordsAfter": summarize(reviewed)["words"],
        "estimatedCostUsd": estimated_cost(attempts), "attempts": attempts})
    (run_dir / "scene-plan.draft.json").write_text(dump_plan(plan), encoding="utf-8", newline="\n")
    (run_dir / "scene-plan.json").write_text(dump_plan(reviewed), encoding="utf-8", newline="\n")
    return review, changes
