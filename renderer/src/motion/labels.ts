import {entityAtFrame, toStage, type EntityState, type MotionProgram, type PreparedEntity} from './engine';
import {BASE_VIEWPORT, type StageViewport} from './camera';
import {entityHalfExtents, labelMetrics} from './metrics';
import {rotatedRigExtents, transformedRigBounds} from './rig';

export type Actor = {prepared: PreparedEntity; state: EntityState};
type Box = {left: number; top: number; right: number; bottom: number};
type LabelLayout = {fontSize: number; width: number; height: number; halfWidth: number; halfHeight: number; bounds?: Box};
/** Side and reserved geometry stay fixed throughout every related shot: 0 below, 1 above, 2 right, 3 left. */
export type LabelSlots = Map<string, number> & {layouts?: Map<string, LabelLayout>; look?: 'vector' | 'sketch'};
/** Process stations read best labelled beside them: walkers pass above and below, the queue is on the left. */
export const PROCESS_LABEL_ORDER = [2, 0, 1, 3];
export type Shot = {program: MotionProgram; frames: number[]};
export type LabelPlanOptions = {viewport?: StageViewport; fontScale?: number; look?: 'vector' | 'sketch'};

/** Every `step`-th frame of a scene, including its final visible frame, never the next scene's frame. */
export const sceneFrames = (from: number, durationInFrames: number, step = 2) => {
  const duration = Math.max(0, Math.floor(durationInFrames));
  if (!duration) return [];
  const stride = Math.max(1, Math.floor(step));
  const frames = Array.from({length: Math.ceil(duration / stride)}, (_, index) => from + index * stride);
  const last = from + duration - 1;
  if (frames.at(-1) !== last) frames.push(last);
  return frames;
};
type Body = {point: {x: number; y: number}; radius: number | null; box: Box; localBounds?: Box};
const intersects = (a: Box, b: Box) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
const SLOTS = [0, 1, 2, 3];
const EDGE = 12;

const bodiesOf = (actors: Actor[], look: 'vector' | 'sketch' = 'vector'): Body[] => actors.map(({prepared, state}) => {
  const point = toStage(state);
  if (prepared.entity.kind === 'custom' && prepared.rig) {
    const box = transformedRigBounds(prepared.rig.bounds, [state.size, state.size], [state.rotation, state.rotation]);
    return {point, radius: null, localBounds: box, box: {left: point.x + box.left, right: point.x + box.right,
      top: point.y + box.top, bottom: point.y + box.bottom}};
  }
  const {x: rx, y: ry} = entityHalfExtents(prepared.entity.kind, state.size, state.rotation, look, prepared.rigExtents);
  return {point, radius: ['moon', 'planet'].includes(prepared.entity.kind) ? Math.max(rx, ry) : null,
    box: {left: point.x - rx, right: point.x + rx, top: point.y - ry, bottom: point.y + ry}};
});

const fittedMetrics = (label: string, viewport: StageViewport, fontScale = 1) => {
  const metrics = labelMetrics(label, fontScale);
  // A narrow export or long label cannot produce an inverted clamping interval. This reduction is
  // planned once, so text never changes size as its actor moves toward an edge.
  const available = Math.max(1, viewport.width - EDGE * 2);
  if (metrics.width <= available) return metrics;
  const ratio = Math.max(0.001, (available - 14) / (metrics.width - 14));
  const fontSize = metrics.fontSize * ratio;
  return {fontSize, width: available, height: fontSize + 10};
};

const candidateFor = (body: Body, metrics: Pick<LabelLayout, 'fontSize' | 'width' | 'height'>,
  slot: number, viewport: StageViewport, layout?: LabelLayout) => {
  const {point} = body;
  const {fontSize, width} = metrics;
  const halfWidth = layout?.halfWidth ?? (body.box.right - body.box.left) / 2;
  const halfHeight = layout?.halfHeight ?? (body.box.bottom - body.box.top) / 2;
  const bounds = layout?.bounds ?? (!layout ? body.localBounds : undefined)
    ?? {left: -halfWidth, right: halfWidth, top: -halfHeight, bottom: halfHeight};
  const position = [
    {x: point.x, y: point.y + bounds.bottom + fontSize + 12},
    {x: point.x, y: point.y + bounds.top - 16},
    {x: point.x + bounds.right + width / 2 + 16, y: point.y + fontSize / 3},
    {x: point.x + bounds.left - width / 2 - 16, y: point.y + fontSize / 3},
  ][slot];
  const clamp = (value: number, min: number, max: number) => max < min ? (min + max) / 2 : Math.max(min, Math.min(max, value));
  const x = clamp(position.x, viewport.x + width / 2 + EDGE, viewport.x + viewport.width - width / 2 - EDGE);
  // Include the text outline and descenders in both the planner and the renderer's bounds.
  const y = clamp(position.y, viewport.y + fontSize + 4 + EDGE, viewport.y + viewport.height - 10 - EDGE);
  return {x, y, bounds: {left: x - width / 2, right: x + width / 2, top: y - fontSize - 4, bottom: y + 10},
    displacement: Math.hypot(x - position.x, y - position.y)};
};

const bodyHits = (box: Box, bodies: Body[]) => bodies.filter((other) => {
  if (other.radius === null) return intersects(box, other.box);
  const nearestX = Math.max(box.left, Math.min(box.right, other.point.x));
  const nearestY = Math.max(box.top, Math.min(box.bottom, other.point.y));
  return Math.hypot(other.point.x - nearestX, other.point.y - nearestY) < other.radius + 6;
}).length;

/** Labels follow translation, but a planned anchor never bobs with the body's rotation or scale.
 * Layout is stateless: rendering out of order produces exactly the same label positions. */
export const placeActorLabels = (actors: Actor[], viewport: StageViewport = BASE_VIEWPORT, slots?: LabelSlots) => {
  const visible = actors.filter(({state}) => state.opacity > 0.05);
  const bodies = bodiesOf(visible, slots?.look);
  const placed: Box[] = [];
  return visible.flatMap((actor, index) => {
    const {entity} = actor.prepared;
    if (!entity.label) return [];
    const layout = slots?.layouts?.get(entity.id);
    const metrics = layout ?? fittedMetrics(entity.label, viewport);
    const planned = slots?.get(entity.id);
    const candidates = SLOTS.filter((slot) => planned === undefined || slot === planned).map((preference) => {
      const candidate = candidateFor(bodies[index], metrics, preference, viewport, layout);
      return {...candidate, score: bodyHits(candidate.bounds, bodies) * 1000
        + placed.filter((other) => intersects(candidate.bounds, other)).length * 1500 + preference};
    });
    const best = candidates.sort((a, b) => a.score - b.score)[0];
    placed.push(best.bounds);
    return [{actor, x: best.x, y: best.y, fontSize: metrics.fontSize, bounds: best.bounds}];
  });
};

/**
 * Choose a single side and geometry envelope for each identity across all related shots. Planning
 * uses the same viewport-clamped boxes as rendering, so an apparently free side beyond the frame
 * cannot win and then be clamped back over the actor. Text and body envelopes include every shot,
 * including a changed label or a larger/rotated version of the same entity.
 */
export const planLabelSlots = (shots: Shot[], order: number[] = SLOTS, options: LabelPlanOptions = {}): LabelSlots => {
  const viewport = options.viewport ?? BASE_VIEWPORT;
  const look = options.look ?? 'vector';
  const slots: LabelSlots = new Map();
  slots.look = look;
  slots.layouts = new Map();
  const samples = shots.flatMap(({program, frames}) => frames.map((frame) => {
    const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}))
      .filter(({state}) => state.opacity > 0.05);
    return {actors, bodies: bodiesOf(actors, look), placed: [] as Box[]};
  }));
  const identities = new Map<string, PreparedEntity[]>();
  for (const {program} of shots) for (const prepared of program.entities) {
    if (prepared.entity.label) identities.set(prepared.entity.id, [...(identities.get(prepared.entity.id) ?? []), prepared]);
  }
  // Serialized entity order is not a layout instruction. Consistent identity order keeps equivalent
  // scenes stable when a generator changes the order of their entity arrays.
  for (const [id, instances] of [...identities].sort(([a], [b]) => a.localeCompare(b))) {
    const metrics = instances.map(({entity}) => fittedMetrics(entity.label, viewport, options.fontScale));
    const fontSize = Math.min(...metrics.map((metric) => metric.fontSize));
    const width = Math.min(Math.max(1, viewport.width - EDGE * 2),
      Math.max(...instances.map(({entity}) => entity.label.length * fontSize + 14)));
    const height = fontSize + 10;
    let halfWidth = 0;
    let halfHeight = 0;
    let bounds: Box | undefined;
    for (const {entity, actions, rigExtents, rig} of instances) {
      const size = Math.max(entity.size, ...actions.filter(({action}) => action.kind === 'scale').map(({action}) => action.value));
      let extents = entityHalfExtents(entity.kind, size, entity.rotation, look, rigExtents);
      if (actions.some(({action}) => action.kind === 'rotate') && !['moon', 'planet'].includes(entity.kind)) {
        if (entity.kind === 'custom' && rigExtents) {
          const rotations = [entity.rotation, ...actions.filter(({action}) => action.kind === 'rotate').map(({action}) => action.value)];
          const rotated = rotatedRigExtents(rigExtents, [Math.min(...rotations), Math.max(...rotations)]);
          extents = {x: (rotated.x + 3) * size, y: (rotated.y + 3) * size};
        } else {
          const unrotated = entityHalfExtents(entity.kind, size, 0, look, rigExtents);
          const radius = Math.hypot(unrotated.x, unrotated.y);
          extents = {x: radius, y: radius};
        }
      }
      halfWidth = Math.max(halfWidth, extents.x);
      halfHeight = Math.max(halfHeight, extents.y);
      if (entity.kind === 'custom' && rig) {
        const sizes = [entity.size, ...actions.filter(({action}) => action.kind === 'scale').map(({action}) => action.value)];
        const rotations = [entity.rotation, ...actions.filter(({action}) => action.kind === 'rotate').map(({action}) => action.value)];
        const box = transformedRigBounds(rig.bounds, [Math.min(...sizes), size], [Math.min(...rotations), Math.max(...rotations)]);
        bounds = bounds ? {left: Math.min(bounds.left, box.left), right: Math.max(bounds.right, box.right),
          top: Math.min(bounds.top, box.top), bottom: Math.max(bounds.bottom, box.bottom)} : box;
      }
    }
    const layout = {fontSize, width, height, halfWidth, halfHeight,
      ...(bounds && instances.every(({entity}) => entity.kind === 'custom') ? {bounds} : {})};
    slots.layouts.set(id, layout);
    const validOrder = [...new Set(order.filter((slot) => SLOTS.includes(slot)))];
    if (!validOrder.length) validOrder.push(...SLOTS);
    const scored = validOrder.map((slot, preference) => {
      const candidates = samples.map(({actors, bodies}) => {
        const index = actors.findIndex((actor) => actor.prepared.entity.id === id);
        return index < 0 ? null : candidateFor(bodies[index], layout, slot, viewport, layout);
      });
      const score = candidates.reduce((sum, candidate, sample) => candidate ? sum
        + bodyHits(candidate.bounds, samples[sample].bodies) * 1000
        + samples[sample].placed.filter((other) => intersects(candidate.bounds, other)).length * 1500
        // Prefer an unclamped anchor when collision counts tie, without outweighing one collision.
        + Math.min(1, candidate.displacement / Math.max(1, viewport.width, viewport.height)) / Math.max(1, samples.length)
        : sum, 0) + preference / 100;
      return {slot, candidates, score};
    }).sort((a, b) => a.score - b.score)[0];
    slots.set(id, scored.slot);
    scored.candidates.forEach((candidate, sample) => {if (candidate) samples[sample].placed.push(candidate.bounds);});
  }
  return slots;
};
