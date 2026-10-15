# Charles - Week 2 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 15, 2026  
**Branch:** `feat/visual-upgrade` (merged through PR #2; its follow-up fixes and this log reach main in the next PR)  
**Focus:** From scene plan to finished video: the renderer, motion, themes and music, four templates for history and science topics, and long example videos

## Contribution to the capstone

Week one ended with the script planner in main and a renderer prototype on a
separate branch. This week the renderer, the long-video planner and a visual
upgrade went into main through PR #2 (October 9), so one command now takes a
topic to a finished MP4. Harry's web studio (PR #3) runs the same pipeline
from a browser.

```text
Topic -> Script and scene plan -> TTS narration -> Timeline and visuals -> Final video
                                                   ^ this week's work
```

## Completed work

### Renderer and pipeline (in main through PR #2)

- `render --run <dir>` and `run --render` turn a narrated plan into a 1080p
  MP4 with Remotion, timed from the real audio length of every line.
  `--draft` renders at 960×540 for quick checks and `--share` also writes a
  720p copy. A run also gets `thumbnail.png`, subtitles and, for long
  videos, chapter start times to paste into a video description.
- Slides can carry icons from a shared list of 139 Lucide names
  (`schemas/icons.json`); the planner drops names that are not on the list.
- `narrate --reuse <earlier run>` copies the audio of lines whose text did
  not change, so a small script edit does not re-voice the whole video.
- `--reference-url` grounds a script in a web page; the first three-topic
  comparison is in [PLANNER_EVALUATION.md](../../docs/PLANNER_EVALUATION.md).
- [QUICKSTART.md](../../docs/QUICKSTART.md) takes a teammate from a topic to
  a video.

### Visual upgrade (in main through PR #2)

- Four templates for history and science topics: `timeline` (dated events),
  `stat` (large numbers), `quote` (a quotation and its source) and `map`
  (areas, places and routes). They come with their own cross-reference
  checks, a shared list of map regions, and drawings in the browser preview.
  The planner does not use them yet; see "In progress" below.
- Motion: scenes push in and out over a slowly moving backdrop, titles rise
  word by word and icons draw themselves.
- `--theme light|night`; night is a darker documentary look.
- A music bed generated locally with numpy from a fixed seed, so there is
  nothing to download or license. It ducks while the narrator speaks, and
  `--no-music` leaves it out.
- Voice-only respellings (`schemas/pronunciations.json`). Kokoro read Qian as
  "kai-en" and Chicxulub as "chick-sue-lub"; captions keep the real spelling.

### Five hand-written example videos

Storyboards in `examples/handwritten/` on the Silk Road, World War II, the
First Emperor, Apollo 11 and the dinosaur extinction, written by hand in a
Claude Code session to try the new templates on the kinds of topics the
client asked for. They are not planner output and made no API calls.

| Measurement | Result |
| --- | --- |
| Length | 473–524 s each, 23–25 scenes |
| Render time on a laptop | 703–828 s per video (17.6–20.2 frames per second), night theme with music |
| File size | 83–100 MB at 1080p; 18–20 MB `--share` copies |
| Timing | Every probed length matched its timeline within 0.02 s |

The moving backdrop costs about 20 percent of render speed and more than
doubles the file size. For an upload limit around 10 MB, CRF 37 with mono
48 kbps audio gives 8.7–9.7 MB copies. Details are in the
[renderer guide](../../docs/RENDERER_GUIDE.md).

### Fixes after PR #2 (merged together with this log)

- Two storyboard lines corrected: the Silk Road line no longer mixes
  Procopius's account with the later hollow-cane detail, and the Apollo 11
  line says the crew did not recognize the alarm codes.
- A stress test with every field at its length limit found two layout
  failures a planner could trigger. A twelve-digit stat no longer pushes its
  neighbours off the slide, because numbers shrink to fit their column, and
  stats line up when only some of them have icons. On a crowded map, a label
  with no free spot appears only while the narration is on its place, and the
  legend flows under a two-line title.

## In progress: the planner and the new templates

`feat/planner-visual-templates` teaches the planner all eight templates. The
prompt says when to use each one, and the output shape, id clean-up, icon
filter and coverage check handle the new ones. Without a reference, the
prompt allows only famous dates and numbers and quotations the model can give
word for word, and the reviewer never rewrites a quotation line. All 129
offline tests passed on that branch.

It is not merged yet. Claude's structured outputs accept at most 24 optional
parameters and 16 parameters with union types (`anyOf`, which is how pydantic
writes an optional field) per request. The new output shape has 33 of each,
so the API would reject every planner request; this was checked offline
against the documented limits, without an API call. The shape in main has 15
of each, one under the union-type limit, so adding any optional field to it
will also break planning. Next: regroup the new fields under the limits, test
offline, run one real plan, then open the PR.

## Validation results

| Check | Result |
| --- | --- |
| Python tests on Windows 11, this branch with current main | 145 of 147 passed. The 2 errors are web-worker tests that call `os.killpg` and `signal.SIGKILL`, which Windows does not have; they fail the same way on main |
| Renderer TypeScript check | Passed |
| Hand-written renders | 5 videos; every length matches its timeline within 0.02 s |
| Planner output shape vs. API limits | Main: 15 optional and 15 union-typed fields. Planner branch: 33 and 33. Limits: 24 and 16 |

## Remaining work

- Regroup the planner's output shape under the structured-output limits and
  run one real plan before merging `feat/planner-visual-templates`.
- Web studio on Windows: the worker clean-up calls `os.killpg` and
  `signal.SIGKILL`, which exist only on macOS and Linux, so stopping a job on
  Windows would raise an error (noted for Harry).
- A listening and fact review of the hand-written videos by someone other
  than their writer.
- The map template draws a latitude and longitude grid, not country borders;
  borders would need map data packages, which were left out for now.

## How to run

```bash
python -m capstone_script narrate --plan examples/handwritten/apollo-11.json --out runs/apollo-11 --offline
python -m capstone_script render --run runs/apollo-11 --theme night --share
python -m capstone_script run --topic "How does GPS know where you are?" --duration 90 --review --render --out runs/gps-01
```

The last command calls the Claude API. The
[renderer guide](../../docs/RENDERER_GUIDE.md) covers the Node.js setup and
every render option.
