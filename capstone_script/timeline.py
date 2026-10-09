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
from .scene_plan import dump_plan, load_plan

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
    for scene in plan.scenes:
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
            frames = math.ceil(block["sampleCount"] / samples_per_frame)
            entry = {"id": line.id, "text": line.text, "from": frame, "durationInFrames": frames,
                     "audioPath": block["audioPath"], "sampleCount": block["sampleCount"]}
            if scene.template == "concept" and line.highlight_point_index is not None:
                entry["highlightPointIndex"] = line.highlight_point_index
            if scene.template == "flow" and line.highlight_node_id is not None:
                entry["highlightNodeId"] = line.highlight_node_id
            lines.append(entry)
            frame += frames
        frame += TAIL_FRAMES
        scenes.append({"id": scene.id, "chapterId": chapter.id if chapter else None, "template": scene.template,
                       "visual": scene.visual.model_dump(mode="json", by_alias=True),
                       "from": start, "durationInFrames": frame - start, "lines": lines})
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


def write_timeline(run_dir: Path) -> Path:
    """Write video/timeline.json, video/narration.wav and video/subtitles.(srt|vtt) for a narrated run."""
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
    return out
