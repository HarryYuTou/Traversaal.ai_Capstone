# Video Renderer Guide

This branch adds the last two stages of the pipeline: a frame-accurate
timeline and a Remotion renderer that turns a narrated run into an MP4 with
animated slides, captions and the narration track. It is offered for the
visual design and video assembly owners to adopt, change or replace; nothing
in the script or TTS modules depends on it.

```text
narrated run -> video/timeline.json + video/narration.wav + subtitles -> video.mp4
               (python -m capstone_script timeline)                     (Remotion, renderer/)
```

## Setup

Rendering needs [Node.js](https://nodejs.org) (tested with Node 26.10 on
Windows 11) on top of the Python setup in the README. Install the renderer's
pinned packages once:

```bash
cd renderer
npm install
cd ..
```

This installs Remotion 4.0.531 and React (about 260 MB in
`renderer/node_modules/`, ignored by Git). The first render or still also
downloads Chrome Headless Shell (about 113 MB) for Remotion. No FFmpeg install
is needed: Remotion ships its own. Remotion has its own license: it is free for
individuals, non-profits and companies of up to three people, and larger
companies need a company license. Check it before the client ships the
renderer in a product.

## Commands

```bash
# Narrated run -> timeline, aligned narration track and subtitles (no Node needed)
python -m capstone_script timeline --run runs/narration-01

# Narrated run -> MP4 (builds the timeline first if it is missing)
python -m capstone_script render --run runs/narration-01
python -m capstone_script render --run runs/narration-01 --draft   # 960x540, quicker

# Check a few frames as PNG files without rendering the whole video
cd renderer
node scripts/stills.mjs ../runs/narration-01/video/timeline.json ../runs/narration-01/stills 30 400 900

# Open Remotion Studio with a built-in demo timeline, to work on the design
npx remotion studio src/index.ts
```

The `render` command refuses an existing `video.mp4`; delete it to render
again. Deleting `video/` rebuilds the timeline on the next render.

## The timeline

`capstone_script/timeline.py` places everything on whole frames at 30 fps:

| Part | Frames | Notes |
| --- | ---: | --- |
| Title card | 60 | Silent; video title and length |
| Chapter card | 45 | Silent; before the first scene of each chapter (long plans only) |
| Scene lead | 6 | Before the first line of a scene |
| Line | ceil(samples / 1600) | Real audio length at 48 kHz, rounded up to whole frames |
| Gap | 3 | Between lines of one scene |
| Scene tail | 6 | After the last line |
| End hold | 30 | Added to the last scene |

These are the week-one pauses (6/3/6 frames). Line timing comes from the
sample counts in `audio-manifest.json`, never from estimates, and the timeline
refuses a plan that changed after narration (it checks `planSha256`).

The `video/` folder holds:

| File | Contents |
| --- | --- |
| `timeline.json` | Size, fps, total frames, title and chapter cards, and every scene and line with its start frame, length, text, visual and highlight |
| `narration.wav` | One 48 kHz mono track: each line's samples start exactly at its start frame (1,600 samples per frame), with silence elsewhere |
| `subtitles.srt`, `subtitles.vtt` | One cue per line on the same frames, split into two rows when longer than 42 characters |

Because narration.wav is built from the same frames, the renderer only plays
one audio file and cannot drift out of sync.

## The renderer

`renderer/` is a small Remotion project. `src/Explainer.tsx` lays out the
video from `timeline.json`, passed with `--props`; `--public-dir` points at
the run's `video/` folder so `narration.wav` can be loaded.

| File | Draws |
| --- | --- |
| `src/scenes/Cards.tsx` | Title card, and chapter cards with the chapter number, title and position |
| `src/scenes/ConceptScene.tsx` | Title, statement and up to three points |
| `src/scenes/FlowScene.tsx` | Two to four steps with arrows, left to right |
| `src/Overlays.tsx` | Captions and the progress bar with chapter marks |
| `src/theme.ts` | Colors, font and motion timing, matching the browser preview |

Points and steps appear when the narration first highlights them, the current
one is highlighted while it is being talked about, and an item that is never
highlighted appears just after its scene starts. Captions show the spoken line
and stay up through the short gaps inside a scene. Every scene fades in and
out. Fonts are system fonts, so rendering works offline.

## Measured results

Windows 11, Ryzen 7 5800HS (8 cores, 15 GB RAM), Node 26.10, Remotion 4.0.531
with its default concurrency, full size (1920x1080, H.264 video and AAC audio):

| Run | Scenes | Frames | Length | Render time | File |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retrieval-augmented generation for business users | 5 | 2,876 | 95.9 s | 120 s (24 frames per second) | 7.4 MB |

The probed length of each MP4 matched its timeline within 0.01 s.
