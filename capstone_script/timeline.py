"""Narrated run -> frame-accurate timeline, aligned narration track and subtitles.

Every narration line starts on a whole video frame and lasts as many frames as
its real audio needs, with the week-one pauses around lines and silent cards
for the title and each chapter. narration.wav places each line's samples at
exactly its start frame, so a renderer that plays this one track stays in sync
with the timeline by construction. The subtitles use the same frames.
"""

import hashlib
import json
import math
from pathlib import Path

from .planner import write_json
from .process import ProcessCompileError, compile_process_visual
from .scene_plan import dump_plan, load_plan, motion_channel

SCHEMA_VERSION = "1"
FPS = 30
WIDTH, HEIGHT = 1920, 1080
# Week-one pauses at 30 fps: scene lead, gap between lines, scene tail.
LEAD_FRAMES, GAP_FRAMES, TAIL_FRAMES = 6, 3, 6
# Silent cards: the video title first, each chapter's title before its first scene, a hold on the last scene.
TITLE_FRAMES, CHAPTER_FRAMES, END_FRAMES = 60, 45, 30
SUBTITLE_ROW_CHARS = 42
VIDEO_DIR = "video"


class TimelineError(ValueError):
    pass


def compile_motion_contacts(visual: dict, lines: list[dict], scene_start: int, scene_end: int) -> dict:
    """Resolve contacts after actions, preserving authored anchors and continuous release intent.

    A scene-initial zero-approach lock includes the scene's silent lead so supported
    objects never float before narration. Other contacts acquire over at least two
    measured frames. Actual release offsets are computed by the renderer, which
    retains them during subsequent free movement rather than resetting positions.
    """
    if visual.get("contacts") is None:
        return visual
    contacts, intervals = [], {}
    for index, contact in enumerate(visual["contacts"]):
        try:
            first, last = lines[contact["startLine"]], lines[contact["endLine"]]
            start = first["from"] + round(contact["startOffset"] * first["durationInFrames"])
            end = last["from"] + round(contact["endOffset"] * last["durationInFrames"])
            approach = contact["approach"]
            initial = contact["startLine"] == 0 and contact["startOffset"] == 0
            if approach == 0 and initial:
                start = scene_start
        except (IndexError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise TimelineError(f"Motion contact {index} has an unusable narration anchor: {exc}") from None
        if not math.isfinite(approach) or not 0 <= approach <= 0.5 or (approach == 0 and not initial):
            raise TimelineError(f"Motion contact {index} needs an approach within 0–0.5; zero is allowed "
                                "only for a scene-initial contact.")
        if not scene_start <= start < end <= scene_end:
            raise TimelineError(f"Motion contact {index} must span at least one frame inside its scene "
                                f"({scene_start}–{scene_end}); got {start}–{end}.")
        approach_frames = round((end - start) * approach)
        if approach > 0 and approach_frames < 2:
            raise TimelineError(f"Motion contact {index} needs at least two acquisition frames; "
                                "increase approach or extend the contact interval.")
        if approach_frames >= end - start:
            raise TimelineError(f"Motion contact {index} must leave at least one frame locked after acquisition.")
        for previous_start, previous_end, previous_index in intervals.get(contact["entityId"], []):
            if start < previous_end and previous_start < end:
                raise TimelineError(f"Motion contact {index} overlaps contact {previous_index} on source "
                                    f"entity {contact['entityId']!r} after frame compilation.")
        intervals.setdefault(contact["entityId"], []).append((start, end, index))
        for action_index, action in enumerate(visual["actions"]):
            if action["entityId"] != contact["entityId"] or action["kind"] not in ("move", "follow-path", "orbit"):
                continue
            if start < action["from"] + action["durationInFrames"] and action["from"] < end:
                raise TimelineError(f"Motion contact {index} overlaps source travel action {action_index} "
                                    "after frame compilation; schedule source travel after release.")
        contacts.append({**contact, "from": start, "durationInFrames": end - start,
                         "approachFrames": approach_frames})
    return {**visual, "contacts": contacts}


def compile_motion_actions(visual: dict, lines: list[dict], scene_start: int, scene_end: int) -> dict:
    """Resolve narration-relative action anchors onto the measured audio timeline.

    Return a new visual, retaining each authored field. Offsets use the line's measured,
    frame-rounded duration; spans between lines include the same pauses as the narration.
    Never stretch a collapsed action into a neighbouring action's frame interval.
    """
    actions, intervals = [], {}
    for index, action in enumerate(visual["actions"]):
        try:
            first, last = lines[action["startLine"]], lines[action["endLine"]]
            start = first["from"] + round(action["startOffset"] * first["durationInFrames"])
            end = last["from"] + round(action["endOffset"] * last["durationInFrames"])
        except (IndexError, KeyError, TypeError, ValueError, OverflowError) as exc:
            raise TimelineError(f"Motion action {index} has an unusable narration anchor: {exc}") from None
        if not scene_start <= start < end <= scene_end:
            raise TimelineError(f"Motion action {index} must span at least one frame inside its scene "
                                f"({scene_start}–{scene_end}); got {start}–{end}.")
        channel = (action["entityId"], motion_channel(action["kind"]))
        for other_start, other_end, other_index in intervals.get(channel, []):
            if start < other_end and other_start < end:
                raise TimelineError(f"Motion action {index} overlaps action {other_index} on entity "
                                    f"{channel[0]!r} channel {channel[1]!r} after frame compilation.")
        intervals.setdefault(channel, []).append((start, end, index))
        actions.append({**action, "from": start, "durationInFrames": end - start})
    result = {**visual, "actions": actions}
    if visual.get("cues") is not None:
        cues, cue_intervals = [], {}
        for index, cue in enumerate(visual["cues"]):
            try:
                first, last = lines[cue["startLine"]], lines[cue["endLine"]]
                start = first["from"] + round(cue["startOffset"] * first["durationInFrames"])
                end = last["from"] + round(cue["endOffset"] * last["durationInFrames"])
            except (IndexError, KeyError, TypeError, ValueError, OverflowError) as exc:
                raise TimelineError(f"Motion cue {index} has an unusable narration anchor: {exc}") from None
            if not scene_start <= start < end <= scene_end:
                raise TimelineError(f"Motion cue {index} must span at least one frame inside its scene "
                                    f"({scene_start}–{scene_end}); got {start}–{end}.")
            for other_start, other_end, other_index in cue_intervals.get(cue["entityId"], []):
                if start < other_end and other_start < end:
                    raise TimelineError(f"Motion cue {index} overlaps cue {other_index} on entity "
                                        f"{cue['entityId']!r} after frame compilation.")
            cue_intervals.setdefault(cue["entityId"], []).append((start, end, index))
            cues.append({**cue, "from": start, "durationInFrames": end - start})
        result["cues"] = cues
    if visual.get("performances") is not None:
        performances, performance_intervals = [], {}
        entities = {entity["id"]: entity for entity in visual["entities"]}
        rigs = {rig["id"]: rig for rig in visual.get("rigs") or []}
        for index, performance in enumerate(visual["performances"]):
            try:
                first, last = lines[performance["startLine"]], lines[performance["endLine"]]
                start = first["from"] + round(performance["startOffset"] * first["durationInFrames"])
                end = last["from"] + round(performance["endOffset"] * last["durationInFrames"])
                rig = rigs[entities[performance["entityId"]]["rigId"]]
                clip = next(clip for clip in rig["clips"] if clip["id"] == performance["clipId"])
            except (IndexError, KeyError, TypeError, ValueError, OverflowError, StopIteration) as exc:
                raise TimelineError(f"Rig performance {index} has an unusable anchor or reference: {exc}") from None
            if not scene_start <= start < end <= scene_end:
                raise TimelineError(f"Rig performance {index} must span at least one frame inside its scene "
                                    f"({scene_start}–{scene_end}); got {start}–{end}.")
            if performance["repeat"] > 1 and end - start < performance["repeat"] * 4:
                raise TimelineError(f"Rig performance {index} needs at least four frames per repeated cycle; "
                                    "reduce repeat or extend the interval.")
            for track in clip["tracks"]:
                channel = (performance["entityId"], track["partId"], track["property"])
                for other_start, other_end, other_index in performance_intervals.get(channel, []):
                    if start < other_end and other_start < end:
                        raise TimelineError(f"Rig performance {index} overlaps performance {other_index} on "
                                            f"part/property {channel[1:]!r} after frame compilation.")
                performance_intervals.setdefault(channel, []).append((start, end, index))
            performances.append({**performance, "from": start, "durationInFrames": end - start})
        result["performances"] = performances
    return compile_motion_contacts(result, lines, scene_start, scene_end)


def build_timeline(plan, manifest: dict) -> dict:
    """Place every scene, line and card of a narrated plan on 30 fps frames."""
    if manifest.get("status") != "completed":
        raise TimelineError("Narration is not complete; narrate the plan again in a new directory.")
    if manifest.get("planSha256") != hashlib.sha256(dump_plan(plan).encode("utf-8")).hexdigest():
        raise TimelineError("The scene plan changed after narration; narrate it again in a new directory.")
    rate = manifest["sampleRate"]
    if rate % FPS:
        raise TimelineError(f"Sample rate {rate} Hz is not a whole number of samples per frame at {FPS} fps.")
    samples_per_frame = rate // FPS
    blocks = {block["narrationId"]: block for block in manifest["blocks"]}
    chapter_of = {scene_id: chapter for chapter in plan.chapters or () for scene_id in chapter.scene_ids}
    chapters, scenes, frame = [], [], TITLE_FRAMES
    for scene_index, scene in enumerate(plan.scenes):
        chapter = chapter_of.get(scene.id)
        if chapter is not None and chapter.scene_ids[0] == scene.id:
            chapters.append({"id": chapter.id, "number": len(chapters) + 1, "title": chapter.title,
                             "from": frame, "cardFrames": CHAPTER_FRAMES})
            frame += CHAPTER_FRAMES
        start = frame
        frame += LEAD_FRAMES
        lines = []
        for index, line in enumerate(scene.narration):
            if index:
                frame += GAP_FRAMES
            block = blocks.get(line.id)
            if block is None or block["sampleRate"] != rate or block["channels"] != 1:
                raise TimelineError(f"No usable narration audio for {line.id}.")
            if not isinstance(block.get("sampleCount"), int) or isinstance(block["sampleCount"], bool) \
                    or block["sampleCount"] <= 0:
                raise TimelineError(f"No usable narration sample count for {line.id}.")
            frames = math.ceil(block["sampleCount"] / samples_per_frame)
            entry = {"id": line.id, "text": line.text, "from": frame, "durationInFrames": frames,
                     "audioPath": block["audioPath"], "sampleCount": block["sampleCount"]}
            entry.update((name, value) for name, value in line.model_dump(by_alias=True, exclude_none=True).items()
                         if name.startswith("highlight"))
            lines.append(entry)
            frame += frames
        frame += TAIL_FRAMES
        visual = scene.visual.model_dump(mode="json", by_alias=True, exclude_none=True)
        template, metadata = scene.template, {}
        if scene.template == "motion":
            visual = compile_motion_actions(visual, lines, start, frame)
        elif scene.template == "process":
            try:
                visual, trace = compile_process_visual(scene.visual, lines, start,
                                                       frame + (END_FRAMES if scene_index == len(plan.scenes) - 1 else 0))
            except ProcessCompileError as exc:
                raise TimelineError(f"Scene {scene.id}: {exc}") from None
            template, metadata = "motion", {"processTrace": trace}
        scenes.append({"id": scene.id, "chapterId": chapter.id if chapter else None, "template": template,
                       "visual": visual,
                       "from": start, "durationInFrames": frame - start, "lines": lines, **metadata})
    scenes[-1]["durationInFrames"] += END_FRAMES
    total = frame + END_FRAMES
    for chapter in chapters:
        last = [scene for scene in scenes if scene["chapterId"] == chapter["id"]][-1]
        chapter["durationInFrames"] = last["from"] + last["durationInFrames"] - chapter["from"]
    return {"schemaVersion": SCHEMA_VERSION, "projectId": plan.project_id, "title": plan.title,
            "fps": FPS, "width": WIDTH, "height": HEIGHT, "durationInFrames": total,
            "durationSeconds": total / FPS, "titleFrames": TITLE_FRAMES,
            "audio": {"path": "narration.wav", "sampleRate": rate, "channels": 1,
                      "sampleCount": total * samples_per_frame},
            "chapters": chapters, "scenes": scenes}


def narration_track(run_dir: Path, timeline: dict):
    """One mono float track with every line's samples at its start frame and silence elsewhere."""
    import numpy as np
    import soundfile as sf

    samples_per_frame = timeline["audio"]["sampleRate"] // timeline["fps"]
    track = np.zeros(timeline["audio"]["sampleCount"], dtype=np.float32)
    for scene in timeline["scenes"]:
        for line in scene["lines"]:
            samples, rate = sf.read(Path(run_dir) / line["audioPath"], dtype="float32")
            if rate != timeline["audio"]["sampleRate"] or samples.ndim != 1 or samples.size != line["sampleCount"]:
                raise TimelineError(f"{line['audioPath']} does not match its narration manifest entry.")
            start = line["from"] * samples_per_frame
            track[start:start + samples.size] = samples
    return track


def subtitle_rows(text: str, limit: int = SUBTITLE_ROW_CHARS) -> list[str]:
    """One row, or two rows split at the space nearest the middle when the text is long."""
    if len(text) <= limit or " " not in text:
        return [text]
    middle = len(text) / 2
    split = min((i for i, c in enumerate(text) if c == " "), key=lambda i: abs(i - middle))
    return [text[:split], text[split + 1:]]


def _clock(frame: int, fps: int, separator: str) -> str:
    ms = round(frame * 1000 / fps)
    hours, ms = divmod(ms, 3_600_000)
    minutes, ms = divmod(ms, 60_000)
    seconds, ms = divmod(ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}{separator}{ms:03d}"


def subtitles(timeline: dict, kind: str = "srt") -> str:
    """SubRip (srt) or WebVTT (vtt) cues, one per narration line, on the timeline's frames."""
    separator = "," if kind == "srt" else "."
    cues = []
    lines = [line for scene in timeline["scenes"] for line in scene["lines"]]
    for number, line in enumerate(lines, start=1):
        start = _clock(line["from"], timeline["fps"], separator)
        end = _clock(line["from"] + line["durationInFrames"], timeline["fps"], separator)
        text = "\n".join(subtitle_rows(line["text"]))
        cues.append((f"{number}\n" if kind == "srt" else "") + f"{start} --> {end}\n{text}\n")
    return ("WEBVTT\n\n" if kind == "vtt" else "") + "\n".join(cues)


def chapter_list(timeline: dict) -> str:
    """Chapter start times in the "0:00 Title" form video sites read; the first chapter starts at 0:00."""
    lines = []
    for index, chapter in enumerate(timeline["chapters"]):
        seconds = 0 if index == 0 else chapter["from"] // timeline["fps"]
        minutes, seconds = divmod(seconds, 60)
        lines.append(f"{minutes}:{seconds:02d} {chapter['title']}")
    return "\n".join(lines) + ("\n" if lines else "")


def write_timeline(run_dir: Path) -> Path:
    """Write video/timeline.json, video/narration.wav, video/subtitles.(srt|vtt) and, for long plans,
    video/chapters.txt for a narrated run."""
    import soundfile as sf

    run_dir = Path(run_dir)
    out = run_dir / VIDEO_DIR
    if out.exists():
        raise FileExistsError(f"Output already exists: {out}. Remove it to rebuild the timeline.")
    plan = load_plan(run_dir / "scene-plan.json")
    manifest = json.loads((run_dir / "audio-manifest.json").read_text(encoding="utf-8"))
    timeline = build_timeline(plan, manifest)
    track = narration_track(run_dir, timeline)
    out.mkdir()
    sf.write(out / "narration.wav", track, timeline["audio"]["sampleRate"], subtype="PCM_16")
    if sf.info(out / "narration.wav").frames != track.size:
        raise TimelineError("The aligned narration track failed verification.")
    write_json(out / "timeline.json", timeline)
    for kind in ("srt", "vtt"):
        (out / f"subtitles.{kind}").write_text(subtitles(timeline, kind), encoding="utf-8", newline="\n")
    if timeline["chapters"]:
        (out / "chapters.txt").write_text(chapter_list(timeline), encoding="utf-8", newline="\n")
    return out
