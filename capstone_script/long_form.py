"""Long videos: plan the chapters first, then write each chapter's scenes.

One request returns an outline: the chapters' titles, goals, key points and
lengths. Each chapter is then planned like a short video, in order, with the
whole outline and the end of the previous chapter as context. The chapter
plans are merged into one ScenePlan whose chapters list their scenes. Like a
short plan, every request gets at most one repair.
"""

from functools import partial
import json
from typing import Annotated

from pydantic import Field, StringConstraints, ValidationError

from .planner import (
    PROMPTS, PlannerError, normalize_ids, output_schema, parse_json, planner_prompt, request_json, review_plan,
    scene_range, structured_schema, template_instruction, word_range,
)
from .scene_plan import (
    MAX_SCENES, PlanValidationError, Purpose, Title, _Model, error_problems, initial_open_station_ids,
    text_problems, validate_plan,
)

OUTLINE_PROMPT_VERSION = "outline-planner-v5"
CHAPTER_PROMPT_VERSION = "chapter-planner-v6"
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
                    "and end the video with a short visual recap of all chapters' key ideas, which may share "
                    "the final process scene.")
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
            f"(stay between {round(target * 0.95)} and {round(target * 1.05)} words).\n"
            f"Scenes: {min_scenes} to {max_scenes}. Prefer process for arrivals, waiting and service, "
            f"and motion for other physical explanations; an all-process or all-motion chapter is allowed. "
            f"Prefer two or three coherent scenes when they fit the narration limits. "
            f"Use the chapter title as the plan title.\n"
            f"{position}")
    text += "\n" + template_instruction(spec)
    if previous_lines:
        text += ("\n\nThe previous chapter ended with these narration lines:\n"
                 + "\n".join(f"> {line}" for line in previous_lines))
    return text + _reference(reference_text)


def visual_continuity(plan):
    """Carry explicit identity and ending state across chapter boundaries."""
    scene = plan.scenes[-1]
    if scene.template not in ("process", "motion"):
        return None
    data = scene.visual.model_dump(mode="json", by_alias=True)
    if scene.template == "process":
        queue = list(data["initialQueue"])
        service = {item["stationId"]: item["actorId"] for item in data["initialService"]}
        completed = []
        open_stations = set(initial_open_station_ids(scene.visual))
        for event in data["events"]:
            if event["kind"] == "arrive":
                queue.extend(event["actorIds"])
            elif event["kind"] == "start":
                queue = queue[len(event["actorIds"]):]
                service.update(zip(event["stationIds"], event["actorIds"]))
            elif event["kind"] == "finish":
                for station in event["stationIds"]:
                    completed.append(service.pop(station))
            elif event["kind"] == "open":
                open_stations.update(event["stationIds"])
        data = {key: data[key] for key in ("actorKind", "actors", "stations")}
        data.update(finalQueue=queue, finalService=[{"actorId": actor, "stationId": station}
                                                  for station, actor in service.items()],
                    completedActorIds=completed, openStationIds=sorted(open_stations))
    return {"sceneTitle": scene.visual.title, "template": scene.template, "endingVisual": data}


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
    system = (planner_prompt(spec.get("allowedTemplates")).strip() + "\n\n"
              + (PROMPTS / "chapter-planner.txt").read_text(encoding="utf-8").strip() + "\n")
    schema, count = output_schema(spec.get("allowedTemplates")), len(seconds)
    scene_cap = min(12, MAX_SCENES // count)
    plans, previous = [], []
    for index, chapter_seconds in enumerate(seconds):
        chapter_spec = {"projectId": spec["projectId"], "targetDurationSec": chapter_seconds, "sceneCap": scene_cap}
        if "allowedTemplates" in spec:
            chapter_spec["allowedTemplates"] = spec["allowedTemplates"]
        request = chapter_request(spec, outline, index, chapter_seconds, scene_cap, previous, reference_text)
        continuity = visual_continuity(plans[-1]) if plans else None
        if continuity:
            request += ("\n\nPrevious chapter visual continuity:\n" + json.dumps(continuity) +
                        "\nContinue these identities, colors and final state when the example continues. "
                        "For motion, derive the ending state from its actions. If resetting a comparison "
                        "or introducing a different example, explicitly say so in narration; do not silently "
                        "resurrect completed actors or change their identities.")
        plan = request_json(client, system, request,
                            schema, partial(review_plan, spec=chapter_spec, require_templates=False),
                            f"scene plan for chapter {index + 1} of {count}", attempts,
                            f"chapter-{index + 1:02d}", progress)
        plans.append(plan)
        previous = [line.text for line in plan.scenes[-1].narration][-3:]
    try:
        return merge_chapters(spec, outline, plans), record
    except PlanValidationError as exc:
        raise PlannerError("The chapter plans could not be merged: " + "; ".join(exc.problems), attempts) from None
