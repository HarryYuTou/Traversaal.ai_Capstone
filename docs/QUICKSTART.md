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
file; never commit or share the key. A Claude subscription does not include
API usage.

The first narration downloads the Kokoro voice model (about 328 MB) and the
first render downloads a headless Chrome for Remotion (about 113 MB). After
that, add `--offline` to use the cached voice model.

## 2. Make a video

```bash
python -m capstone_script run --topic "How does GPS know where you are?" --audience "Curious adults with no technical background" --duration 90 --review --render --out runs/gps-01
```

| Step | What happens | Time on a laptop CPU (90 s video) |
| --- | --- | --- |
| Plan | Claude writes the scenes and narration; videos over 3 minutes are planned chapter by chapter | 30 s (3–4 min for 7 minutes) |
| Review | Claude scores the script and rewrites weak lines | 30–40 s |
| Narrate | Kokoro voices every line on the CPU | 1–2 min (about 4 min for 7 minutes with `--threads 4`) |
| Render | Remotion draws the slides, captions and audio into `video.mp4` | about 2 min (9 min for 7 minutes) |

`--duration` takes 30 to 600 seconds. Every command refuses an existing
output folder, so pick a new `--out` each time. Leave out `--render` to stop
after narration, and add `--draft` for a quicker half-size render.

API cost at list prices: about $0.10–0.20 for a video of up to three
minutes and about $0.60 for seven minutes, including the review.

## 3. Check the result

In the run folder:

| File | Use |
| --- | --- |
| `video.mp4` | The finished video, 1920x1080 |
| `preview.html` | Open in a browser: slides, highlights and subtitles over the narration, for a quick check |
| `scene-plan.json` | The script: every scene's slide and narration lines |
| `review.json` | The review's scores, issues and every rewritten line |
| `video/subtitles.srt` | Subtitles for uploading with the video |

To change the script by hand, edit a copy of `scene-plan.json`, check it with
`python -m capstone_script validate --plan <file>`, then voice and render it:

```bash
python -m capstone_script narrate --plan my-plan.json --out runs/gps-02 --offline
python -m capstone_script render --run runs/gps-02
```

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
