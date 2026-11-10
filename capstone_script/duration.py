"""Measured minimum duration, with bounded content repair and reusable narration.

A target is a planning estimate; minimumDurationSec is an acceptance requirement.
Only newly requested long videos default to the Level 1 floor. Older run specs
without that field retain their original behavior until explicitly opted in.
"""

from functools import partial
import json
import math
from pathlib import Path
import re

from .narrate import narrate_plan
from .planner import (
    PROMPTS, SPEECH_SHARE, estimated_cost, output_schema, planner_prompt, request_json,
    review_plan, word_range, write_json,
)
from .scene_plan import MAX_SCENES, WORDS_PER_SECOND, dump_plan, load_plan, summarize, validate_plan
from .timeline import build_timeline, write_timeline

LEVEL1_SECONDS = 420
MAX_EXTENSION_ROUNDS = 2
EXTENSION_PROMPT_VERSION = "duration-extension-v1"


class DurationError(RuntimeError):
    """A measured video has not met its explicitly requested minimum."""


def requested_minimum(target: int, minimum: int | None = None) -> int:
    """Validate a new request; zero explicitly disables the minimum."""
    if minimum is None:
        return LEVEL1_SECONDS if target >= LEVEL1_SECONDS else 0
    if type(minimum) is not int or (minimum != 0 and not 30 <= minimum <= target):
        raise ValueError("minimumDurationSec must be 0 (off) or a whole number from 30 to the target duration.")
    return minimum


def read_spec(run_dir: Path) -> dict:
    path = Path(run_dir) / "project-spec.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def duration_check(spec: dict, actual: float, stage: str) -> dict:
    minimum = requested_minimum(spec.get("targetDurationSec", 600), spec.get("minimumDurationSec", 0))
    if not math.isfinite(actual) or actual <= 0:
        raise DurationError("The measured video duration is invalid.")
    return {"targetDurationSec": spec.get("targetDurationSec"), "minimumDurationSec": minimum,
            "actualDurationSec": actual, "measurement": stage,
            "passed": actual >= minimum if minimum else None}


def record_duration(run_dir: Path, actual: float, stage: str) -> dict:
    path = Path(run_dir) / "duration-check.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    check = duration_check(read_spec(run_dir), actual, stage)
    write_json(path, {**previous, **check})
    return check


def require_duration(run_dir: Path, actual: float, stage: str) -> dict:
    check = record_duration(run_dir, actual, stage)
    if check["passed"] is False:
        raise DurationError(f"Measured duration is {actual:.2f} s; at least {check['minimumDurationSec']} s is required. "
                            "Add useful explanatory content and narrate again before accepting this video.")
    return check


def _text_key(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", " ".join(text.lower().split()))


def merge_extension(plan, extension, round_number: int):
    """Insert new scenes before the conclusion, retaining every original scene/line ID."""
    data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    additions = extension.model_dump(mode="json", by_alias=True, exclude_none=True)["scenes"]
    if len(data["scenes"]) + len(additions) > MAX_SCENES:
        raise DurationError("The plan has no room for more explanatory scenes.")
    seen = {_text_key(line.text) for scene in plan.scenes for line in scene.narration}
    existing_ids = {scene.id for scene in plan.scenes} | {line.id for scene in plan.scenes for line in scene.narration}
    for index, scene in enumerate(additions, 1):
        scene["id"] = f"duration-{round_number:02d}-scene-{index:02d}"
        if scene["id"] in existing_ids:
            raise DurationError("Duration repair IDs already exist; use a new repair attempt.")
        for number, line in enumerate(scene["narration"], 1):
            key = _text_key(line["text"])
            if key in seen:
                raise DurationError("Duration repair repeated existing narration instead of adding new content.")
            seen.add(key)
            line["id"] = f"duration-{round_number:02d}-scene-{index:02d}-line-{number:02d}"
            if line["id"] in existing_ids:
                raise DurationError("Duration repair narration IDs already exist.")
    final_id = data["scenes"][-1]["id"]
    data["scenes"][-1:-1] = additions
    if data.get("chapters"):
        chapter = next(chapter for chapter in data["chapters"] if final_id in chapter["sceneIds"])
        index = chapter["sceneIds"].index(final_id)
        chapter["sceneIds"][index:index] = [scene["id"] for scene in additions]
    return validate_plan(data)


def generate_extension(plan, spec, manifest, missing_seconds, client, reference_text, attempts, progress):
    """Request additional explanation, sized from this voice's observed speaking rate."""
    speech = manifest["totalSpeechSeconds"]
    rate = summarize(plan)["words"] / speech
    seconds = max(30, min(150, math.ceil((missing_seconds + 5) * rate / (SPEECH_SHARE * WORDS_PER_SECOND))))
    cap = min(6, MAX_SCENES - len(plan.scenes))
    if cap < 2:
        raise DurationError("The plan has no room for the two scenes required for a useful duration extension.")
    extension_spec = {**spec, "targetDurationSec": seconds, "sceneCap": cap}
    low, words, high = word_range(seconds)
    context = [{"title": scene.visual.title, "purpose": scene.purpose,
                "narration": [line.text for line in scene.narration]} for scene in plan.scenes]
    prompt = (f"Topic: {spec['topic']}\nAudience: {spec['audience']}\n"
              f"The measured video is short by {missing_seconds:.2f} seconds. "
              f"Add a useful explanation of about {words} words (between {low} and {high}), in 2 to {cap} scenes. "
              "These scenes will be inserted immediately before the final scene shown below. "
              "Preserve the conclusion's meaning and give the new material a natural lead-in.\n"
              f"Existing scenes, in order:\n{json.dumps(context, ensure_ascii=False)}")
    if reference_text:
        prompt += f"\nReference material (facts must stay within it):\n<reference>\n{reference_text}\n</reference>"
    system = planner_prompt(spec.get("allowedTemplates")) + "\n" + (PROMPTS / "duration-extension.txt").read_text(encoding="utf-8")
    return request_json(client, system, prompt, output_schema(spec.get("allowedTemplates")),
                        partial(review_plan, spec=extension_spec, require_templates=False),
                        "additional explanatory scenes", attempts, "duration-extension", progress)


def _promote(candidate: Path, run_dir: Path, backup: Path):
    """Archive replaced artifacts; on a failed move, restore the original complete run."""
    names = ["scene-plan.json", "scene-plan.draft.json", "review.json", "audio", "audio-manifest.json",
             "narration-preview.wav", "video"]
    # Derived video files must no longer look current after narration changes.
    names += ["video.mp4", "video-info.json", "video-draft.mp4", "video-draft-info.json", "video-720p.mp4",
              "thumbnail.png", "preview.html", "motion-inspection.json", "spatial-inspection.json"]
    backup.mkdir()
    archived, promoted = [], []
    try:
        for name in names:
            path = run_dir / name
            if path.exists():
                path.rename(backup / name)
                archived.append(name)
            if (candidate / name).exists():
                (candidate / name).rename(path)
                promoted.append(name)
    except Exception:
        for name in reversed(promoted):
            (run_dir / name).rename(candidate / name)
        for name in reversed(archived):
            (backup / name).rename(run_dir / name)
        raise


def ensure_minimum_duration(run_dir: Path, client, engine_factory, reference_text=None, *,
                            speed=1.0, threads=2, offline=False, progress=lambda message: None,
                            narration_progress=None, client_factory=None):
    """Use measured TTS to repair an explicit minimum, at most two content extensions.

    Candidate plans, reviews and audio remain available on failure. Existing audio
    is copied by spoken text, so only changed or added narration is synthesized.
    """
    from .review import write_review

    run_dir = Path(run_dir)
    spec, plan = read_spec(run_dir), load_plan(run_dir / "scene-plan.json")
    minimum = requested_minimum(spec.get("targetDurationSec", 600), spec.get("minimumDurationSec", 0))
    if not minimum:
        return plan
    attempts = []
    record_path = run_dir / "duration-extension.json"
    history = json.loads(record_path.read_text(encoding="utf-8")) if record_path.is_file() else {}
    attempts = history.get("attempts", [])
    rounds = history.get("rounds", [])
    initial_review = run_dir / "review.json"
    promoted_rounds = [item for item in rounds if item.get("promoted", "afterSeconds" in item)]
    if promoted_rounds:
        initial_review = run_dir / promoted_rounds[0]["originalArtifacts"] / "review.json"
    initial_review_cost = history.get("initialReviewCostUsd")
    if initial_review_cost is None:
        initial_review_cost = (json.loads(initial_review.read_text(encoding="utf-8")).get("estimatedCostUsd", 0)
                               if initial_review.is_file() else 0)
    candidate = None

    def review_cost(path):
        return json.loads(path.read_text(encoding="utf-8")).get("estimatedCostUsd", 0) if path.is_file() else 0

    # Older repair records stored the actual review alongside the candidate or in
    # the following attempt's archived snapshot. Recover those costs on resume.
    for item in rounds:
        if "reviewCostUsd" not in item:
            review_path = run_dir / item["directory"] / "review.json"
            if item in promoted_rounds:
                index = promoted_rounds.index(item)
                review_path = (run_dir / promoted_rounds[index + 1]["originalArtifacts"] / "review.json"
                               if index + 1 < len(promoted_rounds) else run_dir / "review.json")
            item["reviewCostUsd"] = review_cost(review_path)

    def save(status, **extra):
        generation_cost = estimated_cost(attempts)
        reviews_cost = sum(item.get("reviewCostUsd", 0) for item in rounds)
        write_json(record_path, {"promptVersion": EXTENSION_PROMPT_VERSION, "status": status,
                                 "maxRounds": MAX_EXTENSION_ROUNDS, "rounds": rounds, "attempts": attempts,
                                 "initialReviewCostUsd": initial_review_cost,
                                 "extensionGenerationCostUsd": generation_cost,
                                 "extensionReviewCostUsd": round(reviews_cost, 4),
                                 "estimatedCostUsd": round(generation_cost + reviews_cost, 4), **extra})

    try:
        while True:
            manifest = json.loads((run_dir / "audio-manifest.json").read_text(encoding="utf-8"))
            actual = build_timeline(plan, manifest)["durationSeconds"]
            check = record_duration(run_dir, actual, "narrated-timeline")
            progress(f"Measured duration: {actual:.2f} s; minimum: {minimum} s.")
            if check["passed"]:
                save("passed")
                return plan
            completed = sum(item.get("promoted", "afterSeconds" in item) for item in rounds)
            if completed >= MAX_EXTENSION_ROUNDS:
                raise DurationError(f"Measured duration is {actual:.2f} s after {MAX_EXTENSION_ROUNDS} content extensions; "
                                    f"the {minimum} s minimum was not met. The run remains unaccepted; inspect duration-extension.json.")
            if client is None and client_factory is not None:
                client = client_factory()
            if client is None:
                raise DurationError("Additional explanatory content is needed, but no planning client is available.")
            attempt_number = max([int(path.name.rsplit("-", 1)[-1]) for path in run_dir.glob("duration-attempt-*")
                                  if path.name.rsplit("-", 1)[-1].isdigit()], default=0) + 1
            candidate = run_dir / f"duration-attempt-{attempt_number:02d}"
            candidate.mkdir()
            rounds.append({"round": completed + 1, "attempt": attempt_number, "promoted": False,
                           "beforeSeconds": actual, "directory": candidate.name})
            save("extending")
            progress("Adding a worked example or deeper explanation to meet the minimum duration...")
            extension = generate_extension(plan, spec, manifest, minimum - actual, client, reference_text, attempts, progress)
            merged = merge_extension(plan, extension, attempt_number)
            write_json(candidate / "project-spec.json", {**spec, "reviewWordTarget": summarize(merged)["words"]})
            (candidate / "scene-plan.json").write_text(dump_plan(merged), encoding="utf-8")
            # Review the combined narration so transitions and visual claims get the normal checks.
            write_review(candidate, client, reference_text, progress=progress)
            rounds[-1]["reviewCostUsd"] = review_cost(candidate / "review.json")
            merged = load_plan(candidate / "scene-plan.json")
            original_ids = {scene.id for scene in plan.scenes}
            seen = {_text_key(line.text) for scene in merged.scenes if scene.id in original_ids
                    for line in scene.narration}
            for scene in merged.scenes:
                if scene.id not in original_ids:
                    for line in scene.narration:
                        key = _text_key(line.text)
                        if key in seen:
                            raise DurationError("Reviewed extension repeats narration; the original run was retained.")
                        seen.add(key)
            narrated = narrate_plan(merged, candidate, engine_factory, speed=speed, threads=threads,
                                    offline=offline, progress=narration_progress or progress, reuse_from=run_dir)
            after = build_timeline(merged, narrated)["durationSeconds"]
            if after <= actual:
                raise DurationError("The content extension did not increase measured duration; the original run was retained.")
            # Building from real audio validates geometry/timing and creates fresh subtitles.
            write_timeline(candidate)
            backup = candidate / "previous"
            _promote(candidate, run_dir, backup)
            plan = merged
            rounds[-1].update(promoted=True, afterSeconds=after, reusedLines=narrated["reusedLines"],
                              originalArtifacts=f"{candidate.name}/previous")
            candidate = None
            save("extending")
    except Exception as exc:
        if candidate is not None:
            rounds[-1]["reviewCostUsd"] = review_cost(candidate / "review.json")
        save("failed", error=f"{type(exc).__name__}: {exc}")
        raise
