"""Plan timed video shots; retain the old hybrid contract only for saved jobs."""

import hashlib
import json
import math
from pathlib import Path

from . import MODEL_ID, RESOLUTIONS, VideoError

PROTECTED = {"flow", "comparison", "definition", "timeline", "stat", "quote", "map", "process"}
ROOT = Path(__file__).resolve().parents[1]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_json(path, value):
    import os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def candidate_scenes(plan, timeline, max_seconds=None, *, full_video=False):
    sources = {scene.id: scene for scene in plan.scenes}
    candidates, seconds = [], 0
    for scene in timeline["scenes"]:
        source = sources[scene["id"]]
        if not full_video and source.template in PROTECTED:
            continue
        if not full_video and source.template == "motion" and (source.visual.contacts or source.visual.rigs):
            continue
        frames = scene["durationInFrames"]
        # Balanced shots, at most ten seconds each, within the provider's 4–15 s range.
        count = math.ceil(frames / (10 * timeline["fps"]))
        boundaries = [round(i * frames / count) for i in range(count + 1)]
        slots = [{"offsetFrames": boundaries[i], "durationInFrames": boundaries[i + 1] - boundaries[i],
                  "requestSeconds": max(4, math.ceil((boundaries[i + 1] - boundaries[i]) / timeline["fps"]))}
                 for i in range(count)]
        cost_seconds = sum(slot["requestSeconds"] for slot in slots)
        if not full_video and seconds + cost_seconds > max_seconds:
            continue
        candidates.append({"sceneId": scene["id"], "narration": [line["text"] for line in scene["lines"]],
                           "visual": source.visual.model_dump(mode="json", by_alias=True, exclude_none=True),
                           "slots": slots})
        seconds += cost_seconds
    return candidates


def validate_directions(data, candidates, *, full_video=False):
    if not isinstance(data, dict) or set(data) != {"style", "scenes"}:
        raise ValueError("Return exactly style and scenes.")
    if not isinstance(data["style"], str) or not 20 <= len(data["style"]) <= 1200:
        raise ValueError("Supply one shared visual style of 20–1200 characters.")
    rows = data["scenes"]
    if not isinstance(rows, list) or len(rows) != len(candidates):
        raise ValueError("Return every candidate scene once, in order.")
    for row, candidate in zip(rows, candidates):
        fields = {"sceneId", "prompts"} if full_video else {"sceneId", "useVideo", "reason", "prompts"}
        if not isinstance(row, dict) or set(row) != fields:
            if full_video:
                raise ValueError("Each scene needs exactly sceneId and prompts; every scene uses generated video.")
            raise ValueError("Each scene needs sceneId, useVideo, reason and prompts.")
        if row["sceneId"] != candidate["sceneId"] or (not full_video and type(row["useVideo"]) is not bool):
            raise ValueError("Scene IDs/order and useVideo must match the contract.")
        if not full_video and (not isinstance(row["reason"], str) or not 1 <= len(row["reason"]) <= 500):
            raise ValueError("Explain each scene's routing decision.")
        expected = len(candidate["slots"]) if full_video or row["useVideo"] else 0
        if not isinstance(row["prompts"], list) or len(row["prompts"]) != expected:
            raise ValueError("Provide one prompt per timed slot for video scenes; otherwise no prompts.")
        if any(not isinstance(prompt, str) or not 30 <= len(prompt) <= 3000 for prompt in row["prompts"]):
            raise ValueError("Each shot prompt needs 30–3000 characters.")
    return data


def directions_schema(full_video=False):
    schema = {"type": "object", "additionalProperties": False, "required": ["style", "scenes"],
            "properties": {"style": {"type": "string"}, "scenes": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["sceneId", "useVideo", "reason", "prompts"], "properties": {
                    "sceneId": {"type": "string"}, "useVideo": {"type": "boolean"},
                    "reason": {"type": "string"}, "prompts": {"type": "array", "items": {"type": "string"}}}}}}}
    if full_video:
        row = schema["properties"]["scenes"]["items"]
        row["required"] = ["sceneId", "prompts"]
        for name in ("useVideo", "reason"):
            del row["properties"][name]
    return schema


def plan_clips(run_dir, plan, timeline, *, resolution="480p", max_seconds=60, client=None, sample=False,
               full_video=False, progress=lambda message: None):
    if resolution not in RESOLUTIONS or (not full_video and (type(max_seconds) is not int or not 4 <= max_seconds <= 120)):
        raise VideoError("Choose 480p or 720p and a generated footage limit of 4–120 seconds.")
    run_dir = Path(run_dir)
    contract = {"timeline": timeline, "source": plan.model_dump(mode="json"),
                "model": MODEL_ID, "resolution": resolution, "maxSeconds": max_seconds}
    if full_video:
        contract.update(coverage="full", maxSeconds=None, version=2)
    fingerprint = digest(contract)
    path = run_dir / "video-plan.json"
    if path.exists():
        saved = json.loads(path.read_text())
        if saved.get("fingerprint") != fingerprint or saved.get("model") != MODEL_ID:
            raise VideoError("The video plan changed since generation started. Existing paid clips were preserved.")
        return saved
    candidates = candidate_scenes(plan, timeline, max_seconds, full_video=full_video)
    if not candidates:
        raise VideoError("No whole illustrative scene fits the footage limit. Increase the limit or use animation mode.")
    attempts = []
    if sample:
        authored = json.loads((ROOT / "fixtures/seedance-glass-directions.json").read_text())
        directions = {"style": authored["style"], "scenes": [
            {"sceneId": scene["sceneId"], "useVideo": True, "reason": "Authored visual sample.",
             "prompts": [authored["prompts"][scene["sceneId"]] for _ in scene["slots"]]}
            for scene in candidates]}
        if full_video:
            for row in directions["scenes"]:
                del row["useVideo"], row["reason"]
        validate_directions(directions, candidates, full_video=full_video)
    else:
        if client is None:
            raise VideoError("A Claude client is needed to plan a new topic's video shots.")
        from capstone_script.planner import request_json, estimated_cost
        system = (ROOT / "prompts" / ("full-video-director.txt" if full_video else "video-director.txt")).read_text()
        groups = [[]]
        for candidate in candidates:
            if full_video and groups[-1] and sum(len(c["slots"]) for c in groups[-1]) + len(candidate["slots"]) > 8:
                groups.append([])
            groups[-1].append(candidate)
        directions = {"style": "", "scenes": []}
        try:
            for index, group in enumerate(groups):
                def review(text):
                    try:
                        return validate_directions(json.loads(text), group, full_video=full_video), []
                    except (ValueError, TypeError, KeyError) as exc:
                        return None, [str(exc)]
                directed = request_json(client, system, json.dumps({"title": plan.title, "fps": timeline["fps"],
                    "sharedStyle": directions["style"], "candidates": group}), directions_schema(full_video), review,
                    "video shot plan", attempts, f"video-director-{index + 1}", progress,
                    max_tokens=max(6000, min(16000, 700 * sum(len(c["slots"]) for c in group))), effort="medium")
                directions["style"] = directions["style"] or directed["style"]
                directions["scenes"].extend(directed["scenes"])
        finally:
            atomic_json(run_dir / "video-planning.json", {"attempts": attempts,
                        "estimatedCostUsd": estimated_cost(attempts)})
    shots, routing = [], []
    for scene, direction in zip(candidates, directions["scenes"]):
        routing.append({"sceneId": scene["sceneId"], "useVideo": True if full_video else direction["useVideo"],
                        "reason": "Full-video mode." if full_video else direction["reason"]})
        if not full_video and not direction["useVideo"]:
            continue
        for slot, prompt in zip(scene["slots"], direction["prompts"]):
            shot_id = f"shot-{len(shots) + 1:03d}"
            complete = (directions["style"] + "\n" + prompt +
                        "\nSilent explanatory footage. No written words, numbers, subtitles, logos or talking presenter. "
                        "Leave the lower fifth uncluttered for captions. One clear action, steady camera, no jump cuts.")
            shots.append({"id": shot_id, "sceneId": scene["sceneId"], **slot, "prompt": complete,
                          "seed": int(digest({"fingerprint": fingerprint, "shot": shot_id})[:7], 16)})
    if not shots:
        raise VideoError("The director kept every scene as an exact diagram. Use animation mode for this topic.")
    requested = sum(shot["requestSeconds"] for shot in shots)
    result = {"schemaVersion": "2" if full_video else "1", "fingerprint": fingerprint, "model": MODEL_ID,
              "resolution": resolution, "fps": timeline["fps"], "maxGeneratedSeconds": requested * 2 if full_video else max_seconds,
              "requestedSeconds": requested, "style": directions["style"], "routing": routing, "shots": shots}
    if full_video:
        from .composition import require_full_coverage
        result.update(coverage="full", durationInFrames=timeline["durationInFrames"])
        require_full_coverage(timeline, result)
    result["planDigest"] = digest(result)
    atomic_json(path, result)
    return result
