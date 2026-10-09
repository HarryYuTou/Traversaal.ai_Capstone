"""Planner evaluation: plan and review a list of topics and summarize how the script stage behaves.

Each topic gets its own run directory, written by the same functions as the
`plan --review` command, so every number comes from the files a normal run
keeps. With `narrate`, videos planned in one request are also voiced, which
measures real speech length against the target. A topic that fails is
recorded with its error and the batch moves on.
"""

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean

from .narrate import narrate_plan
from .planner import MODEL, PROMPT_VERSION, SPEECH_SHARE, make_spec, slug, word_range, write_json, write_plan_run
from .review import PROMPT_VERSION as REVIEW_PROMPT_VERSION, write_review
from .scene_plan import load_plan, summarize, text_words

CRITERIA = ("clarity", "flow", "accuracy", "engagement", "audienceFit")


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run_metrics(run_dir: Path) -> dict:
    """Everything worth comparing about one run, read from the files it wrote."""
    run_dir = Path(run_dir)
    spec = _read(run_dir / "project-spec.json")
    llm = _read(run_dir / "llm-response.json") or {"status": "not started", "attempts": []}
    review = _read(run_dir / "review.json")
    manifest = _read(run_dir / "audio-manifest.json")
    steps = Counter(attempt["step"] for attempt in llm["attempts"])
    metrics = {"run": run_dir.name, "topic": spec["topic"], "audience": spec["audience"],
               "targetSeconds": spec["targetDurationSec"], "mode": spec.get("planMode", "single"),
               "planStatus": llm["status"], "requests": len(llm["attempts"]),
               "repairs": sum(count - 1 for count in steps.values()),
               "planCostUsd": llm.get("estimatedCostUsd", 0.0),
               "planSeconds": round(sum(attempt["latencyMs"] for attempt in llm["attempts"]) / 1000, 1)}
    if llm["status"] != "completed":
        metrics["error"] = llm.get("error")
        return metrics
    draft_path = run_dir / ("scene-plan.draft.json" if (run_dir / "scene-plan.draft.json").exists()
                            else "scene-plan.json")
    draft, final = load_plan(draft_path), load_plan(run_dir / "scene-plan.json")
    words = [len(text_words(line.text)) for scene in final.scenes for line in scene.narration]
    summary = summarize(final)
    _, target, _ = word_range(spec["targetDurationSec"])
    metrics.update(chapters=summary["chapters"], scenes=summary["scenes"], lines=summary["lines"],
                   wordTarget=target, wordsDraft=summarize(draft)["words"], wordsFinal=summary["words"],
                   wordRatio=round(summary["words"] / target, 3), maxLineWords=max(words),
                   templates=dict(Counter(scene.template for scene in final.scenes)))
    if review is not None:
        metrics.update(reviewStatus=review["status"], reviewCostUsd=review.get("estimatedCostUsd", 0.0))
        if review["status"] == "completed":
            metrics.update(scores=review["scores"], linesRewritten=len(review["changes"]),
                           issues=dict(Counter(issue["category"] for issue in review["issues"])))
    if manifest is not None and manifest.get("status") == "completed":
        metrics.update(speechSeconds=round(manifest["totalSpeechSeconds"], 1),
                       speechTargetSeconds=round(spec["targetDurationSec"] * SPEECH_SHARE, 1),
                       previewSeconds=round(manifest["preview"]["durationSeconds"], 1))
    return metrics


def aggregate(runs: list[dict]) -> dict:
    planned = [run for run in runs if run["planStatus"] == "completed"]
    reviewed = [run for run in planned if "scores" in run]
    voiced = [run for run in planned if "speechSeconds" in run]
    templates = Counter()
    for run in planned:
        templates.update(run["templates"])
    return {
        "topics": len(runs), "planned": len(planned),
        "firstRequestPassRate": round(sum(run["repairs"] == 0 for run in planned) / len(runs), 3) if runs else 0,
        "repairs": sum(run["repairs"] for run in runs),
        "meanWordRatio": round(mean(run["wordRatio"] for run in planned), 3) if planned else None,
        "wordRatioRange": [min(run["wordRatio"] for run in planned), max(run["wordRatio"] for run in planned)]
                          if planned else None,
        "meanScores": {name: round(mean(run["scores"][name] for run in reviewed), 2) for name in CRITERIA}
                      if reviewed else None,
        "linesRewritten": sum(run["linesRewritten"] for run in reviewed),
        "speechToTarget": [round(run["speechSeconds"] / run["speechTargetSeconds"], 3) for run in voiced],
        "templates": dict(templates.most_common()),
        "costUsd": round(sum(run["planCostUsd"] + run.get("reviewCostUsd", 0.0) for run in runs), 2),
        "planSecondsMean": round(mean(run["planSeconds"] for run in planned), 1) if planned else None,
    }


def markdown(results: dict) -> str:
    rows = ["| # | Topic | Target | Mode | Plan | Requests | Words (of target) | Scenes | Templates | "
            "Review: clarity, flow, accuracy, engagement, fit | Rewritten | Speech | Cost |",
            "| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | --- | --- | ---: | ---: | ---: |"]
    for number, run in enumerate(results["runs"], start=1):
        if run["planStatus"] != "completed":
            rows.append(f"| {number} | {run['topic']} | {run['targetSeconds']} s | {run['mode']} | failed | "
                        f"{run['requests']} | | | | | | | ${run['planCostUsd']:.2f} |")
            continue
        scores = ", ".join(str(run["scores"][name]) for name in CRITERIA) if "scores" in run else "—"
        templates = ", ".join(f"{name} {count}" for name, count in sorted(run["templates"].items()))
        speech = f"{run['speechSeconds']} s" if "speechSeconds" in run else "—"
        cost = run["planCostUsd"] + run.get("reviewCostUsd", 0.0)
        result = "first request" if run["repairs"] == 0 else f"{run['repairs']} repair(s)"
        rows.append(f"| {number} | {run['topic']} | {run['targetSeconds']} s | {run['mode']} | {result} | "
                    f"{run['requests']} | {run['wordsFinal']} ({run['wordRatio']:.0%}) | {run['scenes']} | "
                    f"{templates} | {scores} | {run.get('linesRewritten', '—')} | {speech} | ${cost:.2f} |")
    return "\n".join(rows) + "\n"


def evaluate(topics: list[dict], out_dir: Path, client, narrate: bool = False, engine_factory=None,
             offline: bool = False, threads: int = 2, progress=lambda message: None) -> dict:
    """Plan and review every topic into out_dir/<nn-slug>/ and write results.json and results.md."""
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"Output already exists: {out_dir}. Choose a new output directory.")
    out_dir.mkdir(parents=True)
    engine = None

    def shared_engine():
        nonlocal engine
        engine = engine or engine_factory()
        return engine

    runs = []
    for number, item in enumerate(topics, start=1):
        spec, reference_text = make_spec(item["topic"], item["audience"], item["duration"])
        run_dir = out_dir / f"{number:02d}-{slug(item['topic'], 32)}"
        progress(f"[{number}/{len(topics)}] {item['topic']} ({item['duration']} s)")
        try:
            write_plan_run(run_dir, spec, client, reference_text, progress)
            write_review(run_dir, client, reference_text, progress)
            if narrate and spec["planMode"] == "single":
                narrate_plan(load_plan(run_dir / "scene-plan.json"), run_dir, shared_engine, threads=threads,
                             offline=offline, progress=progress)
        except Exception as exc:  # Record the failure and go on to the next topic.
            progress(f"  failed: {type(exc).__name__}: {exc}")
        runs.append(run_metrics(run_dir))
    results = {"createdAt": datetime.now(timezone.utc).isoformat(), "model": MODEL,
               "promptVersions": {"planner": PROMPT_VERSION, "review": REVIEW_PROMPT_VERSION},
               "summary": aggregate(runs), "runs": runs}
    write_json(out_dir / "results.json", results)
    (out_dir / "results.md").write_text(markdown(results), encoding="utf-8", newline="\n")
    return results
