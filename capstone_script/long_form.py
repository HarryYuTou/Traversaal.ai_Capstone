"""Long videos: plan the chapters first, then write each chapter's scenes.

One request returns an outline: the chapters' titles, goals, key points and
lengths. Each chapter is then planned like a short video, in order, with the
whole outline and the end of the previous chapter as context. The chapter
plans are merged into one ScenePlan whose chapters list their scenes. Like a
short plan, every request gets at most one repair.
"""

from functools import partial
from typing import Annotated

from pydantic import Field, StringConstraints, ValidationError

from .planner import (
    PROMPTS, PlannerError, normalize_ids, output_schema, parse_json, request_json, review_plan, scene_range,
    structured_schema, word_range,
)
from .scene_plan import (
    MAX_SCENES, PlanValidationError, Purpose, Title, _Model, error_problems, text_problems, validate_plan,
)

OUTLINE_PROMPT_VERSION = "outline-planner-v1"
CHAPTER_PROMPT_VERSION = "chapter-planner-v1"
# Each chapter is planned like a short video of this length.
CHAPTER_SECONDS = (40, 150)
SECONDS_PER_CHAPTER = 75
MIN_CHAPTERS, MAX_CHAPTERS = 3, 8
KeyPoint = Annotated[str, StringConstraints(min_length=1, max_length=120)]


class OutlineChapter(_Model):
    title: Title
    goal: Purpose
    key_points: list[KeyPoint] = Field(min_length=1, max_length=4)
    target_seconds: int


class Outline(_Model):
    """The chapter structure of a long video, written before any scene."""

    title: Title
    chapters: list[OutlineChapter] = Field(min_length=2, max_length=MAX_CHAPTERS)


def chapter_range(seconds: int):
    count = round(seconds / SECONDS_PER_CHAPTER)
    return max(MIN_CHAPTERS, count - 1), min(MAX_CHAPTERS, max(MIN_CHAPTERS, count) + 1)


def rescale(seconds: list[int], total: int) -> list[int]:
    """Scale chapter lengths so they add up to total exactly (largest remainders round up)."""
    exact = [value * total / sum(seconds) for value in seconds]
    result = [int(value) for value in exact]
    by_remainder = sorted(range(len(exact)), key=lambda i: exact[i] - result[i], reverse=True)
    for index in by_remainder[:total - sum(result)]:
        result[index] += 1
    return result


def _reference(reference_text: str | None) -> str:
    if reference_text and reference_text.strip():
        return f"\n\nReference material:\n<reference>\n{reference_text.strip()}\n</reference>"
    return ""


def outline_request(spec: dict, reference_text: str | None = None) -> str:
    seconds = spec["targetDurationSec"]
    low, high = chapter_range(seconds)
    return (f"Plan the chapters of this explainer video.\n\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n"
            f"Length: about {seconds} seconds ({seconds / 60:.1f} minutes) of narration in total.\n"
            f"Chapters: {low} to {high}, each with targetSeconds between {CHAPTER_SECONDS[0]} and "
            f"{CHAPTER_SECONDS[1]}, adding up to about {seconds}." + _reference(reference_text))


def review_outline(text: str, spec: dict):
    """Return (outline, problems); the outline is None unless it can be used as it is."""
    data, problems = parse_json(text)
    if problems:
        return None, problems
    try:
        outline = Outline.model_validate(data)
    except ValidationError as exc:
        return None, error_problems(exc)
    seconds = spec["targetDurationSec"]
    low, high = chapter_range(seconds)
    targets = [chapter.target_seconds for chapter in outline.chapters]
    if not low <= len(targets) <= high:
        problems.append(f"chapters: use {low} to {high} chapters, not {len(targets)}")
    for c, chapter in enumerate(outline.chapters):
        if not CHAPTER_SECONDS[0] <= chapter.target_seconds <= CHAPTER_SECONDS[1]:
            problems.append(f"chapters[{c}].targetSeconds: {chapter.target_seconds} is outside "
                            f"{CHAPTER_SECONDS[0]} to {CHAPTER_SECONDS[1]}")
        problems += [f"chapters[{c}].title: {problem}" for problem in text_problems(chapter.title)]
    if abs(sum(targets) - seconds) > 0.1 * seconds:
        problems.append(f"chapters: targetSeconds add up to {sum(targets)}, but the video is about {seconds} seconds")
    problems += [f"title: {problem}" for problem in text_problems(outline.title)]
    return (None if problems else outline), problems


def chapter_request(spec: dict, outline: Outline, index: int, seconds: int, scene_cap: int,
                    previous_lines: list[str], reference_text: str | None = None) -> str:
    count = len(outline.chapters)
    chapter = outline.chapters[index]
    _, target, _ = word_range(seconds)
    min_scenes, max_scenes = scene_range(seconds, scene_cap)
    overview = "\n".join(f"{n}. {item.title}: {item.goal}" for n, item in enumerate(outline.chapters, start=1))
    points = "\n".join(f"- {point}" for point in chapter.key_points)
    if index == 0:
        position = "This is the opening chapter: frame the question and why it matters. Do not recap the video."
    elif index == count - 1:
        position = ("This is the final chapter: begin with one short line that connects to the previous chapter, "
                    "and end the video with a short summary scene that recaps the key ideas of all chapters.")
    else:
        position = ("Begin with one short line that connects to the previous chapter. Do not introduce the "
                    "video again, and do not end with a recap of the whole video.")
    text = (f"Write the scene plan for chapter {index + 1} of {count} of this explainer video.\n\n"
            f"Video title: {outline.title}\n"
            f"Topic: {spec['topic']}\n"
            f"Audience: {spec['audience']}\n\n"
            f"All chapters:\n{overview}\n\n"
            f"Chapter {index + 1}: {chapter.title}\n"
            f"Goal: {chapter.goal}\n"
            f"Key points, in order:\n{points}\n"
            f"Length: about {seconds} seconds, so about {target} words of narration "
            f"(stay between {round(target * 0.9)} and {round(target * 1.1)} words).\n"
            f"Scenes: {min_scenes} to {max_scenes}. Vary the templates when the content allows. "
            f"Use the chapter title as the plan title.\n"
            f"{position}")
    if previous_lines:
        text += ("\n\nThe previous chapter ended with these narration lines:\n"
                 + "\n".join(f"> {line}" for line in previous_lines))
    return text + _reference(reference_text)


def merge_chapters(spec: dict, outline: Outline, plans: list):
    """One ScenePlan with globally numbered ids and a chapter per chapter plan."""
    scenes, bounds = [], []
    for plan in plans:
        data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
        bounds.append((len(scenes), len(scenes) + len(data["scenes"])))
        scenes += data["scenes"]
    merged = normalize_ids({"schemaVersion": "1", "projectId": spec["projectId"], "title": outline.title,
                            "scenes": scenes}, spec["projectId"])
    merged["chapters"] = [{"id": f"chapter-{c:02d}", "title": chapter.title,
                           "sceneIds": [scene["id"] for scene in merged["scenes"][start:end]]}
                          for c, (chapter, (start, end)) in enumerate(zip(outline.chapters, bounds), start=1)]
    return validate_plan(merged)


def generate_long_plan(spec: dict, client, reference_text: str | None = None, progress=lambda message: None,
                       attempts: list | None = None):
    """Return (plan, outline record). Every request is appended to attempts as it is made."""
    attempts = [] if attempts is None else attempts
    outline = request_json(client, (PROMPTS / "outline-planner.txt").read_text(encoding="utf-8"),
                           outline_request(spec, reference_text),
                           structured_schema(Outline.model_json_schema(by_alias=True)),
                           partial(review_outline, spec=spec), "chapter outline", attempts, "outline", progress)
    seconds = rescale([chapter.target_seconds for chapter in outline.chapters], spec["targetDurationSec"])
    record = {"title": outline.title,
              "chapters": [{**chapter.model_dump(mode="json", by_alias=True), "plannedSeconds": planned}
                           for chapter, planned in zip(outline.chapters, seconds)]}
    progress(f"Outline: {len(seconds)} chapters, {', '.join(f'{value} s' for value in seconds)}")
    system = "\n\n".join((PROMPTS / name).read_text(encoding="utf-8").strip()
                         for name in ("scene-planner.txt", "chapter-planner.txt")) + "\n"
    schema, count = output_schema(), len(seconds)
    scene_cap = min(12, MAX_SCENES // count)
    plans, previous = [], []
    for index, chapter_seconds in enumerate(seconds):
        chapter_spec = {"projectId": spec["projectId"], "targetDurationSec": chapter_seconds, "sceneCap": scene_cap}
        plan = request_json(client, system,
                            chapter_request(spec, outline, index, chapter_seconds, scene_cap, previous, reference_text),
                            schema, partial(review_plan, spec=chapter_spec, require_templates=False),
                            f"scene plan for chapter {index + 1} of {count}", attempts,
                            f"chapter-{index + 1:02d}", progress)
        plans.append(plan)
        previous = [line.text for line in plan.scenes[-1].narration][-3:]
    try:
        return merge_chapters(spec, outline, plans), record
    except PlanValidationError as exc:
        raise PlannerError("The chapter plans could not be merged: " + "; ".join(exc.problems), attempts) from None
