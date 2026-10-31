# Charles - Week 4 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 30, 2026  
**Branch:** `feat/sketch-style` (contains `feat/smooth-consistent-motion`)  
**Focus:** Frame-to-frame consistency, motion smoothness and a hand-drawn look for illustrated (process) scenes, after Hamza's review of the checkout-counter clip

## Contribution to the capstone

Hamza (Traversaal) reviewed our 61-second clip "Why a Second Checkout Counter
Cuts Waiting" (web studio job `ec1ba896`) on October 30 and asked us to close
the gap to his hand-drawn reference reels by working on frame-to-frame
consistency and motion smoothness. This week's work changes the renderer and
the process compiler so the same script renders with a steady stage and
continuous movement, and adds an optional hand-drawn look (`--look sketch`)
with line-art people who walk on rigged legs. Visuals are still code-rendered
only (Level 1); no API calls were made.

```text
Topic -> Script and scene plan -> TTS narration -> Timeline and visuals -> Final video
                                                   ^ this week's work
```

## What the old clip did

Read frame by frame from the clip:

- The camera zoomed in on every long hold and back out before each move, so
  the shoppers and counters changed size and position several times a scene.
- "Counter 1" jumped between below and above its counter whenever someone
  stood at or walked past it.
- The waiting / in-service / unfinished strip disappeared during every move
  and came back after it, six times in 61 seconds.
- Walks used a cubic ease, peaking at three times the average speed, and took
  90-degree corners at full speed. Leaving shoppers stopped at the exit and
  faded out on the spot. Items appeared in a shopper's hands on one frame,
  and the second counter switched from grey to open on one frame.
- The two scenes show the same stage, but the cut between them slid the whole
  stage out to the left and back in from the right.
- The title card used the cool slide backdrop and the stage a cream paper
  background, with different text colours.

## Completed work

- **One locked camera per stage.** Related process scenes share one fixed
  wide view; the per-hold zoom is gone.
- **Labels stay put.** Each label's side is planned once over every frame of
  the scene (and of every related scene), not chosen frame by frame. Station
  labels sit beside their counter, clear of the queue and of the exit routes.
- **Counts roll instead of blinking.** The strip stays on screen and a changed
  number rolls to its new value over 9 frames.
- **Steady walking.** A new `walk` easing: smooth start and stop over a
  quarter of the move each, one steady pace between (top speed 1.33x the
  average). Route corners are rounded (radius up to 60 px, inside the corner
  only). A leaving shopper keeps walking while fading out.
- **No pops.** Items rise into the hands over 7 frames and sink after
  service; service and completion marks grow in over 8 frames; an opening
  counter brightens from grey across its opening interval; idle shoppers
  breathe and blink on slow per-actor cycles; walking adds a small bob.
- **Transitions.** Shots of one stage dissolve in place (additive blend, so
  the shared counters never dim). Elsewhere the old card is gone before the
  new one is fully visible, so two titles never stack.
- **One look.** Motion scenes draw on the shared backdrop with the theme's
  ink and type; the illustration palette uses cool neutrals to match.
- **Captions ease between lines.** Each caption is laid out from measured
  text widths (balanced rows, as before), so on a line change the old words
  fade, the box eases to the new size and the new words fade in, instead of
  the box snapping to a new width on one frame.
- **Small touches.** A walker's face turns toward where they are going and
  back as they stop; when the line moves up, each shopper starts 4 frames
  after the one in front; a counting statistic keeps its final width so the
  number no longer shifts sideways as digits appear.
- Docs: MOTION_GUIDE.md and RENDERER_GUIDE.md describe the new behaviour.

### Hand-drawn look (`--look sketch`)

Smoother motion alone could not close the gap: the vector people and counters
are still visibly built from circles and rectangles. The sketch look replaces
the drawings, not the pipeline: the scene plan still says only who goes where
and when, and the renderer decides how it is drawn.

- **People:** Open Peeps line art (Pablo Stanley, CC0, via `react-peeps`, MIT).
  Each actor's outfit and hair come from its id, so the same shopper looks the
  same in every frame and every shot; the highlighted shopper's clothes take
  the accent colour.
- **Walking legs:** an Open Peeps figure is one drawing, so dragging it looks
  like sliding a cut-out. The drawing is kept down to the hips and the legs are
  a rig (hip, knee, ankle, sneaker) whose steps follow the distance walked; a
  forward-swinging leg bends at the knee and both stand straight at a stop.
  The body rides up over each step and leans into the walk; a blink swaps in
  the closed-eyes face.
- **Objects:** counters, workbenches, servers, boxes, packets and coins are
  drawn with rough.js (MIT), seeded by the entity id so the wobbly lines never
  change between frames.
- **Framing and type:** process stages in this look frame only where people
  stand, so the cast is larger and departures walk out of the shot; labels use
  the hand-lettered Patrick Hand font from the official `@remotion/google-fonts`
  package (fetched when a sketch render starts).
- Lottie walk cycles were considered and not used: LottieFiles' free licence
  allows commercial use but not redistributing the files on their own (so they
  could not live in the repo), and no consistent, recolourable set of several
  characters was found.

## Validation

- Rebuilt the clip's scene plan from the video itself (captions give the 14
  lines; caption changes give each line's exact frames; stage motion gives
  the events). Rendering it with main's renderer and the original soundtrack
  matches the original clip frame for frame apart from Windows versus macOS
  fonts. The plan is checked in as
  `fixtures/scene-plan.checkout-counters.json`.
- Re-rendered with this branch, same script, timing and soundtrack. After the
  title card, frames whose picture changes by more than 1.0 (mean grey level,
  320x140) dropped from 95 to 0, and the largest frame-to-frame change from
  2.67 to 0.68.
- Full 61-second sketch render of the same clip: `runs/ec1ba896-sketch`.
- Renderer tests: 48 pass (`npm run test:motion`), including new tests for
  the walk easing, planned label sides, locked framing, carry/idle poses,
  colour blending, caption layout and the sketch legs' stride. `npx tsc --noEmit` is clean.
- Python tests: 320 of 323 pass (new tests: the line moves up front first; the
  look option); the 3 errors are the same on main (Windows
  `os.killpg`/`SIGKILL` in the web worker tests and one preview test).
- Motion inspection: 0 collisions before and after.

## Remaining work

- Fonts outside the sketch labels are system fonts, so a Mac and a Windows
  render wrap captions differently; the same `@remotion/google-fonts` package
  could load one font for everything.
- The sketch look has no metaphor characters yet (for example ducklings for a
  queue), and the planner prompt does not choose a look.
- The web studio does not offer the look option yet.
- The human scorecard should rate the new clip before we call it better.

## How to run

```bash
python -m capstone_script narrate --plan fixtures/scene-plan.checkout-counters.json --out runs/checkout
python -m capstone_script render --run runs/checkout --share
python -m capstone_script render --run runs/checkout-sketch --share --look sketch
```

(Narrate into a second folder for the sketch render, or delete `video.mp4` first.)

Renderer tests: `cd renderer && npm run test:motion`.
