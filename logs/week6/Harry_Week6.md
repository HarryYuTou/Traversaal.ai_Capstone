# Harry - Week 6 Progress Log

**Project:** Traversaal.ai Capstone, Project A - AI Explainer Video Generation

**Date:** November 9, 2026

**Implementation branch:** `video-quality-improvement2`

**Focus:** Model-authored objects, articulated actions, automatic framing, and stable physical contact

## Contribution to the capstone

Extended the Week 5 animation work beyond the predefined object library and
its supported actions. The model can now describe a new 2D object using
vector shapes, connected parts, and animation clips, then schedule its
performance against narration. Remotion renders that description
deterministically, without an image- or video-generation model.

Built on this capability by improving automatic composition, adding explicit
contact constraints, and making articulated performances flow more naturally.
These changes belong to the shared planning, validation, timeline, and
rendering pipeline; they do not require a new runtime preset for each topic.
Verification followed the requested sequence: complete framing and contact
work, pass its acceptance gate, then improve acting and run final acceptance.

## Completed work

### Model-authored objects and articulated actions

- Added `kind: "custom"` objects with reusable rig definitions, parent-child
  part hierarchies, local joints, and named animation clips. The model can
  design new silhouettes and independently moving parts rather than only
  selecting an existing drawing and moving it across the screen.
- Supported bounded rectangles, ellipses, and restricted vector paths.
  Generated output is validated data, not executable React, arbitrary SVG
  markup, or a generated video.
- Added narration-relative `performances` for translation, rotation, scale,
  and opacity tracks on individual parts. Completed poses remain held;
  repeated clips must return to their starting pose to avoid loop jumps.
- Reused the same geometry across frames and evaluated poses from absolute
  timeline time. Out-of-order rendering and seeking reproduce the same
  state. Continuing objects preserve their shape and hierarchy across scenes,
  while the next shot explicitly establishes its starting pose.
- Added structural and semantic checks for references, hierarchy cycles,
  geometry bounds, overlapping channels, accumulated poses, and timing.
  Existing plans may omit the new fields without changing their plan hashes.

### Automatic framing and stable composition

- Fitted custom-object scenes to their full articulated motion, travel
  routes, and solved contact positions. Related shots share a fixed camera
  instead of reframing as an arm, wing, or other part moves.
- Calculated bounds from actual authored rotation intervals. A small joint
  movement or body turn no longer reserves an entire circular sweep and
  unnecessarily shrinks the subject.
- Retained asymmetric bounds for long arms, stems, and other off-center
  shapes. Camera fitting, custom-object label placement, and spatial
  inspection use the same directional bounds.
- Included faint but visible custom objects in framing, preserved the
  conservative geometry safety limits, and retained existing stock-only
  framing behavior.

### Contact constraints and continuous release

- Added explicit `contacts` linking a local point on one entity to a point
  on another entity or articulated part. The source translates to keep its
  anchor aligned while the target moves or performs an action.
- Supported a foot planted on a platform, a subject perched on a moving
  support, and a separate object held by a gripper through the same mechanism.
- Applied already-established contacts from the first scene frame,
  including the lead-in before narration. Later contacts acquire smoothly
  over a declared interval instead of snapping into place.
- Retained the solved position offset after release, so subsequent free
  movement does not reset the object to its earlier authored location.
- Validated contact references, acyclic relationships, acquisition timing,
  and conflicts with simultaneous source movement. Visual repair preserves
  existing contact relationships rather than removing them to hide an error.

### More coherent performance and acting

- Added an optional `smooth` interpolation mode for complete part tracks.
  Shape-preserving cubic interpolation lets monotonic motion pass through
  intermediate keys without stopping at every key or introducing overshoot.
- Supported settled endpoints for single performances and matching velocity
  at internal seams of repeated performances. Existing easing modes retain
  their behavior.
- Updated planning guidance to allocate readable preparation, main action,
  and settling or result holds. Secondary motion should follow its cause
  with an authored delay, rather than every part moving in phase.
- Demonstrated a grounded presenter's weight shift and gesture, a gripper
  closing before lifting and carrying, and a butterfly preparing its wings,
  releasing from a leaf, tucking its feet, and flying away.
- Kept deliberate rests and quiet machinery valid. The system does not add
  arbitrary wobble or assume that every object should move continuously.

### Planning, review, and production quality checks

- Strengthened planner and reviewer instructions to design visible contact
  surfaces before choosing anchors. They must account for local geometry,
  strokes, relative scale, part transforms, and stage coordinates, rather
  than treating a label or bounding box as a contact surface.
- Added guidance to compare the free source and target anchors at
  acquisition. Establishing a grip should not make an already-supported
  object sink, rise, or slide merely to correct a placement error.
- Added a bounded fallback for the service's explicit structured-schema
  size rejection. The same contract is supplied as JSON instructions, and
  full local validation remains mandatory. Other API errors do not trigger
  this fallback; run metadata records the actual output mode and effort.
- Added a production spatial preflight using the actual render properties.
  It checks locked anchors, position continuity near contact boundaries,
  actor containment, and shared cameras. Failed or incomplete checks block
  rendering for custom/contact scene groups.
- Integrated spatial status into render metadata and quality scorecards.
  Unrelated legacy groups remain advisory, preserving intentional departures
  outside older process close-ups. Ordinary overlap and hold warnings remain
  available for visual review.
- Updated the custom-object documentation, renderer guide, schema,
  acceptance fixtures, and reproducible preview scripts.

## Validation results

### Automated checks

| Check | Final recorded result |
| --- | --- |
| Complete Python test suite | 380 passed |
| Complete renderer test suite | 187 passed |
| **Total automated tests** | **567 passed** |
| Renderer TypeScript check | Passed |
| Change formatting | `git diff --check` passed |

The planner-focused tests also passed after the final prompt update. These
are final suite totals, not additional tests to be added to earlier gate
counts or repeated focused checks. Coverage includes contact acquisition
and release, hierarchy transforms, motion bounds, continuous interpolation,
loop seams, random seeking, frame-rate consistency, and legacy behavior.

### Staged acceptance and rendered examples

The first gate covered composition and contact before acting changes began.
Its rendered baseline exposed gripper tips penetrating the pedestal. The
geometry was corrected and rendered again before proceeding. The approved
baseline passed 501 locked-frame checks with no measured boundary position
jump or viewport excess.

| Final example | Output | Verification purpose |
| --- | --- | --- |
| Authored three-scene acceptance reel | 28.7 s, 1280 × 720, 30 fps, silent | Human stance/gesture, gripper transfer, butterfly support/release and flight |
| Fresh model-generated gripper video | 31.936 s, 1920 × 1080, 30 fps, narrated | Normal prompt → planning/review → offline TTS → production rendering |

The authored reel uses synthetic narration timing and is not evidence of
live model generation. Its 23 parts and contact anchors retain the approved
baseline geometry while the performances are refined. Final inspection
checked 519 locked frames: maximum anchor error was approximately
`1.14e-13` stage units, with zero measured boundary position jump and
viewport excess. Both feet remained grounded; the gripper cleared its
support before horizontal travel; the butterfly tucked its feet after release.

The live test used the same gripper prompt twice. The first attempt passed
numerical checks but failed rendered-frame review: a stock parcel floated
above its table and moved downward when the grasp acquired. This exposed
the difference between aligned anchors and correctly drawn contact surfaces.
The general planning/review guidance was improved before generating again.

In the accepted second run, the model generated the table, parcel, gripper,
clips, actions, and contacts. Normal review rewrote three narration lines;
there were no manual plan edits or visual repairs to the accepted geometry.
An independent geometry audit confirmed zero support gap, zero acquisition
displacement, correct closed jaw contact, and matching poses across the cut.
The production spatial check passed 460 locked frames with no measured
boundary position jump or viewport excess and one stable shared-camera
transition. Recorded planning/review cost was approximately $0.35 for this
accepted run only.

Inspected rendered checkpoints covering support, approach, closure,
acquisition, scene transition, lift, carry, and the final hold. Both final
videos decoded successfully; the live output includes offline-generated
speech and the normal music bed, with a separate 720p sharing copy.
Conservative overlap warnings and the explicitly narrated pause were reviewed
and documented rather than silently removed from the diagnostics.

## Current scope and remaining work

- New subjects can be described within the bounded 2D geometry and rig
  contract without adding a dedicated renderer for each one. This does not
  guarantee convincing geometry or professional animation for every prompt.
- Contacts constrain translation at one anchor. They do not infer collisions,
  bend limbs through inverse kinematics, solve multiple planted feet,
  inherit target rotation, or transfer velocity and inertia after release.
- The model still authors meaningful contact points, poses, timing, and
  cross-scene continuity. Smooth interpolation does not generate acting by
  itself; complex interactions may need simpler choreography.
- Passing numerical checks does not establish visual or physical correctness.
  Future generated cases still require rendered-frame and editorial review.
  This iteration's evidence includes sampled encoded frames and complete
  decoding, not a claim of full human playback/listening or arbitrary-topic
  reliability. The final acceptance videos use the vector look.

## Evidence and related files

- [Custom objects and articulated actions](../../docs/custom-rigs.md)
- [Renderer guide](../../docs/RENDERER_GUIDE.md)
- [Quality scorecard guide](../../docs/QUALITY_SCORECARD.md)
- [Custom-object fixture](../../fixtures/scene-plan.custom-rigs.json)
- [Spatial and acting fixture](../../fixtures/scene-plan.spatial-quality.json)
- [Spatial preview script](../../renderer/scripts/spatial-quality-preview.mjs)
- [Spatial inspection script](../../renderer/scripts/inspect-spatial.mjs)

Generated media and detailed acceptance records are local artifacts in the
Git-ignored `runs/` directory. The folder uses the UTC date; acceptance was
completed on November 9 in the local time zone.

```text
runs/spatial-quality-20261110/verification.md
runs/spatial-quality-20261110/acceptance.json
runs/spatial-quality-20261110/python-tests-final.log
runs/spatial-quality-20261110/renderer-tests-final.log
runs/spatial-quality-20261110/phase1-approved/spatial-quality-vector.mp4
runs/spatial-quality-20261110/delivery-preview/spatial-quality-vector.mp4
runs/spatial-quality-20261110/delivery-preview/spatial-audit.json
runs/spatial-quality-20261110/live-gripper-v2/geometry-audit.json
runs/spatial-quality-20261110/live-gripper-v2-narrated/video.mp4
runs/spatial-quality-20261110/live-gripper-v2-narrated/video-720p.mp4
runs/spatial-quality-20261110/live-gripper-v2-narrated/spatial-inspection.json
```

At the time of this log, the implementation and documentation remain local
working-tree changes on `video-quality-improvement2`; this work has not been
committed or pushed.
