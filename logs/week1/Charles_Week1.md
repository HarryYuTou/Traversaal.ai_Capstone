# Charles - Week 1 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 8, 2026  
**Focus:** Script and scene planning, connected to Harry's TTS module

## Contribution to the capstone

Built the step before narration: a topic becomes a scene-by-scene script that
says what each scene shows and what the narrator says. The script is checked
against a shared contract, and every line is voiced by Harry's `capstone_tts`
module without changing its code.

```text
Topic -> Script and scene plan -> TTS narration -> Timeline and visuals -> Final video
         ^ this work               ^ Harry's module, now connected
```

## Completed work

- **Windows reproduction of the TTS module.** Installed Python 3.11 and the
  lock file on Windows 11; `doctor` and all 20 unit tests passed, and the demo
  and long examples produced exactly the same sample counts as on Harry's Mac.
  Record: [TTS_WINDOWS_REPRODUCTION.md](../../docs/TTS_WINDOWS_REPRODUCTION.md).
- **ScenePlan contract.** Two slide templates (`concept`, `flow`), narration
  lines of at most 25 words, highlights that follow the narration, structural
  and cross-reference validation that lists every problem at once, an exported
  JSON Schema for the renderer, and valid and invalid fixtures.
- **LLM planner.** Topic, audience, length and optional reference facts go to
  Claude Opus 5.5 with structured output; the result must pass validation and
  the length check, with at most one repair request. Prompts live in
  `prompts/`; every run keeps the raw responses, token usage and latency.
- **Narration bridge.** Each line is synthesized through Harry's `write_run`
  with one model load per plan, producing per-line WAVs, `audio-manifest.json`
  with real sample counts, and a listening preview track.
- **Preview page.** `preview.html` shows each scene's slide, highlights the
  current point or node and displays subtitles in time with the narration.

## Validation results

| Check | Result |
| --- | --- |
| Unit tests | 57/57 passed (Harry's 20 and 37 new ones) |
| Fixture narration on Windows | 18 lines, 214 words, 81.0 s of speech, 84.3 s preview |
| Preview layout | No overlap between slide content and subtitles at maximum field lengths |
| Real Claude API plans | 3 topics, each valid on the first request; 75 s and 90 s targets gave 74.2 s and 92.6 s previews; $0.06–0.12 per plan |

Finding: speech synthesized line by line runs at about 2.6 words per second,
slower than whole paragraphs (2.9). The planner uses 2.6, about 185 words for a
75-second video; the week-one plan's 140–180 words would give 57–72 seconds.

## Update, October 9: longer videos, review and evaluation

- **Long videos.** Videos of up to ten minutes are planned chapter by chapter:
  an outline first, then each chapter with the outline and the end of the
  previous chapter as context. A seven-minute script on how AI search engines
  find answers (7 chapters, 26 scenes) passed on the first request for $0.46.
- **Script review.** A second request scores the script and rewrites weak
  lines without changing ids, highlights or visuals. On the seven-minute
  script it fixed 7 lines, including a recap line that nearly repeated a line
  from two chapters earlier.
- **Two more slide templates.** `comparison` (two labelled columns) and
  `definition` (a key term, its definition and an example), with the same
  highlight and coverage rules as the first two.
- **Evaluation.** Eight topics from 60 seconds to five minutes all passed on
  the first request. Final scripts were 104–110% of the word target, real
  speech was 99–115% of target, and the batch cost $1.92
  ([PLANNER_EVALUATION.md](../../docs/PLANNER_EVALUATION.md)).
- **Renderer prototype for the team.** The separate `feat/remotion-renderer`
  branch adds a frame-accurate timeline and a Remotion renderer that outputs
  the MP4; the seven-minute video rendered in about nine minutes on a laptop.
  It is a proposal for the visuals and assembly owners and is not merged.

Unit tests on this branch: 79 passed.

## Remaining work

- Listening review of the narration, and a short human rating of a few
  finished videos to check the reviewer's scores.
- Decide with the team whether to adopt, change or drop the renderer
  prototype.
- Length is now centered: asking for 95–105% of the word target put real
  speech at 98–105% of target on six re-run topics (it was 99–115%).
- Try grounding scripts in a source with `--reference-url` and check whether
  the reviewer's accuracy flags drop.

## How to run

```bash
python -m capstone_script validate --plan fixtures/scene-plan.valid.json
python -m capstone_script narrate --plan fixtures/scene-plan.valid.json --out runs/charles-demo --offline
python -m unittest discover -s tests -v
```

The [script planner guide](../../docs/SCRIPT_GUIDE.md) covers the Claude API
setup and every command.
