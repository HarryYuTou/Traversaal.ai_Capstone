"""Level 1 scorecard: success rate and quality score for finished video runs.

Every automatic check reads a file the run already wrote (llm-response.json,
review.json, audio-manifest.json, video-info.json), so nothing is planned,
voiced or rendered again. Human quality comes from a ratings CSV. The
definitions and the rubric are in docs/QUALITY_SCORECARD.md.
"""

import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean

from .evaluate import CRITERIA as REVIEW_CRITERIA
from .planner import write_json

HUMAN_CRITERIA = ("accuracy", "clarity", "visuals", "audio", "sync")
RATING_COLUMNS = ("run", "rater", *HUMAN_CRITERIA, "notes")
MIN_SECONDS = 420          # Level 1 asks for complete seven-minute videos; used when a run records no minimum.
QUALITY_BAR = 3.5          # Mean of the five criterion averages.
CRITERION_FLOOR = 3.0      # No single criterion may average below this.
LENGTH_TOLERANCE = 0.2     # Probed MP4 length vs. the timeline, as render_video checks it.


class ScorecardError(ValueError):
    pass


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def run_minimum(spec: dict, min_seconds: float | None = None) -> tuple[float, str]:
    """The shortest length this run must reach, and where that number came from.

    An explicit min_seconds holds every run to the same length. Otherwise a run
    keeps the minimumDurationSec it was generated with (0 means it had none), and
    runs from before that field existed fall back to the Level 1 length.
    """
    if min_seconds is not None:
        return min_seconds, "command line"
    if spec.get("minimumDurationSec") is not None:
        return spec["minimumDurationSec"], "run"
    return MIN_SECONDS, "default"


def extension_summary(extension: dict | None) -> dict | None:
    """Accepted content extensions: how many, and the narrated length before and after them."""
    if not extension:
        return None
    rounds = extension.get("rounds", [])
    # Records from before the "promoted" flag mark an accepted round by its afterSeconds.
    promoted = [item for item in rounds if item.get("promoted", "afterSeconds" in item)]
    return {"status": extension.get("status"), "rounds": len(promoted),
            "beforeSeconds": promoted[0].get("beforeSeconds") if promoted else None,
            "afterSeconds": promoted[-1].get("afterSeconds") if promoted else None}


def run_checks(run_dir: Path, min_seconds: float | None = None) -> dict:
    """Stage results, length, cost and reviewer scores for one run directory.

    min_seconds overrides every run's own minimum; see run_minimum.
    """
    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise ScorecardError(f"{run_dir} is not a run directory.")
    spec = _read(run_dir / "project-spec.json") or {}
    plan = _read(run_dir / "scene-plan.json") or {}
    llm = _read(run_dir / "llm-response.json")
    review = _read(run_dir / "review.json")
    extension = _read(run_dir / "duration-extension.json")
    manifest = _read(run_dir / "audio-manifest.json")
    info = _read(run_dir / "video-info.json")
    failures = []

    # A run without llm-response.json voiced a saved plan: a reproduction, not a planning attempt.
    live = llm is not None
    if not live:
        stages = {"plan": "reproduction"}
    elif llm.get("status") == "completed":
        stages = {"plan": "passed"}
    else:
        stages = {"plan": "failed"}
        failures.append(f"plan: {llm.get('error') or llm.get('status', 'unknown')}")

    if review is None:
        stages["review"] = "not requested"
    elif review.get("status") == "completed":
        stages["review"] = "passed"
    else:
        stages["review"] = "failed"
        failures.append(f"review: {review.get('error') or review.get('status', 'unknown')}")

    if manifest is None:
        stages["narration"] = "missing"
    elif manifest.get("status") == "completed":
        stages["narration"] = "passed"
    else:
        stages["narration"] = "failed"
        failures.append("narration: " + (manifest.get("error") or "did not complete"))

    seconds = info.get("probedSeconds") if info else None
    if info is None:
        stages["render"] = "missing"
    elif info.get("draft"):
        stages["render"] = "failed"
        failures.append("render: only a draft (960x540) was rendered")
    elif abs(info["probedSeconds"] - info["expectedSeconds"]) > LENGTH_TOLERANCE:
        stages["render"] = "failed"
        failures.append(f"render: MP4 lasts {info['probedSeconds']:.2f} s but the timeline is "
                        f"{info['expectedSeconds']:.2f} s")
    else:
        stages["render"] = "passed"
    for stage in ("narration", "render"):
        if stages[stage] == "missing" and not failures:
            failures.append(f"{stage}: no output; the run stopped before this stage")

    minimum, minimum_source = run_minimum(spec, min_seconds)
    length_ok = seconds is not None and seconds >= minimum
    if seconds is not None and not length_ok:
        failures.append(f"length: {seconds:.1f} s is under the {minimum:.0f} s minimum")

    # The animation report is written before rendering, so read it even when the render did not finish.
    motion = (info or {}).get("motionInspection") or _read(run_dir / "motion-inspection.json")
    # A newer failed preflight must not be hidden by metadata from an older render.
    spatial_report = _read(run_dir / "spatial-inspection.json")
    spatial = spatial_report if spatial_report is not None else (info or {}).get("spatialInspection")
    spatial_status = spatial.get("status", "unknown") if spatial is not None else None
    spatial_ok = spatial is None or spatial_status == "spatial-checks-passed"
    if not spatial_ok:
        failures.append(f"spatial: {spatial_status}; contact or camera checks did not pass")
    review_cost = (review or {}).get("estimatedCostUsd", 0.0)
    if extension:
        if "initialReviewCostUsd" in extension:
            review_cost = extension["initialReviewCostUsd"] + extension.get("estimatedCostUsd", 0.0)
        else:
            # Older extension records include only generation costs. The current
            # review plus archived/candidate reviews account for each review once.
            review_cost += extension.get("estimatedCostUsd", 0.0)
            for item in extension.get("rounds", []):
                folder = item.get("originalArtifacts") or item.get("directory")
                if folder:
                    review_cost += (_read(run_dir / folder / "review.json") or {}).get("estimatedCostUsd", 0.0)
    checks = {
        "run": run_dir.name, "path": str(run_dir),
        "topic": spec.get("topic") or plan.get("title") or run_dir.name,
        "title": plan.get("title"), "targetSeconds": spec.get("targetDurationSec"),
        "live": live, "stages": stages, "seconds": seconds, "lengthOk": length_ok,
        "minSeconds": minimum, "minimumSource": minimum_source, "extension": extension_summary(extension),
        "motionInspection": motion["status"] if motion else None,
        "spatialInspection": spatial_status,
        "costUsd": round((llm or {}).get("estimatedCostUsd", 0.0) + review_cost, 4),
        "reviewScores": review["scores"] if review and review.get("status") == "completed" else None,
        "failures": failures,
    }
    checks["automaticPass"] = (stages["plan"] in ("passed", "reproduction")
                               and stages["review"] in ("passed", "not requested")
                               and stages["narration"] == "passed" and stages["render"] == "passed"
                               and length_ok and spatial_ok)
    return checks


def _score(value: str, where: str):
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError:
        raise ScorecardError(f"{where}: {value!r} is not a whole number from 1 to 5.") from None
    if not 1 <= number <= 5:
        raise ScorecardError(f"{where}: {number} is not between 1 and 5.")
    return number


def read_ratings(path: Path, runs: set[str]) -> dict[str, list[dict]]:
    """Ratings grouped by run name. Unknown runs, bad scores and repeated raters are errors."""
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in ("run", "rater", *HUMAN_CRITERIA) if name not in (reader.fieldnames or [])]
        if missing:
            raise ScorecardError(f"{path} is missing columns: {', '.join(missing)}.")
        ratings: dict[str, list[dict]] = {}
        seen = set()
        for line, row in enumerate(reader, start=2):
            run, rater = (row.get("run") or "").strip(), (row.get("rater") or "").strip()
            scores = {name: _score(row.get(name), f"{path} line {line}, {name}") for name in HUMAN_CRITERIA}
            if not run and not rater and all(value is None for value in scores.values()):
                continue  # A blank line in the sheet.
            if run not in runs:
                raise ScorecardError(f"{path} line {line}: run {run!r} is not one of the runs given.")
            if all(value is None for value in scores.values()):
                continue  # An unfilled template row.
            if not rater:
                raise ScorecardError(f"{path} line {line}: add the rater's name.")
            if (run, rater.casefold()) in seen:
                raise ScorecardError(f"{path} line {line}: {rater} already rated {run}.")
            seen.add((run, rater.casefold()))
            ratings.setdefault(run, []).append({"rater": rater, "scores": scores,
                                                "notes": (row.get("notes") or "").strip()})
    return ratings


def quality(ratings: list[dict]) -> dict:
    """Criterion averages over the raters who scored them; complete only if every criterion has a score."""
    averages = {}
    for name in HUMAN_CRITERIA:
        values = [rating["scores"][name] for rating in ratings if rating["scores"][name] is not None]
        averages[name] = round(mean(values), 2) if values else None
    complete = all(value is not None for value in averages.values())
    score = round(mean(averages.values()), 2) if complete else None
    return {"raters": [rating["rater"] for rating in ratings], "criteria": averages, "score": score,
            "complete": complete,
            "meetsBar": complete and score >= QUALITY_BAR and min(averages.values()) >= CRITERION_FLOOR,
            "notes": [f"{rating['rater']}: {rating['notes']}" for rating in ratings if rating["notes"]]}


def verdict(run: dict) -> str:
    if not run["automaticPass"]:
        return "failed"
    if not run["live"]:
        return "reproduction"
    if not run["quality"]["complete"]:
        return "needs rating"
    return "accepted" if run["quality"]["meetsBar"] else "below quality bar"


def _mean(values):
    values = [value for value in values if value is not None]
    return round(mean(values), 2) if values else None


def summarize(runs: list[dict]) -> dict:
    live = [run for run in runs if run["live"]]
    successes = [run for run in live if run["automaticPass"]]
    rated = [run for run in live if run["quality"]["complete"]]  # Headline quality covers live runs only.
    reviewed = [run for run in runs if run["reviewScores"]]
    minimums = {run["minSeconds"] for run in runs}
    return {
        "runs": len(runs), "liveAttempts": len(live), "reproductions": len(runs) - len(live),
        "automaticSuccesses": len(successes),
        "successRate": round(len(successes) / len(live), 3) if live else None,
        "accepted": sum(run["verdict"] == "accepted" for run in runs),
        "meanQualityScore": _mean(run["quality"]["score"] for run in rated),
        "humanCriteria": {name: _mean(run["quality"]["criteria"][name] for run in rated) for name in HUMAN_CRITERIA},
        "reviewCriteria": {name: _mean(run["reviewScores"].get(name) for run in reviewed) for name in REVIEW_CRITERIA}
                          if reviewed else None,
        "meanSeconds": _mean(run["seconds"] for run in runs),
        "costUsd": round(sum(run["costUsd"] for run in runs), 2),
        # One shared minimum, or None when runs were generated with different minimums.
        "minSeconds": minimums.pop() if len(minimums) == 1 else None,
        "extendedRuns": sum(bool(run["extension"] and run["extension"]["rounds"]) for run in runs),
        "qualityBar": QUALITY_BAR, "criterionFloor": CRITERION_FLOOR,
    }


def build(run_dirs: list[Path], ratings_path: Path | None = None, min_seconds: float | None = None) -> dict:
    """min_seconds holds every run to one minimum; None uses each run's own (see run_minimum)."""
    if not run_dirs:
        raise ScorecardError("Give at least one run directory.")
    runs = [run_checks(path, min_seconds) for path in run_dirs]
    names = [run["run"] for run in runs]
    repeated = sorted({name for name in names if names.count(name) > 1})
    if repeated:
        raise ScorecardError("Run directory names must be unique: " + ", ".join(repeated))
    ratings = read_ratings(ratings_path, set(names)) if ratings_path else {}
    for run in runs:
        run["quality"] = quality(ratings.get(run["run"], []))
        run["verdict"] = verdict(run)
    return {"createdAt": datetime.now(timezone.utc).isoformat(), "ratings": str(ratings_path) if ratings_path else None,
            "summary": summarize(runs), "runs": runs}


def _clock(seconds):
    if seconds is None:
        return "—"
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def _number(value, digits=2):
    return "—" if value is None else f"{value:.{digits}f}"


def _minimum(seconds):
    return "none" if seconds == 0 else _clock(seconds)


def _extension(extension):
    if not extension:
        return "—"
    if extension["rounds"]:
        rounds = "round" if extension["rounds"] == 1 else "rounds"
        return (f"{_clock(extension['beforeSeconds'])} → {_clock(extension['afterSeconds'])} "
                f"({extension['rounds']} {rounds})")
    return "not needed" if extension["status"] == "passed" else (extension["status"] or "—")


def markdown(results: dict) -> str:
    summary = results["summary"]
    rate = ("—" if summary["successRate"] is None else
            f"{summary['automaticSuccesses']} of {summary['liveAttempts']} ({summary['successRate']:.0%})")
    lines = [
        "# Level 1 scorecard", "",
        f"- **Success rate (live attempts):** {rate}",
        f"- **Accepted videos:** {summary['accepted']} (automatic success, live, quality score ≥ "
        f"{summary['qualityBar']} and every criterion ≥ {summary['criterionFloor']})",
        f"- **Mean human quality score (rated live runs):** {_number(summary['meanQualityScore'])} / 5",
        f"- **Reproductions listed but not counted:** {summary['reproductions']}",
        f"- **Mean length:** {_clock(summary['meanSeconds'])} ("
        + ("minimum set per run" if summary["minSeconds"] is None else
           "no minimum" if summary["minSeconds"] == 0 else f"minimum {_clock(summary['minSeconds'])}") + ")",
        f"- **Runs lengthened by a content extension:** {summary['extendedRuns']}",
        f"- **API cost recorded in the runs:** ${summary['costUsd']:.2f}", "",
        "| # | Run | Topic | Length | Minimum | Extension | Plan | Review | Narration | Render | Motion check | Spatial check | "
        "Human: accuracy, clarity, visuals, audio, sync | Quality | Reviewer (script) | Cost | Verdict |",
        "| ---: | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for number, run in enumerate(results["runs"], start=1):
        stages = run["stages"]
        human = ", ".join("—" if value is None else f"{value:g}" for value in run["quality"]["criteria"].values())
        reviewer = _number(mean(run["reviewScores"].values())) if run["reviewScores"] else "—"
        lines.append(
            f"| {number} | `{run['run']}` | {run['topic']} | {_clock(run['seconds'])} | "
            f"{_minimum(run['minSeconds'])} | {_extension(run['extension'])} | {stages['plan']} | "
            f"{stages['review']} | {stages['narration']} | {stages['render']} | {run['motionInspection'] or '—'} | "
            f"{run['spatialInspection'] or '—'} | "
            f"{human} | {_number(run['quality']['score'])} | {reviewer} | ${run['costUsd']:.2f} | "
            f"**{run['verdict']}** |")
    problems = [(run["run"], reason) for run in results["runs"] for reason in run["failures"]]
    if problems:
        lines += ["", "## Failed checks", ""] + [f"- `{name}`: {reason}" for name, reason in problems]
    notes = [(run["run"], note) for run in results["runs"] for note in run["quality"]["notes"]]
    if notes:
        lines += ["", "## Rater notes", ""] + [f"- `{name}` {note}" for name, note in notes]
    lines += ["", "Human criteria are defined in docs/QUALITY_SCORECARD.md. The reviewer column is the mean of "
              "Claude's five script scores before narration and is not part of the quality score."]
    return "\n".join(lines) + "\n"


def csv_rows(results: dict) -> list[dict]:
    rows = []
    for run in results["runs"]:
        row = {"run": run["run"], "topic": run["topic"], "live": run["live"],
               "seconds": run["seconds"], "min_seconds": run["minSeconds"],
               "minimum_source": run["minimumSource"],
               "extension_rounds": (run["extension"] or {}).get("rounds"),
               "seconds_before_extension": (run["extension"] or {}).get("beforeSeconds"),
               **{f"stage_{name}": value for name, value in run["stages"].items()},
               "motion_check": run["motionInspection"], "spatial_check": run["spatialInspection"],
               "automatic_pass": run["automaticPass"],
               **{f"human_{name}": run["quality"]["criteria"][name] for name in HUMAN_CRITERIA},
               "quality_score": run["quality"]["score"], "raters": len(run["quality"]["raters"]),
               **{f"review_{name}": (run["reviewScores"] or {}).get(name) for name in REVIEW_CRITERIA},
               "cost_usd": run["costUsd"], "verdict": run["verdict"], "failures": "; ".join(run["failures"])}
        rows.append(row)
    return rows


def write_report(results: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    if out_dir.exists():
        raise FileExistsError(f"Output already exists: {out_dir}. Choose a new output directory.")
    out_dir.mkdir(parents=True)
    write_json(out_dir / "scorecard.json", results)
    (out_dir / "scorecard.md").write_text(markdown(results), encoding="utf-8", newline="\n")
    rows = csv_rows(results)
    with (out_dir / "scorecard.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return out_dir


def write_template(run_dirs: list[Path], path: Path) -> Path:
    """One empty ratings row per run; raters copy rows to add themselves."""
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} already exists. Choose a new file name.")
    for run_dir in run_dirs:
        if not Path(run_dir).is_dir():
            raise ScorecardError(f"{run_dir} is not a run directory.")
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(RATING_COLUMNS)
        for run_dir in run_dirs:
            writer.writerow([Path(run_dir).name, "", "", "", "", "", "", ""])
    return path
