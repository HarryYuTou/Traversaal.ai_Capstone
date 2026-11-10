# Custom objects and articulated actions

The motion planner can describe new 2D objects as bounded geometry, connected parts, and animation clips. The scene plan carries this data to the existing deterministic Remotion renderer. A new animal, plant, or mechanism does not require a new named entity kind or a topic-specific renderer component.

This extends the existing entity library. Use a built-in object when it already expresses the explanation well; use `kind: "custom"` when the object needs a new silhouette or separately moving parts. The planner produces data, not executable React, SVG markup, or a video. No image or video generation model is required by this contract.

## Authoring flow

1. Define the object's silhouette and break moving regions into parts.
2. Place each part's local origin at its joint. Attach it to another part with `parentId` where appropriate.
3. Define clips containing local transform tracks, with anticipation, the main action, and a settling pose where the explanation calls for them.
4. Schedule clips with narration-relative `performances`.
5. Add explicit `contacts` where a foot, perch, support, or grasp point must stay aligned to another object.
6. Validate the plan and compile the anchors against the narration's measured durations.
7. Inspect rendered poses, framing, and motion. Structural validity alone does not establish convincing acting or physically appropriate contact.

An object's geometry is created once and reused across frames. Clip poses are calculated from absolute timeline frames, so seeking or rendering frames out of order does not create a different character or restart an animation.

The normal planner requests structured JSON. If the model service explicitly rejects the compiled schema as too large, it retries once with the same schema supplied as a JSON authoring contract, using medium reasoning effort to leave room for complete geometry output. The complete local structural and semantic validators still apply, with at most one content repair. Other API errors do not trigger this fallback. Run records identify `json-schema` versus `validated-json` output, the actual effort and the grammar-limit event.

Normal rendering automatically runs a spatial preflight for motion scenes containing a custom entity or authored contacts, and related shots sharing their camera. It checks the actual `video/props.json`, including the selected illustration look, before encoding the MP4. The run's `spatial-inspection.json` must report `spatial-checks-passed`; an unfinished or failing check stops rendering. Successful `video-info.json` records its path and status under `spatialInspection`. The scorecard reports this status and blocks automatic success when explicit spatial evidence fails, while ordinary motion overlap/hold warnings retain their existing review-only policy. Unrelated legacy scene groups remain advisory, including intentional arrivals/departures outside a process close-up. Reports identify enforced groups and advisory findings explicitly. These numerical checks do not replace visual review or establish animation quality by themselves.

## Scene contract

A `motion` visual keeps its existing `title`, `entities`, `paths`, and `actions`, and can add `rigs`, `performances`, and `contacts`.

| Field | Meaning |
| --- | --- |
| `entities[].kind` | Use `"custom"` for a generated articulated object. |
| `entities[].rigId` | ID of a rig in this scene. Only custom entities use this field. |
| `rigs[]` | Objects with `id`, `parts`, and `clips`. A rig can be shared by multiple entities in a scene. |
| `performances[]` | Scheduled instances of clips on a custom entity. |
| `contacts[]` | Translation constraints aligning one entity's local anchor to another entity's anchor. |

The entity still supplies `id`, `x`, `y`, `size`, `rotation`, `opacity`, `value`, `color`, and `label`. Entity positions use the existing scene coordinate system. Rig coordinates are SVG-local illustration units, scaled by the entity's `size`; they are not percentages of the scene. Ordinary entity actions can move the whole object while a performance animates its internal parts.

Rig definitions are local to the scene. Repeated custom entities keep their kind and `rigId`; a repeated rig ID must preserve its ordered parts, parent links, and shape geometry. Its base transforms and clips may change to express the next shot. A completed pose is held within its scene. For a later scene, author its initial local pose explicitly; there is no hidden mutable pose state carried between scenes.

### Parts and shapes

Every part has these fields:

```json
{
  "id": "hinged-arm",
  "parentId": "body",
  "x": 20,
  "y": 0,
  "rotation": 0,
  "scaleX": 1,
  "scaleY": 1,
  "opacity": 1,
  "shapes": [
    {
      "kind": "rect",
      "x": -4,
      "y": 0,
      "width": 8,
      "height": 30,
      "radius": 3,
      "path": "",
      "fill": "accent",
      "stroke": "ink",
      "strokeWidth": 2
    }
  ]
}
```

Use `parentId: ""` for a root part. A part may have no shapes and act only as a joint. Parent references must exist, must not form cycles, and may form chains of at most eight parts. A part's transform is `translate(x, y) rotate(rotation) scale(scaleX, scaleY)`, nested inside its parent's transform. Angles are degrees. Rotations occur around the local origin; draw the part relative to that origin rather than treating its center as an implicit joint.

Shapes are drawn in their array order. Parts are drawn as a hierarchy, with each parent's geometry before its children; sibling/root ordering follows the parts array. Design the hierarchy and sibling order deliberately for front/back layering.

All shape fields shown above are required. The three allowed kinds are:

- `ellipse`: `x` and `y` are its center; `width` and `height` are full diameters. Set `radius` to `0` and `path` to `""`.
- `rect`: `x` and `y` are its top-left corner. `radius` is the corner radius, no larger than half the shorter side. Set `path` to `""`.
- `path`: use absolute `M`, `L`, `Q`, `C`, and `Z` commands only, with an explicit command for each coordinate group. Set `x`, `y`, `width`, `height`, and `radius` to `0`. For example, `M 0 0 Q 12 -18 24 0 L 0 0 Z`.

Fill and stroke accept `ink`, `accent`, `secondary`, `muted`, `paper`, `soft`, `line`, `none`, or a six-digit hexadecimal color such as `#DA7E49`. Palette colors adapt to the theme. Custom vector geometry remains the same when the scene's existing `look` changes; this feature does not automatically convert it into a new hand-drawn asset.

### Clips and keyframes

A clip has an `id` and `tracks`. Each track names one `partId`, one property, and ordered keyframes:

```json
{
  "id": "raise-arm",
  "tracks": [
    {
      "partId": "hinged-arm",
      "property": "rotation",
      "keyframes": [
        {"at": 0, "value": 0, "easing": "linear"},
        {"at": 0.2, "value": 8, "easing": "ease-in-out"},
        {"at": 0.8, "value": -65, "easing": "ease-in-out"},
        {"at": 1, "value": -60, "easing": "ease-out"}
      ]
    }
  ]
}
```

Allowed properties are `x`, `y`, `rotation`, `scaleX`, `scaleY`, and `opacity`. Translation, rotation, and opacity values are offsets; the first value must be `0`. Scale values are multipliers; the first value must be `1`. A clip starts from the pose held by previous completed clips on the same property, so a second clip is relative to that held pose rather than to the original rest pose. Final values persist after the performance ends. Accumulated opacity must stay within `0…1`; invalid excursions are rejected so the next clip starts from the actual visible state.

Every track begins at `at: 0`, ends at `at: 1`, and has strictly increasing times. For `linear`, `ease-in-out`, and `ease-out`, the destination keyframe chooses the easing for the segment leading into it; the first key's easing has no preceding segment to affect. These existing curves retain their behavior. The additional `smooth` option applies to a complete track and must appear on every key in that track; it cannot be mixed with the three segment curves. A clip cannot contain duplicate tracks for one part/property.

### Performances

```json
{
  "entityId": "robot",
  "clipId": "raise-arm",
  "startLine": 0,
  "endLine": 1,
  "startOffset": 0.2,
  "endOffset": 0.8,
  "repeat": 1
}
```

Line indices are zero-based. Offsets are fractions of the corresponding narration line's duration. The compiler adds absolute `from` and `durationInFrames` fields after narration timing is known; do not author these fields in a scene plan. The end must be after the start and must remain valid after frame rounding.

`repeat` divides the scheduled interval into that many equal cycles. Repeated clips must end at the same neutral values with which they began on every track; this prevents a jump at the loop boundary. Each repeated cycle must have at least four frames so frame sampling does not erase the movement. Performances may overlap only when they affect different part/property channels. Parent and child motion can still combine visually, so inspect the resulting motion even when channels do not conflict.

### Contacts and release

A contact identifies a point on the source object and a point on a separate target object. After a smooth acquisition interval, the renderer translates the entire source entity so these points coincide. The source follows target movement and target-part articulation while the contact is active. The solver uses the same hierarchy and transforms as the drawn geometry; it does not estimate contact from labels or silhouettes.

For example, a separate sample can attach to a gripper's authored grip point:

```json
{
  "entityId": "sample",
  "partId": "body",
  "x": 0,
  "y": 0,
  "targetId": "gripper",
  "targetPartId": "grip-point",
  "targetX": 0,
  "targetY": 0,
  "startLine": 0,
  "endLine": 2,
  "startOffset": 0.5,
  "endOffset": 1,
  "approach": 0.2
}
```

Both entities and the named parts must exist in the scene. Use `partId: ""` or `targetPartId: ""` for the corresponding entity origin; nonempty part IDs must identify parts in that entity's custom rig. Each `x/y` pair is a point in that root or part's **local illustration units**, within `-256…256`, before the entity's size and rotation are applied. They are not stage percentages. Place the anchor on the actual drawn foot, surface, or grip. A stock object supports a root anchor with a local offset, but has no named rig parts.

Design the visible surfaces before assigning contact coordinates. The physical stage is `1200 × 500`, so an authored entity position becomes `(12*x, 5*y)` before adding its transformed local anchor. An already-supported object should not slide, sink or lift merely because a grasp acquires: bring the carrier to its existing visible position. Include shape strokes, relative scale and the full part hierarchy when comparing the two sides. Planner/reviewer guidance explicitly checks this calculation and recommends co-designed custom surfaces for contact-critical close views. Stock illustration bounds are not automatically flat contact faces, and stock geometry can vary with the illustration look.

`approach` is the fraction of the scheduled contact interval used to acquire the lock, from `0` to `0.5`. The example uses its first 20% for acquisition and the remaining 80% for exact anchor alignment. A positive approach must compile to at least two acquisition frames and leave a locked interval. The compiler adds `from`, `durationInFrames`, and `approachFrames`; the model does not author frame fields.

For an object already supported when a scene starts, use `startLine: 0`, `startOffset: 0`, and `approach: 0`. This special case starts at the scene's first frame, including the silent lead before narration, so the setup does not show a floating object. Zero approach is invalid for later contacts. Positive approaches start at their normal narration-relative anchor.

Only one contact may control a source entity at a time, even if two proposed contacts name different source parts. Contact intervals may touch at an endpoint. The complete source-to-target graph in a scene must be acyclic, including relationships scheduled at different times; self-contact and reciprocal attachment are rejected. A source's `move`, `follow-path`, or `orbit` action cannot overlap its contact. Move the target while carrying the source, or release the source before free travel. Rotation, scale, and rig clips may continue during contact: translation compensates to keep the chosen anchor aligned.

At release, the solved translation offset remains in place. Subsequent free actions still use the source's **unconstrained coordinate system**, and the renderer adds the retained offset to that trajectory. Do not pre-add that offset to authored move targets or path points. For example, if contact leaves the source 30 stage units to the right of its unconstrained position, a later free trajectory also remains 30 stage units to the right. The compiler preserves the authored coordinates rather than rewriting them into solved positions. As with poses, a new scene must explicitly establish its initial visible state and support relationship.

This is a translation-only constraint. It does not inherit target rotation or release velocity, simulate momentum or gravity, bend a limb to reach a target, solve simultaneous support at multiple feet, or determine when a grip should occur. A moving target can leave the source with a velocity change at release even when its position is continuous; author the later action accordingly. The contact describes a relationship chosen by the author or planner, not an inferred collision or grasp.

Visual repair preserves each existing contact's source entity/part and target entity/part. It may correct anchor coordinates or timing, but cannot remove a physical relationship to hide a bad contact. Custom geometry and hierarchy retain their existing identity protections.

### Bounds and framing

The contract allows up to 6 rigs, 48 performances, and 24 contacts per scene; 32 parts and 12 clips per rig; 8 shapes per part; 32 tracks per clip; and 16 keyframes per track. IDs are lowercase letters/numbers separated by hyphens, up to 48 characters. Older plans may omit `contacts`; omission preserves their serialized plan hashes.

Local coordinates and translation offsets are within `-256…256`; dimensions are within `0…512`; stroke widths are within `0…12`; base scales and animation scale multipliers are within `0.1…4`. Base rotation is within `-3600…3600` degrees and animated rotation offsets within `-720…720`. Base opacity is within `0…1` and opacity offsets within `-1…1`. Paths have at most 2,048 characters and 128 commands. Use compact geometry around the local origin, with part scales near one, to keep camera framing useful. The assembled rig's conservative motion envelope must remain within 800 local units on each axis; deeply nested scaling can exceed that limit even when individual values are valid.

For framing, the renderer computes tighter angular envelopes from the extrema of the actual authored rotation intervals, including turning points between frames. A small joint rotation therefore need not reserve the space of a complete circular sweep. It also retains each custom rig's asymmetric left, right, top, and bottom bounds through outer rotation and scale, so an offset arm does not reserve an imaginary mirrored arm; labels and spatial containment use the same directional envelope. The original conservative 800-unit safety limit remains in place. Camera fitting also includes solved contact positions and released trajectories. One viewport stays fixed for the entire scene and is shared across related continuing shots, avoiding per-frame reframing as a limb moves.

The planner is guided to use larger, readable principal objects and place the interaction where the viewer can see it. For one or two subjects around 100 local units tall, an entity size around `1.5…2.5` is a useful starting point, adjusted for the complete mechanism and its motion. Leave room for the whole movement and keep captions and labels away from the support or grip. These are composition guidelines, not a guarantee that a generated plan has good framing.

No scripts, raw markup, external URLs, image loading, filters, arbitrary SVG attributes, arbitrary code, or dynamic parenting are part of this contract.

### Smooth articulated performances

After support and framing are established, `smooth` can make a deliberate multi-key gesture flow through its intermediate poses. It uses shape-preserving cubic Hermite interpolation (PCHIP): adjacent key values bound the interpolated result, so interpolation does not invent overshoot. Monotonic interior keys can retain nonzero velocity; a local reversal or flat interval brings that property's tangent to zero. This preserves existing key-value bounds and avoids the stop at every key produced by repeatedly easing individual segments in and out.

```json
{
  "partId": "hinged-arm",
  "property": "rotation",
  "keyframes": [
    {"at": 0, "value": 0, "easing": "smooth"},
    {"at": 0.25, "value": -12, "easing": "smooth"},
    {"at": 0.65, "value": -42, "easing": "smooth"},
    {"at": 1, "value": -60, "easing": "smooth"}
  ]
}
```

This example still requires an authored clip and scheduled performance. Its values remain offsets from the held pose. A nonrepeating smooth performance begins and ends with zero velocity for that local property, and holds its final pose. A repeated smooth performance uses a periodic tangent at its matching start/end keys, allowing velocity to agree across internal cycle seams. This does not automatically ease the whole repeated performance in or out, inherit entity movement, or generate anticipation and follow-through. Choose a suitable loop seam and explicitly author preparation and settling clips around the loop when the action needs them; leave time to read the final held result. Four frames per cycle remains only the validation minimum, not a recommended cadence.

The planner's choreography guidance asks for a meaningful preparation, main change, and settling or readable result when the subject calls for them. Primary motion should cause smaller secondary motion, with deliberately delayed tracks rather than all parts moving in phase. A weight shift can retain an explicit planted contact. Large, recognizable shapes and visible contact points matter as much as the interpolation curve. Keep supported geometry and spatial continuity intact while refining the gesture.

The model still chooses the geometry, keys, offsets, and timings. `smooth` is not an automatic action generator or a physics solver, and it is not required for constant-rate mechanisms or intentional holds. The script reviewer checks concrete mismatches between geometry, contact targets, narrated action, and timing; quiet machinery, passive orbits, deliberate rest, and held explanations are not failures simply because they lack extra acting. Release retains position but not inherited velocity, so a carrier may need to settle before release, followed by a deliberately authored launch. A continuing shot must explicitly retain the previous solved root position or continue the same contact, in addition to keeping the object's shape and part pose consistent.

## Acceptance fixture and preview

[`fixtures/scene-plan.custom-rigs.json`](../fixtures/scene-plan.custom-rigs.json) is a **hand-authored acceptance fixture**, not evidence that a live model generated these examples. It exercises three objects that have no dedicated runtime presets:

- A fox with a body, hinged legs, separate paws, head, tail, and tail tip. The clip demonstrates a crouch, hop, and settling motion.
- A flower whose petals open independently and retain their open pose before a two-cycle sway. The sway has matching endpoints.
- A gripper whose jaws close before its carriage lifts. The sample is a persistent child of the carriage from the start. Its motion demonstrates authored attachment, not inferred collision, grasping, or transfer between parents. Check that the jaws remain closed and the sample never teleports away from them.

From `renderer`, generate a silent preview and inspection frames:

```sh
node scripts/custom-rig-preview.mjs ../runs/custom-rig-preview vector
```

Use a new destination directory for each run. Append `--timeline-only` to inspect the compiled timeline without launching a render. The script validates the scene plan and calls the production timeline compiler with synthetic three-second narration lines. It records that provenance alongside the output. Set `CAPSTONE_PYTHON` if the repository virtual environment is unavailable. The preview makes no planner, TTS, image-generation, or video-generation API calls.

The separate [`fixtures/scene-plan.spatial-quality.json`](../fixtures/scene-plan.spatial-quality.json) fixture exercises contact/framing together with articulated performance:

- A presenter's foot stays on a separate platform during a small articulated shift.
- A gripper acquires a separate sample, closes its jaws, and lifts the sample through the declared contact.
- A butterfly remains perched on a leaf and then releases into a free trajectory while retaining a nonzero solved offset.

From `renderer`, render that fixture and run the numerical spatial inspection:

```sh
node scripts/spatial-quality-preview.mjs ../runs/contact-preview vector
node scripts/inspect-spatial.mjs ../runs/contact-preview/timeline.json ../runs/contact-preview/spatial-report.json
```

Use a fresh output directory; `sketch` and `--timeline-only` are also supported by the preview command. This fixture is hand-authored and uses synthetic narration timing. The generated inspection frames cover initial support, acquisition, lock, release, and later travel. The spatial report checks anchor alignment, position continuity near contact boundaries, actor containment, and shared cameras across related shots. It does not test velocity continuity, pixel-level appearance, occlusion, labels, or whether the author selected physically meaningful anchors. A passing numerical report still needs rendered-frame and motion review; it does not by itself establish the stage acceptance gate or justify proceeding to further acting changes.

## Prompt examples and limits

Example requests for the normal planner:

- “Explain how a flower opens in a short 2D animation. Give the petals separate hinges, open them with a slight stagger, and keep them open afterward.”
- “Show a small fox preparing for one short hop, landing, and letting its tail settle. Keep the same character throughout.”
- “Explain a parallel gripper: first close both jaws around a sample on a pedestal, then lift the held assembly. Keep contact visible.”

These are prompts for new descriptions, not hard-coded topic selectors. Live planning quality must be evaluated separately from the authored fixture. Valid output can still need changes to proportions, silhouette, timing, overlap, or contact.

The implementation is a generic 2D articulation system with explicitly authored single-anchor translation contacts. It does not add inverse kinematics, collision detection, physical simulation, inferred contact events, inherited inertia, a multi-foot solver, perspective reconstruction, unrestricted 3D turning, or a guarantee of professional animation for any prompt. Permanent assemblies can share a parent; separate objects can use scheduled contacts for support and release. Complex grasp/release handoffs or walking still require carefully authored anchors, poses, and timing, and may need a simpler action when one translation constraint cannot represent the interaction.
