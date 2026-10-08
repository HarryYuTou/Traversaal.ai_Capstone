import argparse
import json
from pathlib import Path
import platform
import sys


def main():
    parser = argparse.ArgumentParser(description="Generate local English narration with Kokoro on CPU.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check installed dependencies without downloading Kokoro weights.")
    synth = sub.add_parser("synthesize", help="Generate narration.wav and audio-info.json.")
    synth.add_argument("--text", type=Path, required=True, help="UTF-8 English text file")
    synth.add_argument("--output-dir", type=Path, required=True, help="New directory for this run")
    synth.add_argument("--speed", type=float, default=1.0)
    synth.add_argument("--threads", type=int, default=2)
    synth.add_argument("--cache-dir", type=Path, default=Path(".cache/huggingface"))
    synth.add_argument("--offline", action="store_true", help="Use cached model files; never download weights.")
    args = parser.parse_args()
    try:
        if sys.version_info[:2] != (3, 11):
            raise RuntimeError("Use the project's Python 3.11 virtual environment.")
        if args.command == "doctor":
            from importlib.metadata import version
            import numpy
            import scipy
            import soundfile
            import torch
            from kokoro import KModel, KPipeline
            from .engine import check_language_dependencies
            check_language_dependencies()
            print(json.dumps({"status": "ok", "python": platform.python_version(),
                              "architecture": platform.machine(), "device": "cpu",
                              "kokoro": version("kokoro"), "torch": torch.__version__,
                              "englishPhonemizer": "ok", "englishModel": version("en-core-web-sm"),
                              "note": "No Kokoro weights downloaded or synthesized by this check."}, indent=2))
        else:
            from .audio import write_run
            from .engine import KokoroEngine
            result = write_run(
                text_path=args.text, output_dir=args.output_dir, speed=args.speed,
                offline=args.offline, threads=args.threads,
                engine_factory=lambda: KokoroEngine(args.cache_dir, args.offline, args.threads),
                progress=lambda message: print(message, flush=True),
            )
            print(f"Completed: {args.output_dir.resolve() / 'narration.wav'}")
            print(f"{result['durationSeconds']:.2f}s | {result['sampleRate']} Hz | mono | {result['chunkCount']} chunks")
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc or 'Interrupted'}. No new completed run was published.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
