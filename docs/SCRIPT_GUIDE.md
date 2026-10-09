# Script Planner Guide

`capstone_script` turns a topic into a scene-by-scene script and voices every
line with the `capstone_tts` module. Each scene says what the viewer sees (one
of two slide templates) and what the narrator says, one short line at a time.

```text
Topic -> scene-plan.json -> one WAV per line + audio-manifest.json -> narration-preview.wav + preview.html
         (Claude API)        (capstone_tts, local CPU)                 (listening and visual check)
```

## Setup

Use the same Python 3.11 `.venv` as the TTS module and install
`requirements.lock.txt`; it now includes the `anthropic` SDK.

Only the `plan` and `run` commands call the Claude API. Create a file named
`.env` in the repository folder containing `ANTHROPIC_API_KEY=...`. Git ignores
`.env`; never commit or paste the key. A Claude subscription does not include
API usage. Each call's token usage is saved in `llm-response.json`; the list
price for Claude Opus 5.5 is $4 per million input tokens and $20 per million
output tokens.

## Commands

```bash
# Check a plan against the contract
python -m capstone_script validate --plan fixtures/scene-plan.valid.json

# Topic -> scene plan (Claude API)
python -m capstone_script plan --topic "What happens after you enter a website address?" \
  --audience "University students with no networking background" --duration 75 \
  --reference fixtures/reference-primary.md --out runs/plan-01

# Scene plan -> narration and preview (local CPU, no API key)
python -m capstone_script narrate --plan fixtures/scene-plan.valid.json --out runs/narration-01 --offline

# Topic -> scene plan -> narration and preview in one run directory
python -m capstone_script run --topic "How do noise-cancelling headphones work?" --out runs/run-01 --offline

# Rebuild preview.html, or regenerate the JSON Schema after changing the models
python -m capstone_script preview --run runs/narration-01
python -m capstone_script schema

python -m unittest discover -s tests -v
```

`--duration` accepts 30–180 seconds for now (a plan holds at most 12 scenes).
`--offline` uses the cached Kokoro model; omit it on the first narration. Every
command refuses an existing output directory.

## The ScenePlan contract

| Template | Visual fields | Narration highlight |
| --- | --- | --- |
| `concept` | `title` (≤60 chars), `statement` (≤120), up to 3 `points` (≤60 each) | `highlightPointIndex` |
| `flow` | `title` (≤60), 2–4 `nodes` with `id` and `label` (≤24) | `highlightNodeId` |

Every scene has an `id`, a `purpose`, a `template`, a `visual` and 1–8
narration lines of at most 25 English words. IDs use lowercase letters, digits
and hyphens because narration IDs become file names. Python also checks what
JSON Schema cannot: unique scene, line and node IDs, highlights that point to
an existing point or node, the word limit and English-only text.
`schemas/scene-plan.schema.json` is generated from the models for other
languages; the Python check remains the reference. A plan never contains audio
paths, durations or frames; later stages measure those from real audio.

## How the planner works

1. `prompts/scene-planner.txt` sets the rules; the request gives the topic,
   audience, word target and optional reference facts.
2. Claude Opus 5.5 (effort `high`) answers with structured JSON output. The
   program renumbers scene and line IDs and makes node IDs path-safe.
3. The plan must pass validation and fit the length: the word target assumes
   2.6 words per second, and a plan outside 80–120% of the target words counts
   as a problem. Every point and node must also be highlighted by at least one
   narration line, so the visuals follow the narration.
4. If anything fails, one repair request (`prompts/repair-scene-plan.txt`)
   lists every problem. A second failure stops the run; `llm-response.json`
   keeps both raw responses. API errors are retried by the SDK.

## Run outputs

| File | Written by | Contents |
| --- | --- | --- |
| `project-spec.json` | `plan`, `run` | Topic, audience, target duration, reference hash |
| `llm-response.json` | `plan`, `run` | Model, request IDs, token usage, latency, problems, raw text |
| `scene-plan.json` | all | The validated plan used for narration |
| `audio/<narrationId>/` | `narrate`, `run` | `capstone_tts` output for one line: WAV, `audio-info.json`, input |
| `audio-manifest.json` | `narrate`, `run` | Per line: scene, text, audio path, real sample count, duration, synthesis time |
| `narration-preview.wav` | `narrate`, `run` | All lines with fixed 0.2 / 0.1 / 0.2 s scene pauses, for listening only |
| `preview.html` | `narrate`, `run`, `preview` | Slides, highlights and subtitles driven by the preview track |

Open `preview.html` from the run folder in a browser. The preview pauses are
not the frame-accurate timeline; that stays with the timeline module.

## Measured results

On Windows 11 (Ryzen 7 5800HS, two CPU threads) the fixture plan's 18 lines and
214 words produced 81.0 seconds of speech (2.64 words per second) and an
84.3-second preview. Model loading took 19.6 seconds and synthesis 78.2 seconds.
Whole paragraphs read faster (about 2.9 words per second), so per-line timing
is the basis for the planner's word target. At this rate the week-one plan's
140–180 words would produce a 57–72 second video.

First real planner runs (October 8, 2026, Claude Opus 5.5, effort `high`). Each
plan passed on the first request, with no repair needed:

| Topic | Target | Scenes, lines, words | Real speech | Preview | Tokens in / out | Latency |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| Entering a website address, with `reference-primary.md`* | 75 s | 7, 16, 195 | not narrated | — | 2,853 / 5,393 | 48 s |
| How noise-cancelling headphones work | 75 s | 5, 16, 191 | 71.1 s | 74.2 s | 2,462 / 2,609 | 24 s |
| Retrieval-augmented generation for business users | 90 s | 5, 18, 228 | 89.3 s | 92.6 s | 2,475 / 3,235 | 29 s |

\* Prompt v1. It left some points and nodes without a highlighting line, which
led to the coverage rule in v2. At list prices the three plans cost about
$0.12, $0.06 and $0.07.
