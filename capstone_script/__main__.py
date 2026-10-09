import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from .evaluate import evaluate
from .narrate import narrate_plan
from .planner import attach_reference_url, load_env_file, make_spec, save_reference, write_plan_run
from .reference import fetch_reference
from .preview import build_preview
from .render import render_video
from .review import write_review
from .timeline import write_timeline
from .scene_plan import PlanValidationError, dump_plan, load_plan, schema_text, summarize


def _client():
    import anthropic
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise RuntimeError("No Claude API key found. Add ANTHROPIC_API_KEY=... to a .env file "
                           "in the repository folder.")
    return anthropic.Anthropic()


def _engine_factory(offline: bool, threads: int):
    from capstone_tts.engine import KokoroEngine
    return lambda: KokoroEngine(Path(".cache/huggingface"), offline, threads)


def _print(message):
    print(message, flush=True)


def _validate(path: Path) -> int:
    try:
        summary = summarize(load_plan(path))
    except PlanValidationError as exc:
        print(f"ERROR: {path} is not a valid scene plan:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    chapters = f"{summary['chapters']} chapters, " if summary["chapters"] else ""
    print(f"Valid scene plan: {chapters}{summary['scenes']} scenes, {summary['lines']} narration lines, "
          f"{summary['words']} words (about {summary['estimatedSpeechSeconds']:.0f} s of speech), "
          f"templates: {', '.join(summary['templates'])}")
    return 0


def _new_output(path: Path) -> None:
    if path.exists():
        raise FileExistsError(f"Output already exists: {path}. Choose a new output directory.")


def _write_plan(args):
    spec, reference_text = make_spec(args.topic, args.audience, args.duration, args.reference)
    _new_output(args.out)
    if args.reference_url:
        reference_text = fetch_reference(args.reference_url)
        attach_reference_url(spec, args.reference_url, reference_text, args.out)
        _print(f"Reference: {len(reference_text):,} characters from {args.reference_url}")
    load_env_file()
    client = _client()
    try:
        plan = write_plan_run(args.out, spec, client, reference_text, progress=_print)
    finally:
        if args.reference_url:
            save_reference(args.out, reference_text)
    summary = summarize(plan)
    cost = json.loads((args.out / "llm-response.json").read_text(encoding="utf-8"))["estimatedCostUsd"]
    print(f"Plan: {args.out.resolve() / 'scene-plan.json'}")
    print((f"{summary['chapters']} chapters | " if summary["chapters"] else "")
          + f"{summary['scenes']} scenes | {summary['lines']} lines | {summary['words']} words | "
          f"about {summary['estimatedSpeechSeconds']:.0f} s of speech | API about ${cost:.2f} at list prices")
    if args.review:
        _review(args.out, client, reference_text)
        plan = load_plan(args.out / "scene-plan.json")
    return plan


def _review(run_dir: Path, client, reference_text) -> None:
    review, changes = write_review(run_dir, client, reference_text, progress=_print)
    record = json.loads((run_dir / "review.json").read_text(encoding="utf-8"))
    scores = ", ".join(f"{name} {score}" for name, score in record["scores"].items())
    print(f"Review: {run_dir.resolve() / 'review.json'}")
    print(f"Scores before edits: {scores} | {len(review.issues)} issues | {len(changes)} lines rewritten | "
          f"{record['wordsBefore']} -> {record['wordsAfter']} words | API about ${record['estimatedCostUsd']:.2f}")


def _reference_for(run_dir: Path):
    """The reference file recorded in a run's project spec, checked against its hash."""
    spec = json.loads((run_dir / "project-spec.json").read_text(encoding="utf-8"))
    if "referenceFile" not in spec:
        return None
    text = Path(spec["referenceFile"]).read_text(encoding="utf-8-sig")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != spec["referenceSha256"]:
        raise ValueError(f"{spec['referenceFile']} changed since the plan was written.")
    return text


def _narrate(args, plan) -> int:
    manifest = narrate_plan(plan, args.out, _engine_factory(args.offline, args.threads),
                            speed=args.speed, threads=args.threads, offline=args.offline, progress=_print)
    print(f"Narration: {args.out.resolve() / 'audio-manifest.json'}")
    print(f"{len(manifest['blocks'])} lines | {manifest['totalSpeechSeconds']:.1f} s of speech | "
          f"preview {manifest['preview']['durationSeconds']:.1f} s: {manifest['preview']['audioPath']}")
    print(f"Preview: {build_preview(args.out).resolve()}")
    if getattr(args, "render", False):
        _render(args.out, args.draft)
    return 0


def _render(run_dir: Path, draft: bool) -> None:
    info = render_video(run_dir, draft, progress=_print)
    print(f"Video: {run_dir.resolve() / info['videoPath']}")
    print(f"{info['width']}x{info['height']} | {info['probedSeconds']:.1f} s | "
          f"{info['bytes'] / 1e6:.1f} MB | rendered in {info['renderSeconds']:.0f} s")


def _add_plan_options(parser):
    parser.add_argument("--topic", required=True, help="What the video explains")
    parser.add_argument("--audience", default="Curious adults with no background in the topic")
    parser.add_argument("--duration", type=int, default=75,
                        help="Target video length in seconds (30-600; over 180 is planned chapter by chapter)")
    parser.add_argument("--reference", type=Path, help="Facts file the script must stay within")
    parser.add_argument("--reference-url",
                        help="Web page the script must stay within; its text is saved as reference.md in the run")
    parser.add_argument("--review", action="store_true",
                        help="Have Claude review the plan and rewrite weak lines before narration")


def _add_voice_options(parser):
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--offline", action="store_true", help="Use cached model files; never download weights.")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Plan explainer-video scenes and narration.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("validate", help="Check a scene-plan JSON file.")
    check.add_argument("--plan", type=Path, required=True, help="Scene-plan JSON file")
    schema = sub.add_parser("schema", help="Write the ScenePlan JSON Schema.")
    schema.add_argument("--output", type=Path, default=Path("schemas/scene-plan.schema.json"))
    plan = sub.add_parser("plan", help="Write a scene plan for a topic with the Claude API.")
    _add_plan_options(plan)
    plan.add_argument("--out", type=Path, required=True, help="New directory for this run")
    narrate = sub.add_parser("narrate", help="Generate narration for every line of a scene plan.")
    narrate.add_argument("--plan", type=Path, required=True, help="Scene-plan JSON file")
    narrate.add_argument("--out", type=Path, required=True, help="New directory for this run")
    _add_voice_options(narrate)
    review = sub.add_parser("review", help="Review a run's scene plan with the Claude API before narration.")
    review.add_argument("--run", type=Path, required=True, help="Run directory with scene-plan.json")
    timeline = sub.add_parser("timeline", help="Write the frame timeline, aligned narration and subtitles.")
    timeline.add_argument("--run", type=Path, required=True, help="Narrated run directory")
    render = sub.add_parser("render", help="Render a narrated run to MP4 with Remotion (needs Node.js).")
    render.add_argument("--run", type=Path, required=True, help="Narrated run directory")
    render.add_argument("--draft", action="store_true", help="Render at half size (960x540), for quick checks")
    evaluation = sub.add_parser("evaluate", help="Plan and review a list of topics and summarize the results.")
    evaluation.add_argument("--topics", type=Path, required=True,
                            help="JSON list of {topic, audience, duration}, such as fixtures/evaluation-topics.json")
    evaluation.add_argument("--out", type=Path, required=True, help="New directory for the evaluation")
    evaluation.add_argument("--narrate", action="store_true",
                            help="Also voice plans of up to 180 seconds to measure real speech length")
    _add_voice_options(evaluation)
    preview = sub.add_parser("preview", help="Rebuild preview.html for a narrated run.")
    preview.add_argument("--run", type=Path, required=True, help="Run directory with audio-manifest.json")
    run = sub.add_parser("run", help="Topic -> scene plan -> narration (-> video) in one run directory.")
    _add_plan_options(run)
    run.add_argument("--out", type=Path, required=True, help="New directory for this run")
    _add_voice_options(run)
    run.add_argument("--render", action="store_true", help="Also render video.mp4 with Remotion (needs Node.js)")
    run.add_argument("--draft", action="store_true", help="With --render: half size (960x540), for quick checks")
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            return _validate(args.plan)
        if args.command == "schema":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(schema_text(), encoding="utf-8", newline="\n")
            print(f"Wrote {args.output}")
            return 0
        if args.command == "plan":
            _write_plan(args)
            return 0
        if args.command == "review":
            reference_text = _reference_for(args.run)
            load_env_file()
            _review(args.run, _client(), reference_text)
            return 0
        if args.command == "timeline":
            out = write_timeline(args.run)
            data = json.loads((out / "timeline.json").read_text(encoding="utf-8"))
            print(f"Timeline: {out.resolve() / 'timeline.json'}")
            print(f"{len(data['scenes'])} scenes | {data['durationInFrames']} frames at {data['fps']} fps | "
                  f"{data['durationSeconds']:.1f} s | narration.wav, subtitles.srt, subtitles.vtt")
            return 0
        if args.command == "render":
            _render(args.run, args.draft)
            return 0
        if args.command == "evaluate":
            topics = json.loads(args.topics.read_text(encoding="utf-8"))
            load_env_file()
            results = evaluate(topics, args.out, _client(), args.narrate, _engine_factory(args.offline, args.threads),
                               args.offline, args.threads, progress=_print)
            summary = results["summary"]
            print(f"Results: {args.out.resolve() / 'results.md'}")
            print(f"{summary['planned']} of {summary['topics']} planned | first request passed "
                  f"{summary['firstRequestPassRate']:.0%} | API about ${summary['costUsd']:.2f}")
            return 0
        if args.command == "preview":
            print(f"Preview: {build_preview(args.run).resolve()}")
            return 0
        if args.command == "narrate":
            scene_plan = load_plan(args.plan)
            _new_output(args.out)
            args.out.mkdir(parents=True)
            (args.out / "scene-plan.json").write_text(dump_plan(scene_plan), encoding="utf-8", newline="\n")
            return _narrate(args, scene_plan)
        return _narrate(args, _write_plan(args))
    except (Exception, KeyboardInterrupt) as exc:
        print(f"ERROR: {exc or 'Interrupted'}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
