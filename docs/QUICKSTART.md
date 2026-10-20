# Quick Start: From a Topic to a Video

For teammates who want to make an explainer video on their own computer. One
command writes the script with Claude, reviews it, voices it with the local
TTS model and renders an MP4 with Remotion.

## 1. One-time setup

You need Python 3.11, Node.js (tested with 26.10) and a Claude API key.

macOS (from the repository folder):

```bash
brew install python@3.11
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock.txt
```

Windows (PowerShell, from the repository folder):

```powershell
pymanager install 3.11
& "$env:LOCALAPPDATA\Python\pythoncore-3.11-64\python.exe" -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
```

On Windows, write `.venv\Scripts\python.exe` wherever this guide says
`python`. Then, on either system:

```bash
cd renderer
npm install
cd ..
```

Create a file named `.env` in the repository folder containing
`ANTHROPIC_API_KEY=...` with a key from the Claude Console. Git ignores this
file; never commit or share the key. API usage is billed through Claude
Console. Eligible Max and Team plans can claim separate monthly API credits
by linking a Console organization; see the [current API credits guide](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers).

The first narration downloads the Kokoro voice model (about 328 MB) and the
first render downloads a headless Chrome for Remotion (about 113 MB). After
that, add `--offline` to use the cached voice model.

## 2. Make a video

```bash
python -m capstone_script run --topic "How does GPS know where you are?" --audience "Curious adults with no technical background" --duration 90 --review --render --out runs/gps-01
```

| Step | What happens | Time on a laptop CPU (90 s video) |
| --- | --- | --- |
| Plan | Claude selects up to three visual templates, then writes scenes and narration; videos over 3 minutes are planned chapter by chapter | Older slide baseline: 30 s (3–4 min for 7 minutes); motion plans can take longer |
| Review | Claude scores the script and rewrites weak lines | 30–40 s |
| Narrate | Kokoro voices every line on the CPU | 1–2 min (about 4 min for 7 minutes with `--threads 4`) |
| Render | Process events compile into safe positions and phased motion; Remotion draws motion scenes or slides, captions and audio into `video.mp4` | about 2 min (9 min for 7 minutes); older slide measurements |

`--duration` takes 30 to 600 seconds. Every command refuses an existing
output folder, so pick a new `--out` each time. Leave out `--render` to stop
after narration, add `--draft` for a quicker half-size render, and add
`--share` for a 720p copy small enough to email or upload.

Earlier slide runs cost about $0.10–0.20 for a video of up to three
minutes and about $0.60 for seven minutes, including review. These are
historical measurements, not estimates for detailed motion storyboards.
The default pipeline now adds a small template-selection request. Each run's
`llm-response.json` records reported token usage and an estimated list-price
cost, including selection and any planning repairs.

For an arrival/service explanation, the planner can use the new `process`
template. This uses 1–8 actors (`person`, `packet`, `box` or `coin`) and 1–2
stations (`counter`, `server` or `workbench`) per scene. The model describes
who arrives, waits, starts service and finishes; local code supplies layout,
work feedback and departure. Other physical explanations can still use
direct motion scenes. This is a reusable bounded vocabulary, not universal
animation from any prompt.

For example, with the checked-in factual reference:

```bash
python -m capstone_script run --topic "Why does a queue grow, and when does adding another service desk help?" --audience "Curious adults" --duration 75 --reference fixtures/reference-queue-expanded.md --render --share --out runs/queue-process-01
```

This command uses the real API and local narration. It is a reproduction
recipe, not an assertion that a particular run has passed visual acceptance.

## 3. Check the result

In the run folder:

| File | Use |
| --- | --- |
| `video.mp4` | The finished video, 1920x1080 |
| `preview.html` | Listening preview with captions and slide highlights; inspect the MP4 for motion scenes |
| `scene-plan.json` | Every scene's authored visuals, process events or motion actions, and narration lines |
| `review.json` | The review's scores, issues and every rewritten line |
| `video-720p.mp4` | With `--share`: a copy about a quarter of the size |
| `thumbnail.png` | The title card as an image |
| `video/subtitles.srt` | Subtitles for uploading with the video |
| `video/chapters.txt` | Chapter start times for long videos, to paste into a video description |
| `video/timeline.json` | Measured timeline; process scenes include compiled motion and a `processTrace` for inspecting state transitions |

To change the script by hand, edit a copy of `scene-plan.json`, check it with
`python -m capstone_script validate --plan <file>`, then voice and render it:

```bash
python -m capstone_script narrate --plan my-plan.json --out runs/gps-02 --offline
python -m capstone_script render --run runs/gps-02
```

Process events also receive timing checks after the real speech is known.
If an event is too short for readable travel, work or departure, the compiler
reports the scene and event. Revise the source narration or anchors in a new
run; avoid packing several events into one short line. Inspect both the
mechanism and its explanation: parallel service needs enough time to see,
and a stated new condition needs a corresponding demonstration. Detailed
limits and timing rules are in the [process guide](MOTION_GUIDE.md#semantic-process-contract).

To change the look, edit `renderer/src/theme.ts` (colors, fonts, timing) or
the slide components in `renderer/src/scenes/`, and preview them with
`npx remotion studio src/index.ts` from the `renderer` folder.

## 4. Good to know

- Narration is English only. Real speech lands within about 5% of the
  requested length ([evaluation](PLANNER_EVALUATION.md)).
- The reviewer often flags claims to double-check. Give the planner a source
  with `--reference facts.md` or `--reference-url <web page>`, or fact-check
  the script before publishing the video.
- More detail: [script planner guide](SCRIPT_GUIDE.md),
  [renderer guide](RENDERER_GUIDE.md), [TTS guide](TTS_GUIDE.md).
