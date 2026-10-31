# Video Renderer Guide

This branch adds the last two stages of the pipeline: a frame-accurate
timeline and a Remotion renderer that turns a narrated run into an MP4 with
illustrated motion scenes or animated slides, captions and the narration track. It is offered for the
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
python -m capstone_script render --run runs/narration-01 --share   # also video-720p.mp4 for sharing
python -m capstone_script render --run runs/narration-01 --theme night --no-music   # darker look, no music bed
python -m capstone_script render --run runs/narration-01 --look sketch   # hand-drawn people and objects in motion scenes
python -m capstone_script render --run runs/narration-01 --concurrency 2   # fewer browser tabs, for 8 GB laptops

# Check a few frames as PNG files without rendering the whole video
cd renderer
node scripts/stills.mjs ../runs/narration-01/video/timeline.json ../runs/narration-01/stills 30 400 900

# Open Remotion Studio with a built-in demo timeline, to work on the design
npx remotion studio src/index.ts
```

A full render also writes `thumbnail.png` from the title card and
`video-info.json` with the probed length, size and render time. `--share`
adds `video-720p.mp4`, re-encoded with the FFmpeg that ships with Remotion
(the seven-minute video drops from 34 MB to 8.6 MB). The `render` command
refuses an existing `video.mp4`; delete it to render again. Deleting
`video/` rebuilds the timeline on the next render.

`--concurrency N` sets how many frames Remotion draws at once, each in its
own headless browser tab. Without it Remotion uses about half the CPU cores.
On a MacBook with 8 GB of memory, the seven-minute queue video crashed at the
default and finished in 18 minutes with two tabs
([review](reviews/2026-10-20-queues-7min.md)), so use `--concurrency 2`, or
`1` if it still crashes. `run --render` and `ensure-duration --render` accept
the same option, and `video-info.json` records the value used (`null` for the
default).

For illustrated motion, rendering first writes `motion-inspection.json` in
the run folder. It checks body bounds on every frame, identifies long static
holds, records process-event coverage and suggests absolute video frames to
inspect. Possible contacts are review warnings, since some raw motion scenes
deliberately dock objects together. A passed report does not verify factual
accuracy, labels or teaching quality; inspect rendered frames too. The report
path and status are included in `video-info.json`.

To run the same diagnostics without encoding an MP4:

```bash
node renderer/scripts/inspect-motion.mjs runs/narration-01/video/timeline.json runs/narration-01/motion-inspection.json
```

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
| `chapters.txt` | Long plans only: chapter start times as "0:00 Title" lines, the form video sites read for chapters |

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
| `src/scenes/ComparisonScene.tsx` | Two labelled columns with a "vs" badge between them |
| `src/scenes/DefinitionScene.tsx` | A key term, its definition and an optional example |
| `src/scenes/EventTimelineScene.tsx` | Two to five dated events on a line that draws itself, with the current event highlighted |
| `src/scenes/StatScene.tsx` | One to three large numbers that count up, with labels and an optional note |
| `src/scenes/QuoteScene.tsx` | A quotation in serif type whose words light up as it is read, then who said it |
| `src/scenes/MapScene.tsx` | A full-frame map grid of one region with pins, an optional route drawn leg by leg, and country groups |
| `src/motion/MotionScene.tsx` | Persistent illustrated actors, narration-bound actions, routes and labels on a shared stage |
| `src/motion/engine.ts` | Deterministic state evaluation, distance-based path travel and physical-coordinate orbits |
| `src/Backdrop.tsx` | The moving background, and the push transition between cards and scenes |
| `src/scenes/SlideIcon.tsx` | The optional icon of a slide, node or column, from Lucide (ISC license) |
| `src/Overlays.tsx` | Captions and the progress bar with chapter marks |
| `src/theme.ts` | The `light` and `night` themes (colors, fonts) and motion timing |

Points, steps, columns and examples appear when the narration first
highlights them, the current one is highlighted while it is being talked
about, and an item that is never highlighted appears just after its scene
starts. Icons take the highlight color with
their item and sketch themselves in stroke by stroke, and a concept slide
without points shows its statement and icon larger so the slide does not look
half empty. Titles rise in word by word. Captions show the spoken line and stay
up through the short gaps inside a scene, except while a quotation is read
aloud, since the quote is already on screen. Each card and scene slides in from
the right while the previous one slides out to the left, overlapping by 14
frames, over a backdrop of slowly drifting light; the outgoing one is gone
before the incoming one is fully visible, so their text never stacks. Related
process scenes dissolve in place instead (see MOTION_GUIDE.md). Fonts are system fonts, so
rendering works offline.

Motion scenes use original SVG illustrations drawn straight on the shared
backdrop, with the theme's ink and type, instead of slide cards. Their object state persists between actions, and any frame can
be rendered directly without replaying earlier frames. Actions use absolute
frames compiled from the real narration. See [MOTION_GUIDE.md](MOTION_GUIDE.md)
for the reusable contract, local samples, verification and remaining limits.

## Themes and music

`--theme light` (the default) keeps the look of the browser preview;
`--theme night` is a darker, documentary style with a gold accent. Both are in
`src/theme.ts`, and every component reads the current one with `useTheme()`.

`--look vector` (the default) draws motion scenes with the code-drawn shapes.
`--look sketch` draws people as Open Peeps line art (Pablo Stanley, CC0, through
`react-peeps`, MIT) with rigged legs that step with the distance walked, and
counters, workbenches, servers, boxes, packets and coins with rough.js (MIT).
Outfits and hair come from each actor's id and every rough.js shape is seeded by
its entity id, so a drawing is identical on every frame and in every related
shot; the highlighted actor's clothes take its colour. Process stages in this look
are framed closer (departures walk out of the shot), and labels use the
hand-lettered Patrick Hand font from `@remotion/google-fonts`, which is fetched
from Google Fonts when the render starts, so a sketch render needs a network
connection. The code is in `src/motion/sketch.tsx`.

Unless `--no-music` is given, `render` also writes `video/music.wav`, a quiet
music bed synthesized by `capstone_script/music.py`: slow pad chords over a
soft bass, a few bell notes and a synthetic reverb, generated with numpy from a
fixed seed, so there is nothing to download or license. The bed sits about
6 dB below the narration's average loudness during the title and chapter
cards and ducks another 12 dB, starting a moment before each line, while the
narrator speaks. The theme and the music choice go into `video/props.json`
(the timeline plus those two settings), which is what Remotion receives;
`timeline.json` itself is unchanged. `node scripts/stills.mjs` accepts either
file.

The map template draws its region on a latitude and longitude grid, with the
places, route and country-group labels from the plan. It does not draw
country borders or coastlines yet, because that needs map data that is not
installed (for example the `world-atlas` package, from Natural Earth).

## Measured results

Windows 11, Ryzen 7 5800HS (8 cores, 15 GB RAM), Node 26.10, Remotion 4.0.531
with its default concurrency, full size (1920x1080, H.264 video and AAC audio):

| Run | Scenes | Frames | Length | Render time | File |
| --- | ---: | ---: | ---: | ---: | ---: |
| Retrieval-augmented generation for business users | 5 | 2,876 | 95.9 s | 120 s (24 frames per second) | 7.4 MB |
| How AI search engines find answers (7 chapters, reviewed) | 26 | 12,830 | 427.7 s | 528 s (24 frames per second) | 34.4 MB |
| Why AI chatbots make things up (all four templates, reviewed) | 5 | 2,684 | 89.5 s | 109 s (25 frames per second) | 7.2 MB |
| How AI search engines find answers, remade with four templates and 47 icons* | 25 | 13,473 | 449.1 s | 601 s (22 frames per second) | 38.8 MB |

\* Rendered while another job was voicing scripts on the same CPU.

The probed length of each MP4 matched its timeline within 0.01 s. Rendering
runs at about 24 frames per second here, so a video takes about 1.2 times its
own length to render. Narrating the seven-minute plan took another 4.3 minutes
(94 lines, 396 s of speech, 4 CPU threads).

The default H.264 quality is high for flat slides; `--share` makes the
smaller 720p copy described above.

The five hand-written storyboards in `examples/handwritten/` were rendered on
the same laptop with `--theme night --share`, so with the moving backdrop,
transitions and music bed:

| Video | Scenes | Frames | Length | Render time | File | 720p copy |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| The Silk Road | 25 | 15,711 | 523.7 s | 828 s (19.0 frames per second) | 100.3 MB | 20.2 MB |
| How World War II Reshaped the World | 24 | 15,133 | 504.4 s | 783 s (19.3 frames per second) | 95.3 MB | 19.4 MB |
| The First Emperor | 23 | 14,649 | 488.3 s | 752 s (19.5 frames per second) | 83.5 MB | 18.4 MB |
| The Day the Dinosaurs Died* | 23 | 14,217 | 473.9 s | 808 s (17.6 frames per second) | 83.1 MB | 18.1 MB |
| Apollo 11 | 24 | 14,201 | 473.4 s | 703 s (20.2 frames per second) | 88.5 MB | 18.4 MB |

\* Rendered while another video was being re-encoded on the same CPU.

Every probed length matched its timeline within 0.02 s. The moving backdrop
and gradients cost about 20 percent of the render speed and more than double
the file size of the plain slides. The `--share` copies are still near 20 MB;
for an upload limit around 10 MB, re-encoding at CRF 37 with mono 48 kbps
audio gave 8.7 to 9.7 MB copies that still look clean.
