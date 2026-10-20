# Tong - Week 3 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 20, 2026  
**Branch:** `feat/quality-scorecard` (merged into `main` through PR #9)  
**Focus:** A shared way to measure Level 1 success and quality, and a full review of the first seven-minute video

## Contribution to the capstone

Level 1 acceptance asks for five seven-minute videos on non-AI topics, with a
**success rate** and a **quality score**. The team had no shared definition of
either. Harry produced the first seven-minute video this week (PR #8), so I
built the measuring side: a scorecard command, a written rubric, and a first
review that puts Harry's video through both.

```text
Topic -> Script -> Narration -> Video -> Scorecard (success + quality) -> Level 1 acceptance
                                         ^ this week's work
```

None of this work calls the Claude API, so it cost nothing to build or run. It
reads the files each run already writes. Teammates who have API access can
produce the remaining videos, and the scorecard turns their runs into the
acceptance numbers. I built it with Claude Code.

## Completed work

### Scorecard command (`python -m capstone_script scorecard`)

- New `capstone_script/scorecard.py`. For each run directory, it reads
  `llm-response.json`, `review.json`, `audio-manifest.json`, `video-info.json`
  and `motion-inspection.json`. It decides whether planning, the optional
  review, narration and a full-size render all finished, whether the MP4 length
  matches its timeline, and whether the video lasts at least 7:00.
- The **success rate** is automatic successes divided by live attempts. Runs
  that only rebuild a saved plan are listed as **reproductions** and are left
  out, so they cannot inflate the rate. Failed attempts are kept and reported
  with the stage that failed.
- Human **ratings** come from a CSV, one row per rater per run. The command
  rejects unknown runs, scores outside 1–5, a missing rater name and
  repeated raters.
- Each run gets a verdict: accepted, needs rating, below quality bar,
  reproduction, or failed.
- The command writes `scorecard.md` for team updates, `scorecard.csv` for
  Excel or Sheets, and `scorecard.json` with every number. `--template` writes
  an empty ratings sheet for a set of runs.

### Rubric (`docs/QUALITY_SCORECARD.md`)

- Five human criteria, each scored 1–5 with a description of what 1, 3 and 5
  look like: accuracy, clarity, visuals, audio and sync.
- The quality score is the mean of the five criterion averages. The proposed
  bar is 3.5 with no criterion below 3.0; the team can change it in one place.
- Claude's own script-review scores are shown next to the human scores but are
  never mixed into the quality score.
- Step-by-step commands for whoever produces the five videos.

### Review of Harry's seven-minute video (`docs/reviews/2026-10-20-queues-7min.md`)

- Rebuilt "Why Queues Grow, Linger, and Clear" locally from Harry's saved plan
  with no API call. It matched his record exactly: 93 lines, 407.8 s of speech,
  13,034 frames and 434.475 s (7:14) at 1080p.
- Checked every count in the script line by line, for example
  4 + 2 − 1 = 5 and 5 + 3 − 2 = 6 (versus 7 with one desk). There were no
  errors.
- Rendered and inspected 16 still frames covering all 14 scenes, plus the
  automatic animation report, which passed.
- Watched the whole video with sound and rated it **4.80 / 5**: accuracy 5,
  clarity 5, visuals 4, audio 5, sync 5. Claude Code turned my answers about
  sound, sync, visuals and clarity into scores, and I confirmed them.
- Visual findings and suggested fixes for the next version:
  - the action sits in the right half of the frame;
  - the on-screen counter is hidden for most of the parcel chapter;
  - the definition scene switches to the older slide style;
  - the desk labels at 5:47 sit between the two desks;
  - desk names and colours change between scenes.

### Rendering on a laptop

The full render needed three attempts on my 8 GB MacBook:

1. The first ran out of disk space during the final audio merge.
2. The second crashed Remotion's headless browser at frame 10,834, with disk
   space no longer the issue.
3. The third, with the same code and Remotion limited to two browser tabs,
   finished in 18 minutes.

The review records this so teammates rendering the five videos on laptops keep
at least 4 GB of disk free and lower the render concurrency on 8 GB machines.

### Project status check

At the start of the week I compared `main` with the remaining Level 1 work and
ran every test suite after Harry's PR #8 (231 Python, 22 frontend and 36
renderer tests passed). This confirmed that the login and history from week 2
still worked with the new motion scenes.

## Validation results

| Check | Result |
| --- | --- |
| Python tests | 244 passed, including 13 new scorecard tests: stage failures, reproductions, ratings validation, verdicts, report files and the command line |
| Frontend tests | 22 passed |
| Renderer tests | 36 passed |
| Real run through the scorecard | Harry's rebuilt video passed every automatic check: narration, full render, 7:14 against the 7:00 minimum, and the animation check. It scored 4.80 / 5 |
| After merging PR #9 | `main` is identical to the tested branch, and all three suites pass again |

## Current scope and remaining work

- **Five seven-minute videos.** Four or five more seven-minute videos on
  non-AI topics still need to be produced, through a live Claude run with
  an API key. Harry's queue video was produced live on his machine. If its run
  folder is shared, it can be scored as a live attempt instead of my
  reproduction.
- **More raters.** Each video should have at least one more rater, so the
  quality score does not rest on one person.
- **Render concurrency.** A `--concurrency` option on `render` would make
  laptop renders reliable without a workaround.
- **Visual fixes.** The fixes listed in the review are for whoever works on
  the motion scenes next.

## How to run

```bash
.venv/bin/python -m capstone_script scorecard --runs runs/l1-* --template ratings.csv
.venv/bin/python -m capstone_script scorecard --runs runs/l1-* --ratings ratings.csv --out runs/l1-scorecard
```

Related documentation: [quality scorecard](../../docs/QUALITY_SCORECARD.md) and
[queue video review](../../docs/reviews/2026-10-20-queues-7min.md).
