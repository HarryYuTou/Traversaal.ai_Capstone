"""Build preview.html: a browser slideshow of a narrated scene plan.

The page draws each scene with its template, highlights the current point or
node and shows the current line as a subtitle, all driven by the preview
track's clock. It is a quick check of script and narration, not the renderer.
"""

import json
from pathlib import Path

from .scene_plan import load_plan

TEMPLATE = Path(__file__).with_name("preview.html")


def motion_beats(scene):
    """Describe the planned actions per narration line, without simulating motion."""
    visual = scene["visual"]
    names = {entity["id"]: entity.get("label") or entity["kind"].replace("-", " ")
             for entity in visual["entities"]}
    verbs = {"move": "moves to a new position", "follow-path": "follows its route",
             "orbit": "travels around its orbit", "opacity": "changes visibility",
             "scale": "changes size", "rotate": "turns", "value": "changes its displayed value"}
    beats = []
    for index, line in enumerate(scene["narration"]):
        descriptions = [f"{names[action['entityId']]} {verbs[action['kind']]}"
                        for action in visual["actions"]
                        if action["startLine"] <= index <= action["endLine"]
                        and not (index == action["startLine"] and action["startOffset"] == 1)
                        and not (index == action["endLine"] and action["endOffset"] == 0)]
        beats.append({"narrationId": line["id"],
                      "description": "; ".join(dict.fromkeys(descriptions)) + "." if descriptions else
                      "The scene holds while this line is narrated."})
    return beats


def process_beats(scene):
    """Describe semantic events; the MP4 renderer owns their layout and timing."""
    visual = scene["visual"]
    stations = {station["id"]: station["label"] for station in visual["stations"]}
    names = {actor["id"]: actor["label"] or visual["actorKind"] for actor in visual["actors"]}
    beats = []
    for index, line in enumerate(scene["narration"]):
        descriptions = []
        for event in visual["events"]:
            if not event["startLine"] <= index <= event["endLine"]:
                continue
            if ((index == event["startLine"] and event["startOffset"] == 1)
                    or (index == event["endLine"] and event["endOffset"] == 0)):
                continue
            actors = ", ".join(names[actor_id] for actor_id in event["actorIds"])
            destinations = ", ".join(stations[station_id] for station_id in event["stationIds"])
            singular = len(event["actorIds"]) == 1
            descriptions.append({
                "arrive": f"{actors} {'arrives and joins' if singular else 'arrive and join'} the waiting line",
                "start": f"{actors} {'begins' if singular else 'begin'} processing at {destinations}",
                "finish": f"{actors} {'finishes' if singular else 'finish'} at {destinations} and {'leaves' if singular else 'leave'}",
                "open": f"{destinations} {'opens' if len(event['stationIds']) == 1 else 'open'} for service",
                "hold": "The current process state remains visible",
            }[event["kind"]])
        beats.append({"narrationId": line["id"], "description":
                      "; ".join(descriptions) + "." if descriptions else
                      "No new process event is scheduled on this line."})
    return beats


def rendered_videos(run_dir):
    """Link only completed local renders, rather than a partially written MP4."""
    videos = []
    for name, label in (("video", "Watch rendered MP4"), ("video-draft", "Watch rendered draft")):
        video = run_dir / f"{name}.mp4"
        try:
            info = json.loads((run_dir / f"{name}-info.json").read_text(encoding="utf-8"))
            if (video.is_file() and video.stat().st_size == info["bytes"] > 0
                    and abs(info["probedSeconds"] - info["expectedSeconds"]) <= 0.2):
                videos.append({"href": video.name, "label": label})
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return videos


def build_preview(run_dir: Path) -> Path:
    run_dir = Path(run_dir)
    plan = load_plan(run_dir / "scene-plan.json")
    manifest = json.loads((run_dir / "audio-manifest.json").read_text(encoding="utf-8"))
    if manifest.get("status") != "completed":
        raise ValueError(f"Narration in {run_dir} is not complete; run narrate again in a new directory.")
    plan_data = plan.model_dump(mode="json", by_alias=True, exclude_none=True)
    data = {
        "plan": plan_data,
        "blocks": [{key: block[key] for key in
                    ("sceneId", "narrationId", "text", "previewStartSeconds", "durationSeconds")}
                   for block in manifest["blocks"]],
        "audio": manifest["preview"]["audioPath"],
        "lead": manifest["preview"]["leadSeconds"],
        "tail": manifest["preview"]["tailSeconds"],
        "speechSeconds": manifest["totalSpeechSeconds"],
        "motionBeats": {scene["id"]: (process_beats(scene) if scene["template"] == "process"
                                     else motion_beats(scene)) for scene in plan_data["scenes"]
                        if scene["template"] in ("motion", "process")},
        "renderedVideos": rendered_videos(run_dir),
    }
    # "</" inside a script element would end it early, whatever the JSON says.
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    output = run_dir / "preview.html"
    output.write_text(TEMPLATE.read_text(encoding="utf-8").replace("__PREVIEW_DATA__", payload),
                      encoding="utf-8", newline="\n")
    return output
