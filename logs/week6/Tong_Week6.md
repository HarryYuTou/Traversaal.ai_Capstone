# Tong - Week 6 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** November 15, 2026  
**Branch:** `feat/scorecard-run-minimum` (merged into `main` through PR #20)  
**Focus:** A scorecard that checks each video against the length it was generated for, and shows which videos needed a content extension

## Contribution to the capstone

Rebecca's Level 1 runs produced four accepted seven-minute videos, and Harry's
week-four work added a measured minimum length with automatic content
extension. The scorecard had not caught up with either: it still held every
run to a fixed 420 seconds and did not show whether a video reached its length
only through an extension. This was an open item in my week-four log.

```text
Topic -> Script -> Narration -> (Extension) -> Render -> Scorecard -> Level 1 acceptance
                                                         ^ this week's work
```

None of this work calls the Claude API. I built it with Claude Code.

## Completed work

### Each run is checked against its own minimum length

- The scorecard now reads `minimumDurationSec` from each run's
  `project-spec.json`, the minimum the run was generated with. New runs with a
  target of 420 seconds or more record 420 by default, so Level 1 runs are
  still checked against seven minutes.
- `0` means the run had no minimum. A one-minute demo made with
  `--minimum-duration 0` no longer fails the length check.
- Runs from before that field existed are still checked against 420 seconds,
  so older runs keep their previous result.
- `--min-seconds N` now holds **every** run to N seconds, whatever it
  recorded. For the Level 1 report, `--min-seconds 420` guarantees that no run
  generated with a lower minimum counts as a seven-minute video.
- `scorecard.json` records the minimum used for each run and where it came
  from: `run`, `default` or `command line`.

### Content extensions are visible in the report

- New **Minimum** column: the length each run was checked against (`none` for
  no minimum).
- New **Extension** column: the narrated length before and after the accepted
  extension rounds, for example `6:52 → 7:06 (1 round)`; `not needed` when the
  first narration was already long enough; the record's status, such as
  `failed`, when no round was accepted. Failed attempts are not counted as
  rounds, and older extension records without the `promoted` flag are read
  correctly.
- The summary adds **Runs lengthened by a content extension**. The CSV adds
  `min_seconds`, `minimum_source`, `extension_rounds` and
  `seconds_before_extension`.
- This makes Rebecca's extension findings easier to spot: a video that only
  just reached 420 seconds after an extension, such as `l1r-02` at 425.8 s or
  `l1r-04b` with scenes added inside the recap, now shows its extension in the
  report, so raters know to check the added scenes.

### Documentation

`docs/QUALITY_SCORECARD.md` has a new section, "Which minimum length applies",
covering the per-run minimum, the `--min-seconds` override for Level 1 and how
to read the Extension column.

### Project status check

Before starting, I compared `main` with my week-four log. Since October 28 the
team merged PRs #14 to #19: Charles's sketch style and staged rooms, Harry's
frame-to-frame consistency, object actions, model-authored objects and contact
constraints, and Rebecca's week-four log with the Level 1 acceptance runs.
Harry's week-six work also added a spatial check to the scorecard; PR #20 was
built on top of it and keeps that check unchanged.

## Validation results

| Check | Result |
| --- | --- |
| Python tests | 385 passed: the 380 on `main` plus 5 new scorecard tests (a demo with no minimum, a 120-second test minimum, a legacy run, the command-line override, old and new extension records, report columns and CSV fields) |
| Formatting | `git diff --check` passed |
| Real runs | The new scorecard ran on two of my saved local runs (`tong-review-queue-7min`, `tong-concurrency-check`); the report was written and the new columns showed the expected values |
| After merging PR #20 | `main` is identical to the tested commit, and the scorecard tests pass again |

Renderer and frontend code did not change, so their suites were not rerun.
Rebecca's `l1r-*` run folders are on her computer, so the new report has not
yet been produced for her four accepted videos.

## Current scope and remaining work

- **Fifth Level 1 video.** Four of five are accepted. One more live run on a
  non-AI topic is needed, which requires API credit.
- **Second rater.** Rebecca's four videos have one rater each. I can rate them
  if she shares the videos or run folders.
- **Rerun the scorecard on Rebecca's runs** with `--min-seconds 420`, to show
  the Minimum and Extension columns for the accepted videos.
- **Duration extension.** Rebecca found that extension scenes can land inside
  the recap and that a scene revision can fail on preserved objects (`l1r-05`).
  The scorecard now shows where an extension happened, but the extension step
  itself is unchanged.
- **Web studio.** The browser workspace still renders at Remotion's default
  concurrency.
- **Public deployment** has not been started.

## How to run

```bash
.venv/bin/python -m capstone_script scorecard --runs runs/l1-* --ratings ratings.csv --out runs/l1-scorecard
.venv/bin/python -m capstone_script scorecard --runs runs/l1-* --ratings ratings.csv --min-seconds 420 --out runs/l1-scorecard-strict   # Level 1: hold every run to 7:00
```

Related documentation: [quality scorecard guide](../../docs/QUALITY_SCORECARD.md).
