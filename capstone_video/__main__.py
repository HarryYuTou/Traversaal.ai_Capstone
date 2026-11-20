"""A small, resumable real-API sample using the same pipeline as the web studio."""

import argparse
import json
from pathlib import Path

from capstone_web.jobs import validate_request
from capstone_web.worker import generate
from .planning import atomic_json


def main(argv=None):
    parser = argparse.ArgumentParser(description="Generate a ~30-second Seedance 2.0 Fast sample.")
    parser.add_argument("--out", type=Path, default=Path("runs/level2-seedance-sample"))
    parser.add_argument("--resolution", choices=("480p", "720p"), default="480p")
    parser.add_argument("--resume", action="store_true", help="Reuse the saved job, including footage and settings.")
    parser.add_argument("--prepare-only", action="store_true", help="Narrate and plan locally; do not contact Ark or render.")
    args = parser.parse_args(argv)
    directory = args.out.resolve()
    path = directory / "job.json"
    if args.resume:
        if not path.exists():
            parser.error("No saved job exists in --out.")
        job = json.loads(path.read_text())
        job["resumeCount"] = job.get("resumeCount", 0) + 1
    else:
        if directory.exists():
            parser.error("--out already exists. Use --resume or choose a new directory.")
        request = validate_request({"source": "sample", "topic": "Cold glass", "audience": "Curious adults",
            "durationSeconds": 30, "visualMode": "seedance", "videoResolution": args.resolution,
            "music": True})
        job = {"id": "cli-seedance-sample", "request": request, "pipelineVersion": 2}
    atomic_json(path, job)
    try:
        result = generate(job, directory, prepare_only=args.prepare_only)
    except Exception:
        print("Stopped. The saved job remains in " + str(directory) + ". See the error above before resuming.")
        return 1
    if args.prepare_only:
        print(json.dumps(result, indent=2))
    else:
        atomic_json(directory / "result.json", result)
        print("Video: " + str(directory / "output/video.mp4"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
