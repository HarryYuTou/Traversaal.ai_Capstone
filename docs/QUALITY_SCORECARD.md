# Level 1 Quality Scorecard

Level 1 acceptance asks for five complete seven-minute videos on non-AI topics,
with a **success rate** and a **quality score**. This guide defines both and
explains how to produce them with `python -m capstone_script scorecard`.

The scorecard makes no API request and renders nothing. It reads the files that
each run already wrote, and a CSV of human ratings.

## What counts as a success

A run is an **automatic success** when every stage finished on its own and the
result has the required length:

| Check | Passes when | Read from |
| --- | --- | --- |
| Plan | The Claude plan completed (repairs inside the run are allowed) | `llm-response.json` |
| Review | The review completed, or no review was requested | `review.json` |
| Narration | Every line was voiced | `audio-manifest.json` |
| Render | A full-size `video.mp4` exists and its probed length matches the timeline within 0.2 s | `video-info.json` |
| Spatial | When spatial evidence exists, its status is `spatial-checks-passed` | `spatial-inspection.json`, or `video-info.json` → `spatialInspection` |
| Length | The video lasts at least 420 seconds (change with `--min-seconds`) | `video-info.json` |

Animation diagnostics (`motion-inspection.json`) are reported but do not fail
a run. A `needs-review` result tells the raters where to look.

Spatial checks for custom objects and explicit contacts are different: a failed
spatial preflight blocks automatic success and appears in the report's Spatial
check column, including when the run stopped before rendering. A current standalone
spatial report takes precedence over an older video's recorded status. Runs with
no spatial report retain the existing checks; the scorecard does not infer a new
failure for legacy runs. Passing spatial checks is evidence of alignment and
framing, not a human animation-quality rating.

The **success rate** is automatic successes divided by live attempts. A live
attempt is a run that started from a topic and called Claude to plan it. Count
every attempt, including ones that failed part-way. Do not delete a failed run
and try again: keep its directory and pass it to the scorecard.

A run that only re-narrates or re-renders a saved plan (for example
`fixtures/scene-plan.process-queue-long.json`) is a **reproduction**. The
scorecard lists it and scores it, but leaves it out of the success rate. It
proves the pipeline can rebuild a video, not that planning works.

A run must also have no hand edits between topic and MP4. The files cannot
prove this, so raters confirm it in the `notes` column if anything was changed.

## Human quality rating

Each rater watches the **whole** video at normal speed with sound, then gives
each criterion a whole number from 1 to 5. Leave a cell empty if you did not
judge that criterion; do not guess.

| Criterion | 5 | 3 | 1 |
| --- | --- | --- | --- |
| `accuracy` | Every claim checked is correct; simplifications are fair | Minor slips or one unclear simplification | A wrong central claim, or several errors |
| `clarity` | A newcomer in the stated audience could follow and retell it | Mostly followable; some jumps or jargon | Hard to follow; key steps missing |
| `visuals` | Pictures show what the narration says; nothing overlaps, clips or sits still too long | Mostly matches; some static or busy moments | Visuals contradict or ignore the narration, or layout breaks |
| `audio` | Pronunciation, pace and music are comfortable throughout | A few mispronunciations or awkward pauses | Hard to listen to; words missing or garbled |
| `sync` | Subtitles, highlights and motion change with the voice | Occasional drift or late changes | Often out of step |

Use 2 and 4 for in-between cases. Write the reason for any score of 3 or less
in `notes`, with a time stamp such as `03:12 subtitle covers the queue`.

A run's **quality score** is the mean of its five criterion averages, where
each criterion is averaged over the raters who scored it. A run **meets the
quality bar** when its quality score is at least 3.5 and no criterion averages
below 3.0. The team can change the bar; the thresholds are at the top of
`capstone_script/scorecard.py`.

The Claude reviewer's scores (`clarity`, `flow`, `accuracy`, `engagement`,
`audienceFit`, also 1–5) judge the **script** before narration. The scorecard
shows them next to the human scores but never mixes the two.

A run is **accepted** when it is an automatic success, it is a live attempt,
and it meets the quality bar.

## How to run it

1. Produce each video with the normal command, in its own new directory, for
   example:

   ```bash
   .venv/bin/python -m capstone_script run --topic "How do vaccines train the immune system?" --duration 420 --review --render --share --out runs/l1-01-vaccines
   ```

2. Write a ratings sheet for the runs:

   ```bash
   .venv/bin/python -m capstone_script scorecard --runs runs/l1-* --template ratings.csv
   ```

   This writes one row per run. Copy a row for each additional rater. The
   columns are `run, rater, accuracy, clarity, visuals, audio, sync, notes`.

3. After the raters fill it in, build the report:

   ```bash
   .venv/bin/python -m capstone_script scorecard --runs runs/l1-* --ratings ratings.csv --out runs/l1-scorecard
   ```

   The report directory gets `scorecard.md` for the team update,
   `scorecard.csv` to open in Excel or Sheets, and `scorecard.json` with every
   number. The command refuses to overwrite an existing directory.

## Reading the report

`scorecard.md` starts with the success rate, the number of accepted videos,
and the mean quality score of the rated live runs (reproductions are scored in
their own rows but left out of both headline numbers). The per-run table that follows gives each run's
length, every check, the human and reviewer scores, the API cost and a
verdict:

- **accepted**: a live run that passed every check and met the quality bar.
- **needs rating**: it passed every check but has no complete human rating yet.
- **below quality bar**: it passed every check, but its ratings are too low.
- **reproduction**: a rebuilt saved plan, not counted in the success rate.
- **failed**: a check failed; the reason column says which stage.
