# Rebecca — Week 4 Log

## Summary

- Reproduced the full pipeline on a second Mac (8 GB MacBook Air) from a clean clone.
- Found and isolated a planner bug that blocked every new topic on `main` (October 16); it is fixed on the current `main`.
- Ran Level 1 acceptance: six live attempts on non-AI topics; four seven-minute videos were accepted by the scorecard.
- Watched and rated every video, and recorded the visual and pacing issues below.

Success rate 4 of 6 live attempts (67%). One failure was an API credit problem; the other was a scene-revision failure in the duration extension (`l1r-05`). Mean human quality score 4.65 / 5.

## Environment

| Item | Value |
| --- | --- |
| Machine | MacBook Air, Apple Silicon, 8 GB memory |
| macOS | Older than macOS 15 (Remotion prints a warning, but every render succeeded) |
| Python | 3.11, project `.venv` from `requirements.lock.txt` |
| Node.js | v24.22.0 (official installer from nodejs.org) |
| Code | `main` at `a2edf35` for all acceptance runs |

## Reproduction on a second Mac (October 16)

Ran the built-in sample with no Claude request:

```bash
python -m capstone_script narrate --plan fixtures/scene-plan.valid.json --out runs/smoke-01
python -m capstone_script render --run runs/smoke-01 --draft
```

Result: 960x540, 87.5 s, 6.7 MB, rendered in 60 s. The length matches the existing record (87.509 s).

## Planner bug (October 16, now fixed)

On `c126ca5` and `8a68e37`, every new topic failed at the scene-plan request:

```text
400 invalid_request_error: The compiled grammar is too large, which would cause performance issues.
Simplify your tool schemas or reduce the number of strict tools.
```

| Test | Commit | Result | Request ID |
| --- | --- | --- | --- |
| `run --duration 450` (printing press) | `c126ca5` | Outline passed, chapter 1 scene plan rejected | `req_011Cg6wzd3BHciAkKPptqgMF` |
| `plan --duration 90` (leap years) | `c126ca5` | Rejected on first request | `req_011Cg73Qxvk7HUGMc7xN1fZD` |
| `plan --duration 90` (leap years) | `8a68e37` | Rejected on first request | `req_011Cg73eWjYoVRnbLiuyaMxZ` |
| `plan --duration 90` (leap years) | `c0216fa` | Passed: 6 scenes, 224 words, $0.10 | — |

`c0216fa` is the last commit before the timeline, stat, quote and map templates (`335a51a`, `f75416e`). The same key passed there and failed after, so the cause was the larger structured-output schema, not the key. `23074bf` (PR #6) did not fix it.

On `a2edf35` the template router selects templates first, and the same 90-second test passed (`motion, stat`, 218 words, $0.22).

## Level 1 acceptance runs (October 28)

Command for every run:

```bash
time caffeinate -i python -m capstone_script run --topic "<topic>" --audience "<audience>" \
  --duration 420 --review --render --share --offline --concurrency 2 --out runs/<run>
```

| Run | Topic | Audience | Templates chosen | Length | Total time | Render | Cost | Verdict |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `l1r-01` | How the printing press changed Europe | Curious adults | timeline, map, comparison | 7:29 | 20:27 | 688 s | $0.96 | accepted |
| `l1r-02` | How volcanoes form and erupt | Middle school students | flow, comparison, map | 7:06 | 18:59 | 643 s | $1.01 | accepted |
| `l1r-03` | How inflation affects your savings | Young professionals | definition, comparison, motion | 7:14 | 24:48 | 651 s | $1.98 | accepted |
| `l1r-04` | What happens to your body while you sleep | Adults with no science background | — | — | 0:02 | — | $0.00 | failed (API credit) |
| `l1r-04b` | What happens to your body while you sleep | Adults with no science background | comparison, concept, flow | 7:17 | 19:29 | 654 s | $0.97 | accepted |
| `l1r-05` | Why does a second checkout counter cut waiting? | — | — | — | — | — | — | failed (scene revision) |

`l1r-04` stopped at the template-selection request with `Your credit balance is too low to access the Anthropic API` (`req_011CgVNDry4ums7FStxw43No`). Its directory is kept. `l1r-04b` is the same brief after adding credit. Whether `l1r-04` counts toward the success rate is a team decision.

`l1r-05` was run after the scorecard below. The planned video came in at 412 s, below the 420-second minimum, so the duration extension added scenes. Revising one added scene then failed and the run stopped before rendering:

```text
ERROR: No usable scene revision: duration-01-scene-02: Preserve object 'a3', its kind and its identity color.; ... 'a4' ...
```

The revision changed objects that had to stay the same across scenes, so it was rejected. Its directory is kept.

`--concurrency 2` was used on every run. No render crashed on 8 GB.

## Scorecard

```bash
python -m capstone_script scorecard --runs runs/l1r-0* --ratings ratings.csv --out runs/scorecard-l1r
```

- Success rate (live attempts): 4 of 5 (80%) at the time of the scorecard; 4 of 6 (67%) including `l1r-05`
- Accepted videos: 4
- Mean human quality score: 4.65 / 5
- Mean length: 7:16
- API cost recorded in the runs: $4.91

| Run | Accuracy | Clarity | Visuals | Audio | Sync | Quality | Reviewer (script) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `l1r-01` | 5 | 5 | 3 | 5 | 5 | 4.60 | 4.00 |
| `l1r-02` | 5 | 5 | 3 | 5 | 5 | 4.60 | 4.00 |
| `l1r-03` | 5 | 5 | 4 | 5 | 5 | 4.80 | 4.00 |
| `l1r-04b` | 5 | 4 | 4 | 5 | 5 | 4.60 | 3.80 |

All ratings are from one rater (Rebecca). I watched each full video with sound and checked the script's facts and numbers against the narration.

## Issues found

### Map scenes (`l1r-01`, `l1r-02`)

- Maps show pins on a grid with no borders, coastlines or continents, so viewers cannot tell where places are.
- `l1r-01` 01:06: narration says Mainz "lies in western Germany", but the Germany area is not drawn.
- `l1r-02` 02:00–02:12: the map is blank for about 15 seconds while the narration explains tectonic plates.
- `l1r-02` 06:42: another blank map at the start of a scene.
- Labels overlap: `l1r-01` 04:06 (Leipzig and Wittenberg); `l1r-02` 03:00–03:12 (Hawaiian islands, Oahu not readable).
- `l1r-02` 02:24: the "Japan" label sits at the right edge of the frame.

### Animated scenes (`l1r-03`)

- `l1r-03` was the only video of the four with animated scenes (11 of 18). It explained the idea most clearly and scored highest.
- 05:20–05:25 and 06:05–06:15: coins overlap map pins and cover the "Decades: investments" label. The run printed `Animation diagnostics flagged possible contacts or long holds`.
- Motion objects are small, with large empty areas in the frame.

### Slide-only videos (`l1r-01`, `l1r-02`, `l1r-04b`)

- Three of four videos used no animated scenes; `l1r-01` used comparison cards for 12 of 20 scenes.
- Cards sit in the upper half of the frame, leaving the lower half empty.
- `l1r-04b` 02:54: narration says "Watch how they change", but no brain waves are shown.

### Duration extension (`l1r-04b`)

- Scenes `duration-01-scene-01` and `duration-01-scene-02` were added inside the recap chapter (06:36–07:06), between the recap and the closing scene, which breaks the flow.
- 06:54: the added narration says "Another myth", but no earlier myth was introduced.
- `l1r-05`: the extension's scene revision failed to preserve objects `a3` and `a4`, which stopped the whole run (see above). Both extension problems point to the same step.

### Length margin

- `l1r-02` was 425.8 s, only 5.8 s above the 420-second minimum.

## Setup notes for the README

These cost time on a fresh Mac and may help the next teammate:

- Homebrew reported a Tier 3 configuration on this macOS, so packages built from source. `brew install node` spent hours compiling LLVM; the official installer from nodejs.org took minutes.
- Cloning into `~/Desktop` failed with a permission error from macOS privacy settings. Cloning into `~/Projects` worked.
- With Anaconda installed, run `conda deactivate` before creating or activating `.venv`.
- GitHub no longer accepts passwords for `git clone`; `gh auth login` worked.
- After `npm --prefix renderer ci`, npm asked to approve esbuild's install script: `cd renderer && npm install-scripts approve esbuild`.
- On an 8 GB machine, use `--concurrency 2` for seven-minute renders.

## Open items

- Rerun `l1r-05` (or another topic) on the current `main` to reach five accepted videos of my own, independent of whether Harry's queue video counts.
- Look into the duration extension: where it inserts scenes, and why its scene revision can fail on preserved objects.
- Decide whether `l1r-04` (API credit failure) counts toward the success rate; without it the rate is 4 of 5 (80%).
- Add a second rater for each video.
- Optionally rebuild Harry's queue video from `fixtures/scene-plan.process-queue-long.json` and rate it as a second rater (a reproduction, not counted in the success rate).
- API cost: I paid $10 in credit for these runs.
