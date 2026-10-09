# Traversaal.ai_Capstone

AI explainer video generation — Capstone project.

Project language: English. Write project documentation, code comments, command-line
messages, examples, and progress logs in English.

The first working module is **local English text-to-speech on CPU**. It reads a
UTF-8 text file and produces a verified narration WAV and a JSON report. This is
the audio foundation for the team's video pipeline; the timeline, renderer, and
website are future integration work.

The second module, `capstone_script`, turns a topic into a validated
scene-by-scene script with the Claude API and voices every line with the TTS
module. Videos of up to ten minutes are planned chapter by chapter, and an
optional review pass scores the script and rewrites weak lines.

A third stage on the `feat/remotion-renderer` branch builds a frame-accurate
timeline from the narration and renders the MP4 with Remotion (Node.js).
To go from a topic to an MP4 in one command, follow the
[quick start](docs/QUICKSTART.md).

[TTS usage guide](docs/TTS_GUIDE.md) · [Script planner guide](docs/SCRIPT_GUIDE.md) · [Planner evaluation](docs/PLANNER_EVALUATION.md) · [Video renderer guide](docs/RENDERER_GUIDE.md) · [Team week-one plan](docs/WEEK_01_PLAN.md)

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

For future video integration, use `sampleCount / sampleRate` for duration.
`chunks` are model chunk boundaries, **not subtitle or sentence timings**.
Scene IDs, sentence-level audio, frame padding and the timeline belong to a
later integration step. This report is not the complete ScenePlan schema.

## Structure

```text
capstone_tts/           CLI, Kokoro adapter, audio writer and verification
capstone_script/       Scene plan contract, LLM planner, narration bridge, preview, timeline
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

Inputs are plain English narration, up to 20,000 characters per run. Chinese,
SSML, voice cloning, background music and video export are not implemented.
The fixed environment was validated on one Mac, not a second teammate's
machine. Keep `.venv/`, `.cache/`, `runs/`, credentials and large model files
out of commits. Dependencies and model retain their upstream licenses.

## Upstream references

- [Kokoro code and usage](https://github.com/hexgrad/kokoro)
- [Pinned model revision](https://huggingface.co/hexgrad/Kokoro-82M/tree/f3ff3571791e39611d31c381e3a41a3af07b4987)
- [Misaki phonemizer](https://github.com/hexgrad/misaki)
- [spaCy English model](https://github.com/explosion/spacy-models/releases/tag/en_core_web_sm-3.8.0)
