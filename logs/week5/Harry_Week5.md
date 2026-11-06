# Harry - Week 5 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation

**Date:** November 5, 2026

**Implementation branch:** `video-quality-improvement`

**Focus:** Frame-to-frame consistency, smoother character motion, and reusable object performance

## Contribution to the capstone

Improved the existing illustrated video pipeline in response to the
professor's feedback about frame-to-frame consistency and motion smoothness.
The work first addressed visual stability, then added clearer character
performance and extended expressive actions beyond the checkout example.

Testing with parcel and orbital topics showed that the initial vitality
improvements mainly benefited people. Added a shared semantic action layer
to the planner, compiler, and renderer so supported objects can visibly
perform an operation instead of only changing position. The implementation
continues to use deterministic, code-rendered animation without a
video-generation model.

## Completed work

### Stable framing, labels, and scene transitions

- Extended shared camera and label planning to related authored motion
  scenes as well as process scenes. Related shots keep one locked view;
  framing does not change simply because the visible cast changes.
- Reserved bounds for actual illustration sizes, including taller sketch
  characters, rotations, scaling, and the sketch font. Labels retain their
  side, anchor, and reading size throughout a related sequence.
- Kept background room and prop drawing seeds consistent across related
  shots so hand-drawn details do not change between frames or cuts.
- Removed overlapping scene intervals and sliding transition effects that
  could create doubled characters, ghosted titles, or brightness changes.
- Added boundary checks for visible objects, appearance, poses, routes,
  station states, and process counts. Continuous shots can cut directly;
  replays and resets fade within their own authored intervals.

### More readable character performance

- Added anticipatory attention before departure, body lean during movement,
  independent head and torso motion, a short settling motion after stopping,
  and an acknowledgement when service completes.
- Refined distance-based walking into supporting and swinging foot phases.
  Feet follow the actual travel direction while gaze can anticipate the
  next action. Breathing and blinking retain deterministic per-person timing.
- Applied the performance layer to supported people in both vector and
  sketch looks, including directly authored motion outside queue scenes.
  Authored positions, event times, routes, and process counts remain intact.
- Fixed the reported left/right twitch before customers walked to the
  counter. Tiny horizontal interpolation errors on a vertical route could
  trigger a full mirrored view change. Direction evaluation now ignores
  this noise and preserves the last meaningful horizontal orientation.
- Checked 5,310 person-frames from the supplied checkout timeline: no
  spurious mirror changes remained, and source positions were unchanged.
  Exported the corrected full video and a short departure preview.

### Expressive actions for other supported objects

- Added six narration-anchored semantic cues: `pack`, `scan`, `send`,
  `receive`, `compute`, and `thrust`. These articulate existing drawings
  independently of their movement tracks.
- Added parcel flap closure, sealing tape, and label attachment; surface
  scanning; packet and device transfer feedback; and visible device
  processing. Completed packaging persists while the parcel departs.
- Added explicit process-station operations for packing, scanning, and
  computing. Ongoing service cannot falsely produce a finished seal.
  Initial packing appearances keep waiting parcels open across scenes,
  while parcels already in service continue from their prepared state.
- Added short direction traces based on actual movement history. Orbit
  actions use their true center and physical radius for the guide; closed
  paths retain their authored geometry. Process travel routes stay hidden.
- Added fixed shading to planets and moons for depth. This does not invent
  lunar phases, self-rotation, or a different orbit. Spacecraft display
  propulsion only during an explicit burn cue, never merely because they
  are moving.
- Added responses to authored coin rotation, marker arrival, and gauge
  value changes. Gauge values remain exactly those defined in the plan.
- Preserved completion feedback across object types and kept server
  acknowledgements clear of the station's availability sign.

### Planning, validation, and compatibility

- Updated planner guidance, structured output, and JSON Schema to expose
  the new cues and station operations. Validation checks compatible asset
  types, valid references, narration anchors, and non-overlapping cues.
- Compiled cue timing from measured narration, using the existing timeline.
  Process cues preserve the original geometry, occupancy, and count logic.
- Extended motion inspection to recognize visible packing, scanning,
  communication, and computing without requiring position changes. Hidden
  or unsupported cues cannot conceal an otherwise static picture.
- Preserved legacy plan serialization: all nine checked saved narration
  manifests retained matching plan hashes. Existing narrated runs do not
  require new speech synthesis simply to load the updated code.
- Added a packing fixture, enhanced the network fixture, and created
  reproducible multi-scene preview scripts for both drawing styles.
- Updated the motion and renderer guides with the capabilities, authoring
  contract, verification commands, and limits.

## Validation results

### Automated checks

| Check | Final recorded result |
| --- | --- |
| Complete Python test suite | 336 passed |
| Renderer test suite | 125 passed |
| **Total automated tests** | **461 passed** |
| Renderer TypeScript check | Passed |
| Change formatting | `git diff --check` passed |

Coverage includes 19 entity kinds, cue compatibility, narration timing,
process lifecycle, packing continuity, completion visibility, camera and
label bounds, random seeking, and equivalent performance at 24, 30, and
60 fps. Regression checks also protect character direction, unchanged
authored geometry, and the absence of invented reception or propulsion.

These are the final suite totals, not additional tests to be added to the
earlier stability and departure-fix counts. Frontend code was not changed
in this iteration, and a new frontend validation run is not claimed.

### Rendered examples

| Example | Picture duration | Verification purpose |
| --- | ---: | --- |
| Corrected checkout video | 61.000 s | Character performance and departure-direction fix |
| Updated parcel video | 59.867 s | Packing stages, queue continuity, and persistent finished appearance |
| Updated orbital video | 29.933 s | Shading and direction cues with the original authored trajectory |
| Vector acceptance reel | 36.000 s | Packing, orbit, networking, burn/coast, and value changes |
| Sketch acceptance reel | 36.000 s | The same scenarios in the second drawing style |

These outputs are 1280 × 720 at 30 fps. The complete examples retain the
existing narration and music assets; both acceptance reels are silent.
Audio padding makes the complete MP4 container durations slightly longer
than the picture durations above.

The parcel copy explicitly selects packing to match its existing narration.
Its positions, routes, action times, activity intervals, and process counts
remain unchanged. The orbital example retains its original authored
timeline. Original source-run files were not overwritten.

Inspected encoded frames around packing stages, departures, scene cuts,
orbital travel, device reactions, powered flight, coasting, and value
changes in both looks. This caught and corrected a waiting-parcel appearance
reset and an acceptance-preview departure route crossing its workbench.
The updated parcel and orbital examples pass geometry/timing diagnostics;
the parcel retains two declared explanatory holds.

No new planning API or TTS request was used for these acceptance renders.
Schema, fixture, and compiler checks establish the integration contract;
they do not substitute for a fresh live prompt-to-video generation test.

## Current scope and remaining work

- The system remains a bounded animation framework. New characters,
  machinery, materials, and unsupported interactions require additional
  assets and action definitions; this does not establish equal quality
  for arbitrary prompts or attainment of the professor's reference level.
- Sketch heads and torsos articulate, but arms remain embedded in the
  garment artwork. Direction changes use mirrored views, and curved walking
  does not provide full world-space foot locking.
- The synthetic acceptance reel retains conservative warnings for intended
  object contact at transfer endpoints. Orbital labels can still become
  tightly grouped when the objects pass near one another.
- Automated checks and sampled-frame inspection do not replace full
  playback, listening, or editorial review. Further unfamiliar-topic tests
  are needed to assess how consistently planning selects the new actions.
- New web jobs load the updated pipeline; existing History videos remain
  unchanged and must be regenerated to show new capabilities.

## Evidence and related files

- [Motion and process guide](../../docs/MOTION_GUIDE.md)
- [Renderer guide](../../docs/RENDERER_GUIDE.md)
- [Packing fixture](../../fixtures/scene-plan.process-packing.json)
- [Network fixture](../../fixtures/scene-plan.motion-network.json)
- [Multi-scene preview script](../../renderer/scripts/broad-quality-preview.mjs)

Generated videos, inspection images, and detailed verification records are
local artifacts in the Git-ignored `runs/` directory:

```text
runs/video-quality-20261105/stability/
runs/video-quality-20261105/departure-fix/verification.md
runs/video-quality-20261105/departure-fix/capstone-quality-improved-v2.mp4
runs/video-quality-20261105/broad-vitality/verification.md
runs/video-quality-20261105/broad-vitality/renderer-tests.log
runs/video-quality-20261105/broad-vitality/media-info.json
runs/video-quality-20261105/broad-vitality/user-parcel/parcel-improved-v2.mp4
runs/video-quality-20261105/broad-vitality/user-orbit/orbit-improved.mp4
runs/video-quality-20261105/broad-vitality/preview-final-vector/broad-quality-vector.mp4
runs/video-quality-20261105/broad-vitality/preview-final-sketch/broad-quality-sketch.mp4
```

At the time of this log, the implementation and documentation remain local
working-tree changes on `video-quality-improvement`; this work has not been
committed or pushed.
