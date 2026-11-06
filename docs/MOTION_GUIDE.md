# Motion and Process Scenes

The Level 1 visual pipeline now supports reusable illustrated explanations.
A storyboard describes objects and what they do; Remotion evaluates their
state for each frame and exports an MP4. No image or video generation service
is involved. Kokoro still generates the narration locally on CPU.

The purpose is to replace text describing a process with a visible process:
Apollo's ascent cabin leaves its base on the Moon, and network packets take
different paths before reassembly. Both examples use the same renderer.

There are now two authoring levels. `process` describes a bounded workflow
through actors, stations and causal events; the compiler owns its geometry
and movement phases. `motion` gives direct control over object coordinates,
paths and property changes for explanations outside that workflow. Both
compile to frame-based SVG rendering. Existing slide and motion plans remain
valid with `schemaVersion: "1"`.

## Run a local sample

Use the existing Python environment and installed renderer dependencies.
`--offline` requires the already downloaded Kokoro model and voice. The first
Remotion render needs its cached browser, or internet access to install it.
Use a new output directory each time.

```bash
source .venv/bin/activate

# No Claude key is needed for either checked-in storyboard.
python -m capstone_script validate --plan fixtures/scene-plan.motion-apollo.json
python -m capstone_script narrate --plan fixtures/scene-plan.motion-apollo.json \
  --out runs/apollo-motion-demo --offline
python -m capstone_script render --run runs/apollo-motion-demo --share

python -m capstone_script narrate --plan fixtures/scene-plan.motion-network.json \
  --out runs/network-motion-demo --offline
python -m capstone_script render --run runs/network-motion-demo --share

python -m capstone_script narrate --plan fixtures/scene-plan.process-packing.json \
  --out runs/parcel-packing-demo --offline
python -m capstone_script render --run runs/parcel-packing-demo --share
```

The Studio's **Generate sample** action now uses the network storyboard with
real narration and rendering. Existing saved videos keep their own titles.
The HTML narration preview displays beat descriptions for motion scenes; it
is explicitly a listening preview. Inspect the rendered MP4 to judge motion.
After rendering, `python -m capstone_script preview --run <run>` adds the
available video link to that preview.

## Semantic process contract

Use `template: "process"` for arrivals, waiting, service and completion.
Examples include people receiving service, packets waiting for processing,
or parcels passing a workbench. The contract is deliberately limited to
**1–8 actors and 1–2 stations per scene**. It does not generate arbitrary
machines, detailed characters, unlimited crowds or a physical simulation.

The scene retains `id`, `purpose`, `template`, `visual` and 1–8 narration lines
with `id` and `text`. There are no narration highlight fields. Its visual has
these required fields:

| Field | Meaning |
| --- | --- |
| `title` | At most 60 characters |
| `actorKind` | One of `person`, `packet`, `box`, `coin`, shared by the scene's actors |
| `actors` | 1–8 `{id, color, label}` records; label is at most 24 characters or `""` |
| `stations` | 1–2 `{id, label, kind, color}` records with optional `initialState: "open" \| "closed"` and `operation: "generic" \| "pack" \| "scan" \| "compute"`; kind is `counter`, `server` or `workbench`, and label is 1–24 characters |
| `initialQueue` | Actor IDs in waiting order, front first |
| `initialService` | `{actorId, stationId}` pairs already receiving service |
| `events` | Up to 48 records describing the changes or deliberate holds |

Colors are `ink`, `accent`, `secondary` or `muted`. Actor and station IDs must
be unique and distinct. Every actor not in the initial queue or service list
starts outside the visible process. Each station can serve one actor, and
each actor can occupy only one position. Station positions are fixed within a
scene. A station's `initialState` explicitly sets whether it starts open or
closed. A closed station may remain closed for the entire scene without an
`open` event, preserving the layout of a one-counter baseline. If this field
is omitted or null, a station targeted by an `open` event starts closed and
other stations start open, preserving existing plans. Declare a future station
from the start so its opening changes availability without moving the other counters.
Continuing actors must be initialized consistently; keep their IDs, colors and
labels, and keep station IDs and ordering stable across related scenes.

An explicit station `operation` selects the mechanism shown during service.
`pack` requires box actors at a workbench; `scan` requires boxes or packets at
a workbench or server; `compute` requires packets at a server. The compiler
rejects unsupported combinations. `generic`, an omitted operation or null
preserves the original work feedback. Labels do not select an operation: a
legacy bench labeled "Packing" does not silently acquire new story actions.
New planner requests choose the operation from the narrated task. Packaging
closes flaps and adds a seal, scanning uses a scan line, and computing activates
packet/device details. These do not create workers, hands, contents or tools.

Every event has `kind`, `actorIds`, `stationIds`, `startLine`, `endLine`,
`startOffset` and `endOffset`, all required. The line anchors have the same
meaning as motion anchors described below. Events must be chronological,
have positive spans, and not overlap. They may meet at an endpoint. Parallel
actors belong in the same event, with actor/station arrays paired in order.

| Event | State change |
| --- | --- |
| `arrive` | One or more never-visible actors join the queue's end; `stationIds` is `[]` |
| `start` | Actors at the queue's front enter their paired free, open stations |
| `finish` | Currently served actors complete work at their paired stations, leave and disappear permanently within this scene |
| `open` | `actorIds` is `[]`; `stationIds` names one or two initially closed stations that become available for service |
| `hold` | Both ID arrays are `[]`; preserve the visible state for explanation and inspection |

The next logical state is established at the event's end. A departed actor
cannot be recycled as a new arrival. `start` cannot skip the front of the
queue, and `finish` must match the current station occupancy. A station may
open only once, cannot appear in `initialService` when initially closed, and
cannot receive a `start` until its opening finishes. Python checks
these rules beyond the exported JSON Schema. Planner coverage also requires
each narration line to overlap an event or explicit hold, and at least one
state-changing event per process scene. This is not a movement quota: a hold
is appropriate when the narration explains an existing state. A new causal
claim still needs a matching visible demonstration and factual review.

### Compilation and readable timing

The saved `scene-plan.json` remains the authored process plan. After Kokoro
measures the narration, `capstone_script/process.py` compiles events into
positions, routes, opacity changes and `work`/`complete` activity intervals.
It uses fixed queue slots, separate service positions and departure routes;
actors reach their exit before fading. Ongoing work means activity, not a
measured completion percentage. Only a `finish` event creates a completion
cue.

An opening retains the station in place and changes its visible `CLOSED` sign
to `OPENING` during the authored interval, then `OPEN` at completion. Allow a result hold after opening so the
new availability is readable before the next action or cut. For a comparison,
show both conditions with the same actors and stated assumptions; announce a
replay before resetting the queue. The checked-in
`fixtures/scene-plan.process-counter-comparison.json` demonstrates two versus
one completed service rounds without treating animation speed as real time.

The renderer gives people distance-based walking poses and visible work
gestures. Process route lines are hidden to avoid accumulating travel trails;
the same routes still determine movement. A small state strip reads the
compiled trace and shows waiting, in-service and total unfinished counts.
Future arrivals are excluded. The strip stays on screen; a count that changes
rolls to its new value over 9 frames. A person moves from waiting to in
service on reaching the counter, and leaves the total only after reaching the
exit. These are counts of the illustrated example, not measured performance
statistics.

Movement is tuned for frame-to-frame continuity. Process travel uses the
`walk` easing (compiler-only): a smooth start and stop over a quarter of the
move each and one steady pace in between, so a stride never lurches mid-route.
Routes turn on a short curve (radius up to 60 px) through the inside of each
corner. A departing person keeps walking while fading out, at most 60 px past
the exit point, rather than stopping and vanishing. Items rise into a
person's hands over 7 frames as service starts and sink away after it ends;
service and completion marks grow in over 8 frames; a station that opens
brightens from grey over its opening interval. Idle people breathe and blink
on slow, per-actor cycles that depend only on the frame, so any frame still
renders alone.

Process framing fits the visible cast and its complete routes instead of
reserving empty stage margins. Consecutive process scenes in the same chapter
that share actor and station IDs form one stage: they share one locked wide
view (the camera never zooms or re-frames), every label keeps one side for
all of them (station labels sit beside their station, clear of the routes),
and continuous boundaries cut without overlaying two casts. A replay or reset
fades through the backdrop in place, so the shared counters never slide or
change size. This does not repair incorrect source identity or
state: those remain planner and reviewer responsibilities.

### Reusable stability and character performance

Authored motion scenes also share one camera and label plan when consecutive
shots in the same chapter share an entity ID and kind. Labels reserve the
largest actor envelope and text size across those shots, including rotation,
scaling and the taller sketch people. They keep their side and anchor instead
of switching sides in the middle of movement. Layout uses the actual sketch
font size and viewport bounds. Object-array order does not change the plan.

Sharing a camera is separate from continuity at a cut. The renderer checks
visible actors, their appearance, position and pose at the boundary. A reset
of the cast fades in place, with each shot confined to its authored interval;
there is no overlapping copy of the outgoing character or title. Background
room and prop strokes use the shared stage seed and stay identical across
related shots.

People derive their performance from existing movement and activity tracks:
attention leads departure, the torso follows the movement, feet alternate
between support and swing, and the body settles after stopping. Attention
persists after a move. Work and completion drive reach and acknowledgement
rather than changing the underlying event schedule. Direction evaluation
ignores numerical noise. Vertical travel retains the
last meaningful horizontal direction from the authored route, so tiny rounding
errors cannot repeatedly mirror a character at departure. All poses are computed
from absolute frames, entity identity and the composition FPS, so random
seeking and parallel rendering reproduce the same result. Breathing and
blinking have per-actor offsets. Both vector and sketch figures use this pose
layer; the sketch drawing keeps its existing hair and garment selection.
Vector hands articulate during work. Sketch heads and torsos articulate
independently, but arms remain part of the original garment artwork; a full
sketch handoff requires separate arm assets rather than overlaying extra limbs.

These are renderer capabilities, not topic rules. They apply to every
supported person entity, including directly authored motion outside process
scenes. Other assets use their own bounded operation cues, described below;
they keep their authored geometry and do not acquire human gestures. This
does not supply new character species, arbitrary actions or missing
storyboards, and visual review is still needed for each final explanation.

### Semantic object performance

Motion visuals may now include optional `cues`, a list of up to 48 records.
Every authored record contains `entityId`, `kind`, `startLine`, `endLine`,
`startOffset` and `endOffset`. Timing uses the same measured narration anchors
as actions. The compiler retains those anchors and adds absolute `from` and
`durationInFrames`. Cue intervals must be positive and inside the scene;
same-entity cues cannot overlap. They can overlap that object's movement
action because they articulate details rather than changing its position.

| Cue | Supported entity kinds | Intended meaning |
| --- | --- | --- |
| `pack` | `box` | Close a parcel's flaps and seal it |
| `scan` | `box`, `packet` | A visible scanning pass |
| `send`, `receive` | `packet`, `server`, `laptop`, `cloud`, `satellite` | Emission or reception at a narrated transfer boundary |
| `compute` | `packet`, `server`, `laptop`, `cloud` | Ongoing processing, without invented percent completion |
| `thrust` | `spacecraft`, `rocket`, `lander`, `lander-ascent`, `satellite` | An explicitly narrated powered burn |

The process compiler emits these same cue records from explicit station
operations, only while the actor is at its service position. `pack` and
`scan` target the actor; `compute` targets both packet and server. Queue
positions, counts, paths, event timings and existing activity tracks remain
unchanged. A packing workflow also sets a compiler-only `packingState` on
every parcel, including waiting parcels whose work occurs in a later scene:
`open` for queued/future actors and `prepared` for actors already at a packing
station in `initialService`. This keeps waiting parcels open across cuts
instead of switching from a generic sealed box when a later cue appears.
Generic boxes receive no packing state. A compiled pack cue has `complete: true` only when work leads into
an authored finish; ongoing work ending at the scene boundary has
`complete: false`, so it cannot falsely seal the parcel. An actor already in
`initialService` has `continued: true`, retaining a partially packed pose
instead of reopening at the next scene. These two fields are compiler-only;
authored motion packing cues represent a complete packing action.

The planner now requests visible send/receive reactions around packet travel
and explicitly chooses process packing, scanning or computing when justified
by the topic. It keeps passive orbits continuous using a single linear orbit
action across related narration lines. An orbit is not evidence of thrust,
self-rotation or a changing lunar phase; those facts are never inferred from
motion alone. A gauge continues to display only its authored numeric value.
Existing plans without cues retain their source serialization and narration
hashes, so adding this capability does not require re-narrating saved runs.

Motion scenes also draw a short direction trace from the object's actual
position history. It is trimmed behind the object and fades at the action's
endpoints. Authored orbit actions gain a circular guide using the exact
physical radius; closed follow-path orbits retain their authored geometry.
Process scenes keep their hidden travel routes, and people never gain trails.
Planet and moon drawings have fixed surface shading for depth, not animated
phases or unrequested self-rotation. Completion marks, packing states and
direction graphics participate in continuity checks. The motion inspector
recognizes the rendered semantic parts, rather than mistaking stationary
packing or computation for a frozen picture.

This covers the current asset vocabulary and named operations, not every
possible real-world action. Unsupported machinery, materials and gestures
still need new assets and action definitions. Supporting slide templates
remain available when an honest diagram explains the idea better.

Run the regression suite and a silent, reproducible preview across a person,
parcel handling, a network and an orbit. These commands use no planner, TTS or
video-generation API. The preview includes return travel and service cues;
it is a visual acceptance fixture, not a narrated lesson.

```bash
cd renderer
npm run typecheck
npm run test:motion
node scripts/quality-preview.mjs ../runs/quality-vector vector
node scripts/quality-preview.mjs ../runs/quality-sketch sketch
```

Each preview writes its timeline, a 720p MP4 and four inspection frames. Use
a new output directory for each run. Check the video at normal speed as well
as the stills: unit tests establish geometry and timing, not acting quality.

For the extended nonhuman acceptance set (packing, lunar orbit, networking,
explicit spacecraft burn/coast and an illustrative value change), use:

```bash
node scripts/broad-quality-preview.mjs ../runs/broad-vector vector
node scripts/broad-quality-preview.mjs ../runs/broad-sketch sketch
```

This writes a silent 36-second video, the timeline, and inspection stills.
`--timeline-only` creates the inputs without launching a browser, so the same
timeline can also be rendered through the normal Remotion CLI.

The resulting `video/timeline.json` scene uses `template: "motion"` for the
existing renderer. Its `processTrace` records source events, measured frame
intervals, phases and queue/service/completion states before and after each
event. It also records `initialOpenStationIds`, `finalOpenStationIds` and each
event's `openStationsBefore`/`openStationsAfter`. Generated actions retain their source event anchors for provenance;
their absolute `from` and `durationInFrames` control playback. Expanded actions
are not a replacement source plan and need not fit the source motion
template's authored action-count limit.

At the pipeline's 30 fps, the compiler currently enforces these minimums:

| Event or phase | Minimum |
| --- | ---: |
| `arrive` | 18 frames (0.6 s) per actor, entering sequentially |
| `start` | 48 frames (1.6 s), reserving at least 18 travel frames and 30 visible work frames |
| `finish` | 44 frames (about 1.47 s): at least 12 completion, 24 exit travel and 8 fade frames |
| `open` | 18 frames (0.6 s), followed by a readable result hold when needed |
| Visible service before `finish` | 30 frames (1 s), including for actors in `initialService` |
| `hold` | A positive measured interval; one frame is structurally sufficient, not a recommended teaching duration |

These are readability floors, not preferred speeds or claims about real
service rates. Give `start` and `finish` meaningful full narration lines,
normally eight or more spoken words. Use small arrival batches or span
additional lines, and give initially serviced actors a visible work hold.
If measured audio makes an event too short, compilation reports the scene
and event rather than silently stretching speech or padding the video.
Revise the source narration or anchors and build a fresh run.

The compiler and contract tests establish deterministic state and timing
behavior. They do not establish teaching quality for every topic. Live
process acceptance results belong in the verification record after actual
narration, rendering and frame review; the earlier live results below used
the lower-level motion template.

## Direct motion contract

`schemaVersion` remains `"1"`; `motion` is an additive scene type. Existing
eight-template plans remain valid. A motion scene has the usual `id`,
`purpose`, `template`, `visual` and 1–8 short narration lines. Each narration
line has `id` and `text`; it has no slide highlight field.

`visual` has `title`, `entities`, `paths` and `actions`. Every listed nested
field is required, including unused zero values and empty strings. This keeps
the planner's structured-output schema compact. The complete examples are
the two `fixtures/scene-plan.motion-*.json` files.

| Part | Fields and meaning |
| --- | --- |
| Entity | `id`, `kind`, `x`, `y`, `size`, `rotation`, `opacity`, `value`, `color`, `label` |
| Path | `id`, `points` (`{x, y}`), `curved`, `closed`, `color` |
| Action | `entityId`, `kind`, `startLine`, `endLine`, `startOffset`, `endOffset`, `pathId`, `x`, `y`, `value`, `easing` |

Positions are percentages of a 1200×500 logical stage. Each coordinate is
0–100, with zero at the left/top. `size` is an absolute scale from 0.25 to 3;
rotation is degrees. Initial opacity and value are 0–1. Color is `ink`,
`accent`, `secondary` or `muted`. Labels are at most 32 characters; use `""`
for no label. Keep labels sparse and leave room around each object.

The available kinds are `planet`, `moon`, `spacecraft`, `lander`,
`lander-base`, `lander-ascent`, `rocket`, `satellite`, `person`, `packet`,
`server`, `laptop`, `cloud`, `coin`, `box`, `marker`, `gauge`, `counter` and
`workbench`.
The lander's base and ascent assets share an origin, so placing both at the
same position and scale initially forms a complete lander. Moving only the
ascent entity leaves the base behind. The gauge visual uses `value` as fill
and prints a percentage, so it needs a meaningful, stated denominator; it
must not turn a qualitative claim into an invented statistic.

Paths contain 2–24 points. The renderer samples curved paths once and uses
that same geometry to draw the route and move objects by distance along it.
If a later action starts away from a path's first point, it includes a
connecting segment instead of teleporting the object. Referenced paths
appear as their first action starts; unreferenced paths can serve as static
guides, such as an orbit. A scene permits up to 12 entities, 12 paths and 48
actions.

For authored `motion` scenes, the renderer computes one fixed camera for the entire scene, including curve
overshoot, orbit radii, the largest object scale and room for labels. Each
label's side is also chosen once for the whole scene, so it does not jump as
other objects pass. A scene that already fits keeps the authored framing. Larger trajectories are fitted
uniformly into the stage, which is clipped away from the title and subtitles.
This is a safety fit, not an automatic cinematic camera or a layout-quality
score; crowded staging can still need revision.

| Action kind | Target |
| --- | --- |
| `move` | Position `x`, `y` |
| `follow-path` | The path named by `pathId` |
| `orbit` | Rotate position around center `x`, `y` by `value` degrees; positive is clockwise on screen |
| `opacity` | `value` from 0 to 1 |
| `scale` | Absolute scale `value` from 0.25 to 3 |
| `rotate` | Absolute orientation `value` in degrees |
| `value` | A normalized value from 0 to 1, currently displayed by a gauge |

Easing is `linear`, `ease-in-out` or `ease-out`. Use `pathId: ""` except for
`follow-path`, and zero for unused numeric fields. Orbit geometry uses
physical stage coordinates so circles do not turn into ellipses because the
stage is wide.

## Timing and continuity

`startLine` and `endLine` are zero-based indices within this scene's narration.
An offset is a fraction of the corresponding spoken line's duration. An
action from line 1 at offset 0.2 to line 2 at offset 1 starts one fifth into
the second narration line and finishes at the end of the third line. It
includes the pause between them.

The plan contains no guessed seconds or frames. After real TTS, timeline
compilation appends absolute `from` and `durationInFrames` to each action:

```text
start = firstLine.from + round(startOffset * firstLine.durationInFrames)
end   = lastLine.from  + round(endOffset   * lastLine.durationInFrames)
durationInFrames = end - start
```

The final state holds after each action. The next action on that property
starts from the prior result. Actions are sorted by time, so authoring array
order and out-of-order rendering do not alter the output. Position and
opacity can change simultaneously; two position actions cannot overlap.
`move`, `follow-path` and `orbit` share the position channel. Adjacent actions
may meet at an endpoint. Invalid references, ranges, overlapping channels,
out-of-scene anchors and intervals that round to zero frames are rejected.

## Planner integration and verification boundary

The planner prefers process events for supported arrival/service workflows
and motion for other physical explanations. A video may use either template
throughout; two or three coherent scenes are preferred when they satisfy
narration limits. The output adapter keeps actor/station and entity/path
references intact while cleaning IDs. Chapter requests carry the preceding
scene's identities and ending state. Ordinary narration edits preserve visuals;
reported sync issues instead trigger bounded structural repair and a final
audit that cannot rewrite narration. Unresolved sync or medium/high accuracy
issues in that audit stop the run. See
[script review](SCRIPT_GUIDE.md#script-review). A small
template-selection request chooses one
to three visual families for each video. The detailed planning schema contains
only those families and their referenced definitions, and the system prompt
omits unselected template details. Process-only and motion-only requests have
no optional visual parts. A live API request rejected the earlier combined
nine-template grammar even though its optional/union field counts passed
local checks. Template selection is shared by CLI and web jobs, saved with the
run, and reused across chapters. The full local contract now supports ten
templates while retaining compatibility with earlier plans.

The Apollo and network sample plans were
authored and visually revised by a person/agent, then narrated by real
Kokoro and rendered by Remotion. They demonstrate reuse of the same engine,
not automatic planning quality. Live planning was subsequently exercised as
described below. Configure a Claude key in the ignored local `.env`, never in
chat or version control.

Further acceptance work must cover more unfamiliar topics and stronger
staging. The process run below adds one seven-minute illustrated example;
a long video rendered with the old slide templates alone is not evidence of
long-form motion storytelling quality.

Local validation on October 19, 2026 produced these final light-theme videos
with real Kokoro narration, music and subtitles. Both are 1920×1080 at 30 fps;
the same folders include 1280×720 sharing copies. Local run folders are ignored
by Git; the storyboards needed to reproduce them are checked-in fixtures.

| Final local run | Measured length | Full MP4 | Sharing MP4 | Main render time |
| --- | ---: | ---: | ---: | ---: |
| `runs/motion-apollo-v4` | 46.101 s | 5.93 MB | 1.32 MB | 45.5 s |
| `runs/motion-network-v2` | 47.168 s | 5.40 MB | 1.30 MB | 30.3 s |

Durations differ from their timelines by less than 0.002 seconds. Render
times exclude thumbnail/sharing encoding and are observations, not a
controlled performance benchmark. Key-frame and encoded-frame checks covered
arrival, landing, ascent, docking, packet ordering and reassembly. A night
theme still was checked too. Apollo's final motion timing was revised to
avoid an accidental overlap before the intended docking.

Current limits: this is a bounded 2D asset/action vocabulary, not unrestricted
scene creation or a physics simulator. Entities persist within one scene;
related process scenes share framing, but continuing state still needs explicit
authored initialization and review. Semantic quality
and factual correctness still require review. It does not reproduce every
camera, character or editing technique in the professor's reference video.

### Live planning check

On October 19, 2026, Claude Opus 5.5 planned a new topic: "Why does a queue
grow when people arrive faster than they can be served?" The input was a
55-second brief for curious adults and `fixtures/reference-queue.md`, a
qualitative facts file with no authored scenes, coordinates or actions.

- `runs/live-motion-queue-20261019-01`: the original combined schema was
  rejected by the provider before a generation response. No token usage was
  reported for that rejected request.
- `runs/live-motion-queue-20261019-02`: compact template selection and
  planning both passed without repair. The model wrote five motion scenes,
  14 lines and 141 words. Its unedited plan was narrated and rendered as a
  draft. Visual review found unsupported line-length percentages, completed
  people piled at one exit, crossing people and shipping boxes labeled as
  desks. This is a diagnostic example, not an accepted visual-quality result.
- `runs/live-motion-queue-20261019-03`: after improving general prompt rules,
  the same input produced two motion scenes, 12 lines and 139 words, again
  without a validation repair. The saved plan was not manually restaged.
  It uses labeled location markers instead of boxes, shows queue growth with
  people instead of percentages, fades completed people at an exit, and
  preserves the initial queue state across its scene boundary. Real local
  narration measures 52.625 seconds; the video timeline is 57.567 seconds
  including titles and pauses. The encoded H.264/AAC video measures 57.579
  seconds, 1920×1080 at 30 fps and 7.15 MB; its 720p sharing copy is 1.62 MB.
  The main render took 56.2 seconds, excluding thumbnail/sharing encoding.

The prompt changes cover fixed asset meanings, supported quantities, visible
before/after states, occupancy, exits, scene continuity and fewer unnecessary
cuts. They apply to other topics; there are no topic-name branches or queue
coordinates in the planner or renderer.

| Successful planning run | Input tokens | Output tokens | API time | Estimated cost |
| --- | ---: | ---: | ---: | ---: |
| First draft (`02`) | 7,841 | 14,141 | 118.0 s | $0.3142 |
| Revised prompts (`03`) | 8,745 | 12,801 | 111.3 s | $0.2910 |

Counts and time include each run's template-selection call. Total reported
usage is 16,586 input and 26,942 output tokens, estimated at $0.6052 using
the configured list price, before any credits. Billing remains authoritative
in the provider console. `llm-response.json` preserves the actual responses,
reported usage, model served, validation findings and request IDs.

This verifies the short CLI path from a real API plan to local narration and
rendering. It does not establish reliable staging for arbitrary prompts,
seven-minute motion continuity, or parity with the professor's reference.
API schema acceptance and local validation cannot judge visual teaching
quality; rendered-frame review is still necessary.

Encoded frames confirm queue growth, parallel service, a shorter queue and
removal of departed people. Remaining visible weaknesses include location
pins touching the heads of people at service positions, a short initial
parallel-service demonstration, and about thirteen seconds without object
actions at the end. The conditional case where arrivals match combined
service is spoken but not animated. This is a working end-to-end diagnostic
sample, not a finished reference-quality film. It motivates geometry-aware
staging, richer service/character assets and stronger action coverage.

### Semantic process validation

The next iteration uses `fixtures/reference-queue-expanded.md`, a factual
reference with no storyboard or coordinates. A real API request selects the
template and writes events; the compiler stages those events without changing
the saved plan.

`runs/live-process-queue-20261019-01` was a diagnostic 75-second brief. Its
71-second narration and key frames verified the basic process compiler, but
review found a misleading claim that extra capacity only helps when it clears
work faster than arrivals. General prompts and the factual reference were
clarified to distinguish helping from clearing a backlog. Actor labels were
also simplified and the shared staging enlarged.

`runs/live-process-queue-20261019-02` then generated two process scenes,
14 lines and 190 words without a validation repair. Its saved plan exactly
matches normalized conversion of the recorded API response. State review
confirmed two unfinished customers plus three arrivals minus one departure
leaves four; the next scene preserves those four actors and shows two
departures plus one arrival, leaving three. The plan was not manually restaged.

Real Kokoro speech measures 74.250 seconds. The full 1920×1080, 30 fps
H.264/AAC MP4 measures 79.403 seconds, versus a 79.400-second timeline;
it is 8.65 MB, with a 2.17 MB 720p copy. The main render took 76.0 seconds.
Every-frame diagnostics found zero body-collision pairs and no undeclared
static holds of at least four seconds. Encoded-frame inspection checked
counts, simultaneous service, final state, labels and captions. The final
recap still retains one arrangement with ongoing work for about 17.6 seconds;
passing motion diagnostics does not mean pacing is finished or reference-level.

The two process short planning runs used 17,392 input and 8,785 output tokens,
estimated at $0.2453 in total at configured list prices. Both preserve raw
provider responses, usage and request IDs in `llm-response.json`. The first
run is diagnostic evidence; the second is the rendered short validation.

The reviewed long source plan is preserved outside ignored run directories
as `fixtures/scene-plan.process-queue-long.json`. It contains the actual API
planned events plus recorded automatic narration edits, not a hand-restaged
example. To reproduce its narration and video without another planning call:

```bash
python -m capstone_script narrate --plan fixtures/scene-plan.process-queue-long.json --out runs/process-long-reproduction --offline
python -m capstone_script render --run runs/process-long-reproduction --share
```

### Seven-minute process run

`runs/live-process-queue-7min-20261019-01` used a 440-second brief and the
expanded factual reference. Claude selected process and definition templates,
then wrote six chapters and 14 scenes. The outline needed one repair for
overlong key-point strings; all six chapter plans passed on their first
attempt. The outline prompt now states the 120-character limit explicitly.
Reconstructing the saved plan from the recorded chapter responses produced
an exact match.

`runs/live-process-queue-7min-20261019-02` preserves that planning record and
applies the production API reviewer before final narration. Its 14 recorded
line edits clarify temporal references, distinguish extra work from physical
size, qualify the one-desk hypothetical, and distinguish an empty waiting
line from an empty system. The result exactly matches application of the
recorded review response. No visual event, actor, anchor or coordinate was
manually restaged. The final plan has 93 lines and 1,109 words; 79 unchanged
audio lines were reused from the draft, and the 14 edits were synthesized again.

| Final result | Measurement |
| --- | ---: |
| Real speech | 407.825 s |
| Timeline | 434.467 s |
| Encoded MP4 | 434.475 s (7 min 14 s) |
| Picture | 1920×1080, H.264, 30 fps |
| Decoded video frames | 13,034, exactly matching the timeline |
| Audio | AAC, 48 kHz, stereo mix |
| Full MP4 | 50.63 MB |
| 1280×720 sharing copy | 12.10 MB; duration verified against the full video |
| Main render | 454.0 s, excluding thumbnail and sharing encoding |

Thirteen process scenes use people, parcels or packets; a 27.5-second
definition scene explains waiting time versus total time in the system.
The equal-arrival/departure case actually performs one arrival and one
departure and leaves the unfinished count unchanged. State review confirmed
the parcel sequence 4→5→4→4, the capacity example 5→6→3, and the final system
emptying to zero. Every-frame diagnostics found no body-collision pairs and
no undeclared static holds of four seconds or more. Three deliberate result
or recap holds remain, the longest about 10.6 seconds.

Still samples covered all 14 scenes and six chapter cards. Eight frames
extracted from the final MP4 were checked across all chapters, including the
workbench correction, counts, labels and captions. Full-frame decoding
confirmed all 13,034 frames and the audio stream. This is not a claim of
full real-time listening review or parity with the professor's reference.
Some parcel colors change between continuing scenes, an early scenario reset
is not explicitly announced, and camera and character performance remain
simple. Semantic and visual review are still needed for new prompts.

Long planning used 61,668 input / 38,062 output tokens and cost an estimated
$1.0079; the automatic review used 18,121 / 8,599 and $0.2445. The copied
planning record in the final run is the same request history, not another
charge. Including both short trials, this iteration totals 97,181 input /
55,446 output tokens over 14 requests, estimated at **$1.4977** using configured
list prices. The provider's billing console remains authoritative.
`verification.json`, `encoded-probe.json`, `share-probe.json`,
`motion-inspection.json`, `review.json` and `llm-response.json` in the final
run retain the evidence.

## Checks

Each motion render writes `motion-inspection.json` before encoding. It scans
every frame for conservative body intersections and long static holds,
distinguishes explicitly planned process holds, and records suggested absolute
frames for visual review. Activity counts as motion, so a passed report does
not establish good pacing or prove that the narration's claim is demonstrated.
Review object labels, subtitles, continuity and causal meaning in the rendered
video as well. Intentional contact in raw motion scenes remains a warning.

```bash
python -m unittest discover -s tests
npm --prefix renderer run typecheck
npm --prefix renderer run test:motion
npm --prefix web test
npm --prefix web run build
```

Python tests cover both contracts, process lifecycle/occupancy, compact
planner conversion, review/chapters and real sample-count timing. Renderer tests cover seeking, action composition,
path geometry and orbits. Frontend tests also execute the narration-preview
HTML against a motion plan. Automated checks cannot judge whether the
animation teaches the idea; inspect the sample MP4s and their key frames.
The pre-process validation record passed 201 Python tests, 15 motion-engine
tests and 21 frontend tests, plus renderer type checking and the frontend
production build. These historical counts are not results for the newer
process implementation; rerun the commands above after changes.

The process iteration passed 231 Python tests, 36 renderer tests (engine,
diagnostics and process counts), and 22 frontend tests. Renderer type checking,
the frontend production build and whitespace validation passed too. The SVG
workbench intentionally contains no decorative parcel: all visible parcels
are declared actors, so the artwork cannot add an uncounted job.

The Apollo storyboard follows NASA's description of the separate descent
and ascent stages in [Apollo's Lunar Module Bridged Technological Leap to the
Moon](https://www.nasa.gov/history/apollos-lunar-module-bridged-technological-leap-to-the-moon/).
Its trajectories, scale and elapsed time are schematic. The packet example
illustrates possible differing routes and TCP reassembly, following
[Cloudflare's packet explanation](https://www.cloudflare.com/en-gb/learning/network-layer/what-is-a-packet/)
and [Internet protocol overview](https://www.cloudflare.com/en-gb/learning/network-layer/how-does-the-internet-work/).
Real messages need not contain exactly three packets or use different routes.
