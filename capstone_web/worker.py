"""Run one real pipeline in an isolated process and emit structured progress."""

import argparse
import json
import os
from pathlib import Path
import sys
import traceback

from .health import ROOT, SAMPLE_FIXTURE, model_cached
from .jobs import EVENT_PREFIX


def emit(event):
    # The leading newline separates events from Remotion's terminal progress output.
    print("\n" + EVENT_PREFIX + json.dumps(event, ensure_ascii=False), flush=True)


def error_message(stage, exc):
    name = type(exc).__name__
    if name in {"AuthenticationError", "PermissionDeniedError"}:
        detail = "Claude could not authenticate. Check the API credential in the server environment or .env."
    elif name in {"RateLimitError"}:
        detail = "Claude rejected the request because of an account or rate limit. Check your API account before retrying."
    elif name in {"APIConnectionError", "APITimeoutError"}:
        detail = "Claude could not be reached. Check the server's network connection before retrying."
    else:
        detail = f"The pipeline reported {name}. Check this job's local worker.log for details."
    return f"Generation failed during {stage}. {detail} No automatic retry was made by the web server."


def generate(job, job_dir, emit_event=emit):
    """The caller marks completion only after every existing pipeline check succeeds."""
    from capstone_script.narrate import narrate_plan
    from capstone_script.planner import load_env_file, make_spec, write_plan_run
    from capstone_script.render import render_video
    from capstone_script.review import write_review
    from capstone_script.scene_plan import dump_plan, load_plan
    from capstone_script.timeline import write_timeline
    from capstone_tts.engine import KokoroEngine

    request = job["request"]
    output = Path(job_dir) / "output"
    stage = "narrating" if request["source"] == "sample" else "planning"

    def update(name, message, **extras):
        nonlocal stage
        stage = name
        emit_event({"type": "progress", "stage": name, "message": message, **extras})

    try:
        if request["source"] == "sample":
            update("narrating", "Loading the built-in sample script. No Claude request is made.")
            plan = load_plan(ROOT / SAMPLE_FIXTURE)
            output.mkdir(parents=True, exist_ok=False)
            (output / "scene-plan.json").write_text(dump_plan(plan), encoding="utf-8")
        else:
            update("planning", "Claude is creating the script and scene plan.")
            load_env_file(ROOT / ".env")
            import anthropic
            client = anthropic.Anthropic()
            spec, reference = make_spec(request["topic"], request["audience"], request["durationSeconds"])
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
        update("rendering", "Synchronizing narration, subtitles, and animated scenes.")
        write_timeline(output)
        update("rendering", "Remotion is rendering your MP4. This can take several minutes.")
        info = render_video(output, draft=request["draft"], theme=request["theme"], music=request["music"],
                            progress=lambda message: print(message, flush=True))
        base = f"/api/jobs/{job['id']}/files"
        result = {"videoUrl": base + "/video.mp4", "downloadUrl": base + "/video.mp4?download=1",
                  "thumbnailUrl": base + "/thumbnail.png" if info.get("thumbnail") and (output / "thumbnail.png").is_file() else None,
                  "subtitlesUrl": base + "/subtitles.vtt" if (output / "video/subtitles.vtt").is_file() else None,
                  "durationSeconds": info["probedSeconds"], "width": info["width"], "height": info["height"],
                  "bytes": info["bytes"], "title": plan.title}
        emit_event({"type": "result", "result": result})
        return result
    except Exception as exc:
        traceback.print_exc()
        emit_event({"type": "error", "stage": stage, "message": error_message(stage, exc)})
        raise


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
