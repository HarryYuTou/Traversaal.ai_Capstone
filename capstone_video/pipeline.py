"""Durable, bounded clip generation and atomic integration into the render timeline."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import time

from . import MODEL_ID, SubmissionUnknown, VideoError
from .planning import atomic_json, digest


def file_digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def probe(path):
    from capstone_script.render import _node, REMOTION_CLI, RENDERER
    result = subprocess.run([_node(), str(REMOTION_CLI), "ffprobe", "-v", "error", "-show_streams",
                             "-show_format", "-of", "json", str(path)], cwd=RENDERER,
                            capture_output=True, text=True, check=True, timeout=60)
    data = json.loads(result.stdout)
    streams = [item for item in data["streams"] if item["codec_type"] == "video"]
    if len(streams) != 1:
        raise VideoError("The generated file must contain exactly one video stream.")
    stream = streams[0]
    return {"duration": float(stream.get("duration") or data["format"]["duration"]),
            "width": stream["width"], "height": stream["height"],
            "frames": int(stream.get("nb_frames") or 0),
            "audioStreams": sum(item["codec_type"] == "audio" for item in data["streams"])}


def normalize(source, target, frames, fps):
    from capstone_script.render import _node, REMOTION_CLI, RENDERER
    metadata = probe(source)
    if metadata["duration"] + 1 / fps < frames / fps or not 0 < metadata["duration"] <= 20:
        raise VideoError("The generated clip cannot cover its narration slot. No freezing or looping was used.")
    if metadata["width"] < 320 or metadata["height"] < 240:
        raise VideoError("The generated clip has an unusable resolution.")
    target = Path(target)
    temporary = target.with_name(target.stem + ".partial.mp4")
    try:
        # Decode fully, discard provider audio, convert 24 fps to timeline fps, and trim without slowing speech.
        subprocess.run([_node(), str(REMOTION_CLI), "ffmpeg", "-v", "error", "-y", "-i", str(source),
                        "-map", "0:v:0", "-an", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",
                        "-r", str(fps), "-fps_mode", "cfr",
                        "-frames:v", str(frames), "-c:v", "libx264", "-crf", "20", "-preset", "fast",
                        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(temporary)],
                       cwd=RENDERER, capture_output=True, check=True, timeout=180)
        checked = probe(temporary)
        if checked["frames"] != frames or checked["audioStreams"] or abs(checked["duration"] - frames / fps) > 1 / fps:
            raise VideoError("The normalized clip failed its frame or audio check.")
        temporary.replace(target)
        return {**checked, "sha256": file_digest(target)}
    finally:
        temporary.unlink(missing_ok=True)


def check_plan(plan):
    expected = plan.get("planDigest")
    if expected != digest({k: v for k, v in plan.items() if k != "planDigest"}) or plan.get("model") != MODEL_ID:
        raise VideoError("The saved video plan was changed. Existing tasks will not be resubmitted.")
    if plan.get("resolution") not in ("480p", "720p") or plan.get("fps") != 30:
        raise VideoError("The saved video plan uses unsupported settings.")
    full_video = plan.get("schemaVersion") == "2"
    if (type(plan.get("maxGeneratedSeconds")) is not int or plan["maxGeneratedSeconds"] < 4
            or (not full_video and plan["maxGeneratedSeconds"] > 120)):
        raise VideoError("The saved video plan has an invalid footage limit.")
    if not isinstance(plan.get("shots"), list) or not plan["shots"]:
        raise VideoError("The video plan has no shots.")
    ids = set()
    for shot in plan["shots"]:
        if (shot["id"] != f"shot-{len(ids) + 1:03d}" or shot["id"] in ids
                or type(shot["requestSeconds"]) is not int or not 4 <= shot["requestSeconds"] <= 15
                or type(shot["durationInFrames"]) is not int or not 1 <= shot["durationInFrames"] <= shot["requestSeconds"] * 30
                or type(shot["offsetFrames"]) is not int or shot["offsetFrames"] < 0):
            raise VideoError("The saved video shot contract is invalid.")
        ids.add(shot["id"])
    if sum(shot["requestSeconds"] for shot in plan["shots"]) > plan["maxGeneratedSeconds"]:
        raise VideoError("The video plan exceeds its footage limit.")
    if full_video and (plan.get("coverage") != "full"
                       or plan["maxGeneratedSeconds"] != 2 * sum(s["requestSeconds"] for s in plan["shots"])
                       or plan.get("durationInFrames") != sum(s["durationInFrames"] for s in plan["shots"])):
        raise VideoError("The full-video plan has inconsistent duration or retry bounds.")


def generate_clips(run_dir, plan, provider, *, progress=lambda **event: None, retry_failed=False,
                   wait_seconds=15, timeout_seconds=1800, sleep=time.sleep, clock=time.monotonic,
                   normalize_clip=normalize):
    check_plan(plan)
    run_dir = Path(run_dir)
    path = run_dir / "video-generation.json"
    asset_dir = run_dir / "video/generated"
    asset_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"schemaVersion": "1", "planDigest": plan["planDigest"], "model": MODEL_ID,
                "resolution": plan["resolution"], "status": "running", "shots": {}}
    if path.exists():
        manifest = json.loads(path.read_text())
        if manifest.get("planDigest") != plan["planDigest"] or manifest.get("model") != MODEL_ID:
            raise VideoError("Saved task metadata does not match this video plan.")

    def save():
        records = manifest["shots"].values()
        manifest["submittedSeconds"] = sum(a["seconds"] for record in records for a in record["attempts"])
        tokens = sum(a.get("completionTokens", 0) for record in manifest["shots"].values() for a in record["attempts"])
        manifest["completionTokens"] = tokens
        # List price checked 2026-11-19: Fast, no video input, CNY 37 per million tokens.
        missing_usage = any(a.get("status") == "succeeded" and "completionTokens" not in a
                            for record in manifest["shots"].values() for a in record["attempts"])
        manifest["estimatedCostCny"] = None if missing_usage else round(tokens * 37 / 1_000_000, 4)
        manifest["costBasis"] = "CNY 37/M completion tokens; estimate, actual invoice controls; no video input"
        atomic_json(path, manifest)

    try:
        manifest["status"] = "running"
        preflight_done = False
        for index, shot in enumerate(plan["shots"]):
            record = manifest["shots"].setdefault(shot["id"], {"state": "pending", "attempts": []})
            target = asset_dir / (shot["id"] + ".mp4")
            source = asset_dir / (shot["id"] + "-source.mp4")
            if record["state"] == "ready":
                if target.is_file() and file_digest(target) == record.get("media", {}).get("sha256"):
                    progress(current=index + 1, total=len(plan["shots"]), message=f"Reusing verified clip {index + 1}.")
                    continue
                record["state"] = "succeeded"
            if record["state"] in ("submitting", "submission_unknown"):
                raise SubmissionUnknown("An earlier submission has no saved task ID. Check the Ark task list; "
                                        "automatic resubmission is disabled to avoid duplicate charges.")
            if record["state"] in ("failed", "cancelled", "expired", "rejected") and not retry_failed:
                raise VideoError("A video task stopped. Use Resume to retry a definite failure within the saved retry allowance.")
            if record["state"] in ("pending", "failed", "cancelled", "expired", "rejected"):
                if len(record["attempts"]) >= 2:
                    raise VideoError("This shot reached its two-attempt limit. No further paid requests were made.")
                spent = sum(a["seconds"] for r in manifest["shots"].values() for a in r["attempts"])
                if spent + shot["requestSeconds"] > plan["maxGeneratedSeconds"]:
                    raise VideoError("The generated-seconds limit was reached, including previous attempts. "
                                     "Existing clips are saved; no further paid requests were made.")
                if not preflight_done:
                    provider.preflight()
                    preflight_done = True
                record.update(state="submitting")
                record["attempts"].append({"seconds": shot["requestSeconds"], "model": MODEL_ID})
                # Persist the submission intent before sending any paid POST.
                save()
                progress(current=index, total=len(plan["shots"]), message=f"Submitting clip {index + 1} with Seedance 2.0 Fast.")
                try:
                    task_id = provider.submit(shot["prompt"], shot["requestSeconds"], plan["resolution"], shot["seed"])
                except SubmissionUnknown:
                    record["state"] = "submission_unknown"
                    raise
                except VideoError:
                    record["state"] = "rejected"
                    raise
                record.update(state="queued")
                record["attempts"][-1]["taskId"] = task_id
                save()
            task_id = record["attempts"][-1]["taskId"]
            deadline = clock() + timeout_seconds
            while True:
                progress(current=index, total=len(plan["shots"]), message=f"Clip {index + 1}: checking {record['state']} task.")
                response = provider.get(task_id)
                status = response.get("status")
                if status not in {"queued", "running", "succeeded", "failed", "cancelled", "expired"}:
                    raise VideoError("Ark returned an unknown video task state.")
                if response.get("model") not in (None, MODEL_ID):
                    raise VideoError("The video task used a different model; generation stopped.")
                record["state"] = status
                attempt = record["attempts"][-1]
                attempt["status"] = status
                tokens = (response.get("usage") or {}).get("completion_tokens")
                if status == "succeeded" and type(tokens) is int and tokens >= 0:
                    attempt["completionTokens"] = tokens
                elif status == "succeeded":
                    attempt.pop("completionTokens", None)
                save()
                if status == "succeeded":
                    if response.get("model") != MODEL_ID:
                        raise VideoError("Ark did not identify the completed task's model. The clip was not accepted.")
                    url = (response.get("content") or {}).get("video_url")
                    if not isinstance(url, str):
                        raise VideoError("The completed video task has no download URL.")
                    if not source.is_file() or record.get("sourceTaskId") != task_id:
                        provider.download(url, source)
                        record["sourceTaskId"] = task_id
                        save()
                    progress(current=index, total=len(plan["shots"]), message=f"Checking and aligning clip {index + 1}.")
                    record["media"] = normalize_clip(source, target, shot["durationInFrames"], plan["fps"])
                    record.update(state="ready", path=f"generated/{shot['id']}.mp4")
                    save()
                    break
                if status in {"failed", "cancelled", "expired"}:
                    code = (response.get("error") or {}).get("code", "provider_failure")
                    record["errorCode"] = str(code)[:100]
                    save()
                    raise VideoError(f"Clip {index + 1} ended as {status}. Inspect the local error code, then resume if appropriate. "
                                     "Other clips and task IDs are saved.")
                if clock() >= deadline:
                    raise VideoError("The local wait limit was reached. Resume to keep checking the existing task; "
                                     "no replacement task was submitted.")
                sleep(wait_seconds)
            progress(current=index + 1, total=len(plan["shots"]), message=f"Clip {index + 1} of {len(plan['shots'])} ready.")
        manifest["status"] = "completed"
        save()
        return manifest
    except Exception:
        manifest["status"] = "stopped"
        save()
        raise


def integrate_clips(run_dir, timeline, plan, manifest):
    check_plan(plan)
    if manifest.get("status") != "completed" or manifest.get("planDigest") != plan["planDigest"]:
        raise VideoError("All planned video clips must finish before final rendering.")
    if plan.get("coverage") == "full":
        from .composition import require_full_coverage
        require_full_coverage(timeline, plan)
    result = copy.deepcopy(timeline)
    generated_frames = 0
    for scene in result["scenes"]:
        shots = [shot for shot in plan["shots"] if shot["sceneId"] == scene["id"]]
        if not shots:
            continue
        clips, end = [], 0
        for shot in shots:
            record = manifest["shots"][shot["id"]]
            expected_path = f"generated/{shot['id']}.mp4"
            asset = Path(run_dir) / "video" / expected_path
            if (record["state"] != "ready" or record.get("path") != expected_path or not asset.is_file()
                    or file_digest(asset) != record["media"]["sha256"] or shot["offsetFrames"] != end):
                raise VideoError("A generated video asset is missing, changed, or leaves a timeline gap.")
            clips.append({"path": expected_path, "from": end, "durationInFrames": shot["durationInFrames"]})
            end += shot["durationInFrames"]
        if end != scene["durationInFrames"]:
            raise VideoError("Generated clips must cover their scene exactly.")
        scene.update(template="generated-video", visual={"title": scene["visual"].get("title", timeline["title"]),
                                                         "clips": clips, "model": MODEL_ID})
        scene.pop("processTrace", None)
        generated_frames += end
    result["generatedVideo"] = {"model": MODEL_ID, "resolution": plan["resolution"], "shotCount": len(plan["shots"]),
                                "seconds": round(generated_frames / timeline["fps"], 3),
                                "submittedSeconds": manifest["submittedSeconds"],
                                "completionTokens": manifest["completionTokens"],
                                "estimatedCostCny": manifest["estimatedCostCny"]}
    if generated_frames != sum(shot["durationInFrames"] for shot in plan["shots"]):
        raise VideoError("The generated shot plan references an unknown scene.")
    if plan.get("coverage") == "full":
        result["generatedVideo"]["coverage"] = "full"
    atomic_json(Path(run_dir) / "video/timeline.json", result)
    return result
