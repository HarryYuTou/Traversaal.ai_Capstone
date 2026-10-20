# Traversaal.ai_Capstone

AI explainer video generation — Capstone project.

Project language: English. Write project documentation, code comments, command-line
messages, examples, and progress logs in English.

The local video pipeline turns a topic, audience, and target length into an
English explainer MP4. `capstone_script` creates a validated script with the
Claude API, optionally reviews it, synthesizes narration with local CPU TTS,
and builds a frame-accurate timeline for the Remotion renderer. Target lengths
range from 30 seconds to ten minutes; videos over three minutes are planned
chapter by chapter.

The planner now supports **process scenes** for arrivals, waiting, service and
completion. It specifies actors, stations and events; a local compiler checks
queue order and occupancy, lays out the workflow, and schedules travel, visible
work and departure against real narration. The bounded vocabulary supports
1–8 people, packets, boxes or coins and 1–2 counters, servers or workbenches per
scene. It is reusable across those workflows, not arbitrary scene generation.

The renderer also supports **motion scenes**: persistent illustrated objects
move along paths, orbit, separate, fade, rotate, resize and change value in time
with the actual narration. The Apollo and network samples share this engine;
their storyboards contain data, not topic-specific rendering code. See the
[motion and process guide](docs/MOTION_GUIDE.md) for local demos, contracts and
measured timing checks. Both source formats use the same frame renderer;
process events compile into motion actions and activity intervals.
Live Claude planning has also been exercised on a new queueing example:
the API produced an unedited two-scene motion plan, followed by local Kokoro
narration and Remotion rendering. The [verification record](docs/MOTION_GUIDE.md#live-planning-check)
documents the schema fix, visual findings, usage and remaining quality limits.
The subsequent process run produced a **7 min 14 s** video with six chapters,
13 illustrated workflow scenes and one definition scene, using people,
parcels and computer requests. Its source plan is saved as
[`fixtures/scene-plan.process-queue-long.json`](fixtures/scene-plan.process-queue-long.json).
See the [process verification record](docs/MOTION_GUIDE.md#seven-minute-process-run)
for the actual API review, encoded-video checks, cost and remaining limits.

**Traversaal Studio (Frontend-v1)** adds a browser workspace for the brief,
setup checks, generation progress, video playback, and downloads, with local
sign-in accounts and a per-account video history. It runs on this computer at
`127.0.0.1:8000`, with durable local jobs and one generation worker. The
built-in sample uses an existing script with real TTS and rendering and needs
no Claude key; a new topic uses the configured Claude API. Follow the
[web studio guide](docs/WEB_STUDIO.md) to install and start it. This version
does not include public deployment.

For command-line topic-to-video generation, follow the
[quick start](docs/QUICKSTART.md). The standalone **local English text-to-speech
on CPU** module also remains available: it reads a UTF-8 text file and writes a
verified narration WAV and JSON report, as described below.

[Web studio guide](docs/WEB_STUDIO.md) · [Motion scene guide](docs/MOTION_GUIDE.md) · [TTS usage guide](docs/TTS_GUIDE.md) · [Script planner guide](docs/SCRIPT_GUIDE.md) · [Planner evaluation](docs/PLANNER_EVALUATION.md) · [Level 1 quality scorecard](docs/QUALITY_SCORECARD.md) · [Video renderer guide](docs/RENDERER_GUIDE.md) · [Team week-one plan](docs/WEEK_01_PLAN.md)

## Quick start (macOS, Python 3.11)

Run these commands from the repository folder. The validated machine is Apple
Silicon with macOS 15.1. Windows 11 was also verified
([record](docs/TTS_WINDOWS_REPRODUCTION.md)); other systems have not been.
The `brew` command requires [Homebrew](https://brew.sh/); install it first if
it is missing, or skip that line if Python 3.11 is already installed.

```bash
# Install Python if it is not already available.
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
python -m pip check
python -m capstone_tts doctor
python -m capstone_tts synthesize --text examples/demo.txt --output-dir runs/demo
```

The first synthesis downloads the pinned Kokoro model and voice from Hugging
Face (roughly 328 MB) into `.cache/huggingface/`. Dependency installation also
needs internet access to PyPI and GitHub. No API key, paid speech service, GPU,
Node.js, or FFmpeg is needed for this module. Speech inference runs locally.
The installed English phonemizer includes its own eSpeak library; `doctor`
checks that it actually works.

For an existing setup, only activate the environment and run the last command
with a **new** output directory. Existing runs are never overwritten.

```bash
python -m capstone_tts synthesize --text examples/acronyms.txt --output-dir runs/acronyms --offline
python -m capstone_tts synthesize --text examples/long.txt --output-dir runs/long --offline
python -m unittest discover -s tests -v
```

`--offline` requires a successful initial model download. It uses only the
cached model files. `--speed 1.0` is the default; accepted range is 0.5–2.0.
CPU threads default to 2 and can be set with `--threads` (1–16). Run
`python -m capstone_tts synthesize --help` for all options.

## Outputs and handoff contract

Each successful run contains:

```text
runs/demo/
  narration.wav       # 48,000 Hz, mono, PCM 16-bit
  audio-info.json     # measured duration, counts, configuration and timings
  input.txt           # narration used, with surrounding whitespace removed
```

The engine generates 24 kHz audio. All chunks are concatenated in order and
**resampled** to 48 kHz. No artificial pauses or frame padding are added.
If the resampled peak exceeds 0.99, gain is reduced to avoid PCM clipping; the
applied gain is recorded. The saved WAV is read back before a run is published.

Key `audio-info.json` fields:

| Field | Meaning |
| --- | --- |
| `schemaVersion` | `1.0` for this standalone TTS report |
| `audioPath` | `narration.wav`, relative to the report directory |
| `sampleRate`, `channels`, `subtype` | Actual written WAV format |
| `sampleCount`, `durationSeconds` | Actual frames and frames / sample rate |
| `sourceSampleRate`, `sourceSampleCount` | Native 24 kHz counts before resampling |
| `chunkCount`, `chunks` | Every chunk's text, original start sample and sample count |
| `modelId`, `modelRevision`, `voiceId`, `device` | Fixed model revision, `af_heart`, CPU |
| `timingsMs.initializationIncludingDownloads` | Dependency imports, asset lookup/download and model load |
| `timingsMs.phonemizationAndSynthesis` | Text processing and actual inference over all chunks |
| `timingsMs.resampleWriteVerify` | Resampling, WAV write, read-back checks and input snapshot |
| `timingsMs.totalThroughAudioVerification` | Function time up to verified audio, excluding CLI startup/final JSON publication |
| `listeningReview` | `pending`: automated checks do not prove pronunciation quality |

For video integration, use `sampleCount / sampleRate` for duration.
`chunks` are model chunk boundaries, **not subtitle or sentence timings**.
`capstone_script` adds scene IDs, sentence-level audio, frame padding, and the
timeline. This standalone TTS report is not the complete ScenePlan schema.

## Structure

```text
capstone_tts/           CLI, Kokoro adapter, audio writer and verification
capstone_script/       Scene plan contract, LLM planner, narration bridge, preview, timeline
capstone_web/          Local HTTP API, saved jobs and pipeline worker
web/                   React/TypeScript browser workspace (separate from the renderer)
renderer/              Remotion project that renders a timeline to MP4 (Node.js)
prompts/               Planner, chapter, review and repair prompts
schemas/               ScenePlan JSON Schema generated from the models
fixtures/              Valid and invalid scene plans and reference facts
examples/              English demo, abbreviations and long paragraph
tests/                 Offline unit tests using synthetic audio
requirements.in        Direct dependency decisions
requirements.lock.txt  Exact installed packages from the tested environment
docs/                  Team plan, usage guide and verification record
logs/week1/            Individual week-one progress reports
runs/                  Local generated outputs (ignored by Git)
.cache/                Local model cache (ignored by Git)
```

Tests cover chunk preservation, duration/resampling, invalid audio and failure
handling. They are separate from real-model acceptance recorded in
[TTS verification](docs/TTS_VERIFICATION.md).
Harry's completed work is recorded in [the week-one log](logs/week1/Harry_Week1.md).

## Troubleshooting

- **Wrong Python / missing module:** activate `.venv`; use `python -m pip` with
  the same interpreter. This project currently targets Python 3.11.
- **First download fails:** check access to Hugging Face, then retry with the
  same cache and an unused output directory. A failed run does not publish
  a success report. `--offline` cannot fill an incomplete cache.
- **Output already exists:** select another directory, such as `runs/demo-02`.
- **Unknown pronunciation or oversized word:** rewrite that part of the text.
  The module rejects known missing pronunciations or chunks above 510 phonemes
  instead of silently truncating them.
- **Abbreviations sound wrong:** listen and rewrite them as spoken letters or
  words. The example deliberately includes both forms; pronunciation quality
  still needs human review.
- **Torch deprecation warnings:** warnings from the upstream model may appear;
  successful output and `doctor` are the functional checks.

Standalone TTS inputs are plain English narration, up to 20,000 characters per
run. Chinese, SSML, and voice cloning are not implemented. Background music and
video export are provided by `capstone_script` and the web studio. The TTS
verification records cover macOS and a teammate's Windows environment; they do
not establish verification of the web studio on both systems. Keep `.venv/`,
`.cache/`, `runs/`, credentials and large model files out of commits.
Dependencies and model retain their upstream licenses.

## Upstream references

- [Kokoro code and usage](https://github.com/hexgrad/kokoro)
- [Pinned model revision](https://huggingface.co/hexgrad/Kokoro-82M/tree/f3ff3571791e39611d31c381e3a41a3af07b4987)
- [Misaki phonemizer](https://github.com/hexgrad/misaki)
- [spaCy English model](https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0)
