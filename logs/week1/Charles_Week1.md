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

## Remaining work

- Try more topics and audiences, including longer videos.
- Listening review of the generated narration.
- The frame-accurate timeline, renderer and final MP4 belong to the visuals and
  timeline work; the scene plan and audio manifest are ready as their input.

## How to run

```bash
python -m capstone_script validate --plan fixtures/scene-plan.valid.json
python -m capstone_script narrate --plan fixtures/scene-plan.valid.json --out runs/charles-demo --offline
python -m unittest discover -s tests -v
```

The [script planner guide](../../docs/SCRIPT_GUIDE.md) covers the Claude API
setup and every command.
