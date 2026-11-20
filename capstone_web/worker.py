"""Run one real pipeline in an isolated process and emit structured progress."""

import argparse
import json
import os
from pathlib import Path
import sys
import traceback

from .health import ROOT, SAMPLE_FIXTURE, SEEDANCE_FIXTURE, model_cached
from .jobs import EVENT_PREFIX


def emit(event):
    # The leading newline separates events from Remotion's terminal progress output.
    print("\n" + EVENT_PREFIX + json.dumps(event, ensure_ascii=False), flush=True)


def error_message(stage, exc):
    from capstone_video import VideoError
    name = type(exc).__name__
    if isinstance(exc, VideoError):
        detail = str(exc)
    elif name in {"AuthenticationError", "PermissionDeniedError"}:
        detail = "Claude could not authenticate. Check the API credential in the server environment or .env."
    elif name in {"RateLimitError"}:
        detail = "Claude rejected the request because of an account or rate limit. Check your API account before retrying."
    elif name in {"APIConnectionError", "APITimeoutError"}:
        detail = "Claude could not be reached. Check the server's network connection before retrying."
    elif name == "DurationError":
        detail = "The measured video did not pass its duration requirement. Review duration-check.json and duration-extension.json in this job's output."
    elif name == "PlannerError":
        # Match only the pipeline's fixed prefix; never expose model findings or
        # arbitrary exception text in the public job status.
        visual_gate = "Visual repair still has narration/action mismatches or unsupported factual claims: "
        if stage == "reviewing" and str(exc).startswith(visual_gate):
            detail = ("The quality check found that some visuals still did not match the narration, "
                      "or that the explanation contained unsupported claims. Generation stopped before rendering. "
                      "You can try again or adjust the topic.")
        elif stage == "reviewing":
            detail = "The generated script did not pass its quality checks. You can try again or simplify the topic."
        elif stage == "planning":
            detail = "We could not create a valid script and scene plan. You can try again or simplify the topic."
        else:
            detail = "The script could not pass validation. You can try again or simplify the topic."
    else:
        detail = f"The pipeline reported {name}. Check this job's local worker.log for details."
    return f"Generation failed during {stage}. {detail} No automatic retry was made by the web server."


def generate(job, job_dir, emit_event=emit, *, prepare_only=False):
    """Prevent two local processes from submitting the same job concurrently."""
    if job["request"].get("visualMode") != "seedance":
        return _generate(job, job_dir, emit_event, prepare_only=prepare_only)
    from capstone_video import VideoError
    try:
        import fcntl
    except ImportError:
        raise VideoError("Seedance job locking currently requires macOS or Linux.") from None
    Path(job_dir).mkdir(parents=True, exist_ok=True)
    with (Path(job_dir) / "pipeline.lock").open("a") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise VideoError("This job is already being processed. No second generation was started.") from None
        return _generate(job, job_dir, emit_event, prepare_only=prepare_only)


def _generate(job, job_dir, emit_event=emit, *, prepare_only=False):
    """The caller marks completion only after every existing pipeline check succeeds."""
    from capstone_script.duration import duration_check, requested_minimum
    from capstone_script.planner import load_env_file
    from capstone_script.render import render_video
    from capstone_script.scene_plan import load_plan

    request = job["request"]
    output = Path(job_dir) / "output"
    seedance = request.get("visualMode") == "seedance"
    full_video = seedance and job.get("pipelineVersion", 1) >= 2
    checkpoint = output / "pipeline-checkpoint.json"
    stage = "narrating" if request["source"] == "sample" else "planning"
    client, reference = None, None
    minimum = 0 if request["source"] == "sample" else requested_minimum(
        request["durationSeconds"], request.get("minimumDurationSec"))

    def update(name, message, **extras):
        nonlocal stage
        stage = name
        emit_event({"type": "progress", "stage": name, "message": message, **extras})

    try:
        load_env_file(ROOT / ".env")
        if seedance and checkpoint.exists():
            from capstone_video.planning import digest
            from capstone_video.pipeline import file_digest
            from capstone_video import VideoError
            saved = json.loads(checkpoint.read_text())
            if saved.get("requestDigest") != digest(request) or any(
                    not (output / name).is_file() or file_digest(output / name) != checksum
                    for name, checksum in saved["files"].items()):
                raise VideoError("The saved narration or settings changed. Resume stopped before any paid request.")
            plan = load_plan(output / "scene-plan.json")
            update("storyboarding", "Reusing the completed narration and original timeline.")
        else:
            options = {"full_video": True} if full_video else {}
            plan, client, reference = prepare_narration(request, output, minimum, update, **options)

        if seedance:
            from capstone_video.planning import atomic_json, digest, plan_clips
            from capstone_video.pipeline import file_digest, generate_clips, integrate_clips
            from capstone_video.provider import ArkVideoClient
            if not checkpoint.exists():
                atomic_json(output / "video/timeline.base.json", json.loads((output / "video/timeline.json").read_text()))
                files = ["scene-plan.json", "audio-manifest.json", "video/timeline.base.json", "video/subtitles.vtt", "video/subtitles.srt"]
                base_timeline = json.loads((output / "video/timeline.base.json").read_text())
                files.append("video/" + base_timeline["audio"]["path"])
                atomic_json(checkpoint, {"requestDigest": digest(request),
                                        "files": {name: file_digest(output / name) for name in files}})
            timeline = json.loads((output / "video/timeline.base.json").read_text())
            if full_video:
                from capstone_video.composition import full_video_timeline, require_full_coverage
                timeline = full_video_timeline(timeline, request.get("videoResolution", "480p"))
            update("storyboarding", "Planning Seedance shots for the entire video." if full_video else
                   "Resuming the saved hybrid video plan.")
            if request["source"] != "sample" and client is None and not (output / "video-plan.json").exists():
                import anthropic
                client = anthropic.Anthropic()
            shots = plan_clips(output, plan, timeline, resolution=request.get("videoResolution", "480p"),
                               max_seconds=request.get("maxGeneratedSeconds", 60), client=client,
                               sample=request["source"] == "sample", full_video=full_video,
                               progress=lambda message: update("storyboarding", message))
            if full_video:
                require_full_coverage(timeline, shots)
            if prepare_only:
                return {"prepared": True, "durationSeconds": timeline["durationSeconds"],
                        "shotCount": len(shots["shots"]), "requestedSeconds": shots["requestedSeconds"], "model": shots["model"]}
            update("generating_video", "Checking Ark connectivity before generating with Seedance 2.0 Fast.")
            provider = ArkVideoClient()
            try:
                manifest = generate_clips(output, shots, provider, retry_failed=bool(job.get("resumeCount")),
                    progress=lambda current, total, message: update("generating_video", message,
                                                                    clipProgress={"current": current, "total": total}))
            finally:
                provider.close()
            timeline = integrate_clips(output, timeline, shots, manifest)
            # A crashed local render can be repeated without another model request.
            previous = output / ("video-draft.mp4" if request["draft"] and not full_video else "video.mp4")
            if previous.exists():
                previous.replace(previous.with_suffix(".interrupted.mp4"))

        update("rendering", "Remotion is rendering your MP4. This can take several minutes.")
        info = render_video(output, draft=False if full_video else request["draft"],
                            theme=request["theme"], music=request["music"],
                            progress=lambda message: print(message, flush=True))
        base = f"/api/jobs/{job['id']}/files"
        result = {"videoUrl": base + "/video.mp4", "downloadUrl": base + "/video.mp4?download=1",
                  "thumbnailUrl": base + "/thumbnail.png" if info.get("thumbnail") and (output / "thumbnail.png").is_file() else None,
                  "subtitlesUrl": base + "/subtitles.vtt" if (output / "video/subtitles.vtt").is_file() else None,
                  "durationSeconds": info["probedSeconds"], "width": info["width"], "height": info["height"],
                  "durationCheck": duration_check(
                      {"targetDurationSec": request["durationSeconds"], "minimumDurationSec": minimum},
                      info["probedSeconds"], "rendered-mp4"),
                  "bytes": info["bytes"], "title": plan.title}
        if seedance:
            result["generatedVideo"] = timeline["generatedVideo"]
        if result["durationCheck"]["passed"] is False:
            from capstone_script.duration import DurationError
            raise DurationError("The rendered MP4 did not meet its minimum duration.")
        emit_event({"type": "result", "result": result})
        return result
    except Exception as exc:
        traceback.print_exc()
        emit_event({"type": "error", "stage": stage, "message": error_message(stage, exc)})
        raise


def prepare_narration(request, output, minimum, update, *, full_video=False):
    """Complete all script, speech and duration work before paid footage is planned."""
    from capstone_script.narrate import narrate_plan
    from capstone_script.duration import ensure_minimum_duration
    from capstone_script.planner import make_spec, write_plan_run
    from capstone_script.review import write_review
    from capstone_script.scene_plan import dump_plan, load_plan
    from capstone_script.timeline import write_timeline
    from capstone_tts.engine import KokoroEngine

    client, reference = None, None
    if request["source"] == "sample":
        update("narrating", "Loading the built-in sample script. No Claude request is made.")
        fixture = SEEDANCE_FIXTURE if request.get("visualMode") == "seedance" else SAMPLE_FIXTURE
        plan = load_plan(ROOT / fixture)
        output.mkdir(parents=True, exist_ok=False)
        (output / "scene-plan.json").write_text(dump_plan(plan), encoding="utf-8")
    else:
        update("planning", "Claude is creating the script and scene plan.")
        import anthropic
        client = anthropic.Anthropic()
        spec, reference = make_spec(request["topic"], request["audience"], request["durationSeconds"])
        spec["minimumDurationSec"] = minimum
        if full_video:
            # Plan the explanation without spending model calls on renderer-specific geometry.
            spec["allowedTemplates"] = ["concept"]
        plan = write_plan_run(output, spec, client, reference, progress=lambda message: print(message, flush=True))
        if request["review"]:
            update("reviewing", "Claude is reviewing and improving the narration.")
            write_review(output, client, reference, progress=lambda message: print(message, flush=True))
            plan = load_plan(output / "scene-plan.json")

    lines = {line.id for scene in plan.scenes for line in scene.narration}
    done = set()
    offline = model_cached(ROOT)
    update("narrating", "Generating English narration on CPU.", lineProgress={"current": 0, "total": len(lines)})

    def narration_progress(message):
        print(message, flush=True)
        line_id = message.split(":", 1)[0]
        if line_id in lines:
            done.add(line_id)
            update("narrating", f"Narration: {len(done)} of {len(lines)} lines complete.",
                   lineProgress={"current": len(done), "total": len(lines)})

    narrate_plan(plan, output, lambda: KokoroEngine(ROOT / ".cache/huggingface", offline, 2),
                 threads=2, offline=offline, progress=narration_progress)
    if minimum:
        update("narrating", "Checking the measured duration and adding explanation if the minimum is not met.")
        plan = ensure_minimum_duration(output, client, lambda: KokoroEngine(ROOT / ".cache/huggingface", offline, 2),
                                       reference, threads=2, offline=offline,
                                       progress=lambda message: update("narrating", message))
    update("narrating" if request.get("visualMode") == "seedance" else "rendering",
           "Synchronizing narration and subtitles for generated scenes." if full_video else
           "Synchronizing narration, subtitles, and animated scenes.")
    if not (output / "video/timeline.json").exists():
        write_timeline(output)
    return plan, client, reference


def main(argv=None):
    parser = argparse.ArgumentParser(description="Internal Capstone web generation worker.")
    parser.add_argument("--job", type=Path, required=True)
    args = parser.parse_args(argv)
    path = args.job.resolve()
    os.chdir(ROOT)
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
        generate(job, path.parent)
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
