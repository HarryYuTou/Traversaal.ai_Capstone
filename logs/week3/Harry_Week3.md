# Harry - Week 3 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation

**Date:** October 19, 2026

**Branch:** `Video-generation-refine`

**Focus:** Reusable illustrated animation and a verified seven-minute Level 1 video

## Contribution to the capstone

Improved the video generation pipeline in response to the professor's feedback
that the earlier output looked like a slide deck. The work focuses on showing
an explanation through objects and actions: people queue and receive service,
parcels move through workbenches, and packets travel or wait for processing.

Implemented reusable animation capabilities, connected them to real Claude
planning and measured narration, and produced a **7 minute 14 second** video
with six chapters, subtitles, music, and 1080p output. The final storyboard
comes from actual API responses and an automatic narration review. Its visual
events were not manually restaged to make the demonstration work.

```text
Topic and audience -> Claude scene plan -> Measured Kokoro narration
                   -> Python timing and staging -> Remotion animation -> MP4
```

The work extends the existing script, narration, rendering, and web modules.
It does not introduce a separate text-to-video model or a new paid speech
service. Existing slide-based templates remain available for suitable content.

## Completed work

### Reusable motion scenes

- Added the `motion` scene format with persistent object identities, paths,
  and narration-relative actions. Supported actions include movement along
  paths, orbiting, rotation, scaling, fading, and changing displayed values.
- Built original SVG illustrations for people, spacecraft, planets, packets,
  computers, parcels, and service equipment, with consistent styling across
  Light and Night themes.
- Implemented deterministic frame evaluation in TypeScript: the same frame
  produces the same object positions and poses, including when seeking or
  rendering frames out of order.
- Added path interpolation, easing, object and label placement, and automatic
  fitting of each scene's full trajectory into the available picture area.
- Created Apollo and network examples that share the same rendering engine.
  Their storyboards specify the objects and actions; the renderer does not
  contain a separate implementation for each topic.

### Semantic process scenes and automatic staging

- Added a higher-level `process` scene format for arrival, waiting, service,
  and completion. Claude chooses actors, stations, initial state, and events
  using `arrive`, `start`, `finish`, and `hold` instructions.
- Implemented `capstone_script/process.py` to translate these instructions
  into positions, routes, timed movement, work activities, and departures.
  The current vocabulary supports 1–8 people, packets, boxes, or coins and
  1–2 counters, servers, or workbenches per scene.
- Enforced queue order, station occupancy, valid actor lifecycles, and
  non-overlapping events. A finished actor cannot silently reappear as a
  new arrival, and an occupied station cannot accept another actor.
- Added automatic queue compaction, parallel service at two stations, and
  separate approach and exit routes to reduce object collisions.
- Added distance-based walking poses, visible work activity, and completion
  cues. Characters stop walking when they stop moving; completion requires
  an explicit finish event.
- Derived the on-screen waiting, in-service, and unfinished counts from
  actual process state. Counts update at physical movement milestones and
  are hidden during ambiguous transitions.
- Removed a decorative parcel from the workbench illustration so that every
  visible parcel corresponds to a declared, counted actor.

The action implementations are predefined, but their participants, ordering,
and timing come from each generated plan. Python calculates the animation
instructions; TypeScript evaluates and draws each frame. New unsupported
actions still require implementation work.

### Narration timing and planning reliability

- Anchored movement to the actual duration of each Kokoro narration line,
  using the same 30 fps timeline as subtitles and audio placement.
- Added minimum visible intervals for travel, work, completion, and exit.
  Invalid timing fails with a diagnostic instead of silently skipping an
  action or extending it into another event.
- Addressed a real provider rejection of the combined template schema by
  adding a compact template-selection request. Planning then receives only
  the selected template families and their required schema definitions.
- Reused the selected template families across long-form chapters and
  preserved the existing bounded validation-repair workflow.
- Improved planner and reviewer prompts to preserve object meanings,
  distinguish waiting from service and total unfinished work, demonstrate
  claims with visible events, and avoid unsupported numerical claims.
- Clarified that added capacity can reduce waiting or slow backlog growth
  without necessarily clearing the backlog. The long example visibly
  demonstrates both changing and unchanged unfinished counts.
- Preserved provider responses, token usage, validation findings, and review
  edits for auditing. Documented API credential setup through the ignored
  `.env` file and a credential-free `.env.example`; credentials stay on the server.

### Quality checks, previews, and frontend integration

- Added automatic `motion-inspection.json` reports before rendering. The
  inspector checks every frame for conservative body intersections and
  static holds, distinguishes declared holds, and suggests frames to review.
- Preserved a `processTrace` in the compiled timeline so queue, service,
  completion, and movement transitions can be inspected against the source
  events and narration.
- Updated the standalone script preview to identify motion/process scenes
  as a narration-only preview, describe their planned beats, and link to
  completed videos when available.
- Connected the new scene types through the existing web worker's planning,
  review, narration, timeline, and rendering path. The browser plays the
  resulting MP4 without needing its own animation renderer.
- Updated **Try a sample** to use the approximately 45-second network-motion
  story. It still performs real narration and rendering without a Claude call.
- Rebuilt the frontend, confirmed all local readiness checks passed, and
  opened the studio's sign-in page. Custom topics can use the existing
  30-second to ten-minute settings, including a seven-minute target.
- Added the motion/process guide and updated the README, quick start,
  script guide, renderer guide, and web documentation.

## Validation results

### Automated checks

| Check | Recorded result |
| --- | --- |
| Complete Python test suite | 231 tests passed |
| Renderer tests | 36 tests passed |
| Frontend tests | 22 tests passed |
| Renderer TypeScript check | Passed |
| Frontend type checking and production build | Passed |
| Change formatting | `git diff --check` passed |

Coverage includes source contracts, process lifecycle and occupancy, template
selection, chapter/review integration, measured narration timing, deterministic
motion and poses, state counts, diagnostics, and preview behavior. These are
recorded implementation checks; mocked tests alone do not verify a paid API
request or visual teaching quality.

### Real narration and rendering

| Example | Planning provenance | Encoded duration | Main render time |
| --- | --- | ---: | ---: |
| Apollo motion demonstration | Authored fixture | 46.101 s | 45.5 s |
| Network motion demonstration | Authored fixture | 47.168 s | 30.3 s |
| Short process explanation | Actual Claude plan, no manual restaging | 79.403 s | 76.0 s |
| Full process explanation | Actual Claude chapter plans and narration review | 434.475 s | 454.0 s |

All four examples use real Kokoro narration and 1920 × 1080, 30 fps output;
720p sharing copies were also produced. Render times exclude earlier planning
and narration stages, thumbnail generation, and sharing-copy encoding.
The authored demonstrations verify rendering capabilities, while the process
runs additionally verify automatic planning through the live API.
The process runs used `fixtures/reference-queue-expanded.md`, which supplies
factual reference material without authored scenes, coordinates, or actions.

### Seven-minute video

The final run is saved locally at:

```text
runs/live-process-queue-7min-20261019-02/
```

| Measurement | Recorded result |
| --- | --- |
| Title | Why Queues Grow, Linger, and Clear |
| Structure | 6 chapters, 14 scenes, 93 narration lines, 1,109 words |
| Scene types | 13 process scenes and 1 definition scene |
| Real speech duration | 407.825 seconds |
| Encoded MP4 duration | 434.475 seconds, approximately 7 min 14 s |
| Picture | 1920 × 1080, H.264, 30 fps |
| Decoded video frames | 13,034, exactly matching the timeline |
| Audio | AAC, 48 kHz, stereo mix |
| Full MP4 size | 50,632,693 bytes |
| 720p sharing copy | 12,101,727 bytes; duration matches the full video |

The outline required one repair for an overlong text field; all six chapter
plans passed on their first attempt. The automatic reviewer then changed
14 narration lines. The final plan matches the recorded review applied to
the original API plan. Seventy-nine unchanged audio lines were reused and
the 14 revised lines were synthesized again.

Every-frame diagnostics reported zero body-collision pairs and no undeclared
static holds of four seconds or longer. Three deliberate result/recap holds
remain, the longest approximately 10.6 seconds. Still inspection covered all
14 scenes and six chapter cards, and eight frames extracted from the final
MP4 were checked across all chapters. Full decoding verified the frame count
and audio stream. A full real-time listening review was not performed.

The accepted short run is in `runs/live-process-queue-20261019-02/`.
The reviewed long source plan is also saved as
[`fixtures/scene-plan.process-queue-long.json`](../../fixtures/scene-plan.process-queue-long.json),
so it can be reproduced without another planning API call. Generated media
and local diagnostic records remain under Git-ignored `runs/` directories.

### API usage and frontend verification boundary

The process iteration, including two short planning trials, long planning,
and the final review, used 97,181 input tokens and 55,446 output tokens over
14 requests. Estimated cost was **$1.4977** at the configured prices. Earlier
live-motion planning trials were separately estimated at **$0.6052**. These
are usage-based estimates, not billing receipts; the provider's billing
records remain authoritative. Copying the long planning record into the final
run did not create another API charge.

The short and seven-minute API-to-MP4 results above were produced through
the command-line pipeline. The frontend's shared pipeline integration,
production build, local readiness, and page loading were checked, but a new
custom-topic generation submitted and completed entirely through the browser
was not recorded in this iteration. The web form also does not expose the
reference-file input used in the queue examples. Readiness confirms installed
components and credential presence, not API credit or future request success.

## Current scope and remaining work

- This is a bounded 2D animation system. The planner combines supported
  objects and actions; it cannot reliably invent arbitrary illustrations,
  physical interactions, or character performances from any prompt.
- Object state persists within a scene. Cross-scene state, colors, and poses
  are not automatically inherited. Some parcel colors change in the final
  video, and an early scenario reset is not explicitly announced.
- Framing currently fits the scene's trajectories; it is not dynamic camera
  tracking. More varied staging, richer interactions, and smoother visual
  continuity are still needed to approach the professor's reference.
- Intentional holds and ongoing activity can pass motion checks while still
  feeling slow. The short sample retains one arrangement during an extended
  recap, and the long video's definition scene differs visually from its
  illustrated process scenes.
- Validate more unfamiliar topics, complete browser-based custom-topic runs,
  and conduct full listening and editorial reviews. One verified long video
  does not establish arbitrary-prompt reliability or complete the broader
  acceptance target of five seven-minute videos on non-AI topics.

At the time of this update, the implementation and documentation are local
working-tree changes on `Video-generation-refine`; they have not been
committed or pushed as part of this work.

## How to run

From the repository root with the existing dependencies and local model cache:

```bash
npm --prefix web run build
.venv/bin/python -m capstone_web
```

Open [Traversaal Studio](http://127.0.0.1:8000), sign in, choose **Your topic**,
and select a target length. Claude credentials are read from the server
environment or the ignored repository `.env` file. **Quick draft** produces
540p; disabling it produces 1080p. Keep the local server running throughout
generation. The final duration follows the actual narration.

To reproduce the saved seven-minute storyboard without a planning request:

```bash
.venv/bin/python -m capstone_script narrate --plan fixtures/scene-plan.process-queue-long.json --out runs/harry-week3-reproduction --offline
.venv/bin/python -m capstone_script render --run runs/harry-week3-reproduction --share
```

Use a new output directory for each reproduction. Related documentation:
[motion and process guide](../../docs/MOTION_GUIDE.md),
[web studio guide](../../docs/WEB_STUDIO.md),
[script guide](../../docs/SCRIPT_GUIDE.md), and
[renderer guide](../../docs/RENDERER_GUIDE.md).
