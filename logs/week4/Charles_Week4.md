# Charles - Week 4 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation  
**Date:** October 30, 2026  
**Branch:** `feat/smooth-consistent-motion`  
**Focus:** Frame-to-frame consistency and motion smoothness in illustrated (process) scenes, after Hamza's review of the checkout-counter clip

## Contribution to the capstone

Hamza (Traversaal) reviewed our 61-second clip "Why a Second Checkout Counter
Cuts Waiting" (web studio job `ec1ba896`) on October 30 and asked us to close
the gap to his hand-drawn reference reels by working on frame-to-frame
consistency and motion smoothness. This week's work changes the renderer and
the process compiler so the same script renders with a steady stage and
continuous movement. Visuals are still code-rendered only (Level 1); no API
calls were made.

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
- Docs: MOTION_GUIDE.md and RENDERER_GUIDE.md describe the new behaviour.

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
- Renderer tests: 46 pass (`npm run test:motion`), including new tests for
  the walk easing, planned label sides, locked framing, carry/idle poses and
  colour blending. `npx tsc --noEmit` is clean.
- Python tests: 318 of 321 pass; the 3 errors are the same on main (Windows
  `os.killpg`/`SIGKILL` in the web worker tests and one preview test).
- Motion inspection: 0 collisions before and after.

## Remaining work

- Fonts are system fonts, so a Mac and a Windows render wrap captions
  differently. Bundling one font would make renders identical across
  machines (needs a new package).
- Characters still face the camera while walking sideways.
- The human scorecard should rate the new clip before we call it better.

## How to run

```bash
python -m capstone_script narrate --plan fixtures/scene-plan.checkout-counters.json --out runs/checkout
python -m capstone_script render --run runs/checkout --share
```

Renderer tests: `cd renderer && npm run test:motion`.
