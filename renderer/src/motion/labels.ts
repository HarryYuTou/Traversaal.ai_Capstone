import {entityAtFrame, toStage, type EntityState, type MotionProgram, type PreparedEntity} from './engine';
import {BASE_VIEWPORT, type StageViewport} from './camera';
import {entityHalfExtents, labelMetrics} from './metrics';

export type Actor = {prepared: PreparedEntity; state: EntityState};
/** The side each labelled entity keeps for a whole scene: 0 below, 1 above, 2 right, 3 left. */
export type LabelSlots = Map<string, number>;
/** Process stations read best labelled beside them: walkers pass above and below, the queue is on the left. */
export const PROCESS_LABEL_ORDER = [2, 0, 1, 3];
export type Shot = {program: MotionProgram; frames: number[]};

/** Every `step`-th frame of a scene, including its last. */
export const sceneFrames = (from: number, durationInFrames: number, step = 2) => Array.from(
  {length: Math.ceil(durationInFrames / step) + 1}, (_, index) => from + Math.min(durationInFrames, index * step));
type Box = {left: number; top: number; right: number; bottom: number};
type Body = {point: {x: number; y: number}; radius: number | null; box: Box};
const intersects = (a: Box, b: Box) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
const SLOTS = [0, 1, 2, 3];

const bodiesOf = (actors: Actor[]): Body[] => actors.map(({prepared, state}) => {
  const point = toStage(state);
  const {x: rx, y: ry} = entityHalfExtents(prepared.entity.kind, state.size, state.rotation);
  return {point, radius: ['moon', 'planet'].includes(prepared.entity.kind) ? 68 * state.size : null,
    box: {left: point.x - rx, right: point.x + rx, top: point.y - ry, bottom: point.y + ry}};
});

const slotPosition = ({point, box: body}: Body, fontSize: number, width: number, slot: number) => [
  {x: point.x, y: body.bottom + 27}, {x: point.x, y: body.top - 17},
  {x: body.right + width / 2 + 16, y: point.y + fontSize / 3},
  {x: body.left - width / 2 - 16, y: point.y + fontSize / 3},
][slot];

const bodyHits = (box: Box, bodies: Body[]) => bodies.filter((other) => {
  if (other.radius === null) return intersects(box, other.box);
  const nearestX = Math.max(box.left, Math.min(box.right, other.point.x));
  const nearestY = Math.max(box.top, Math.min(box.bottom, other.point.y));
  return Math.hypot(other.point.x - nearestX, other.point.y - nearestY) < other.radius + 6;
}).length;

/**
 * Keep labels outside illustrated bodies, particularly a lander approaching the Moon's surface.
 * With `slots` (from planLabelSlots) each label stays on its planned side; without, the clearest
 * side is chosen for this frame alone.
 */
export const placeActorLabels = (actors: Actor[], viewport: StageViewport = BASE_VIEWPORT, slots?: LabelSlots) => {
  const visible = actors.filter(({state}) => state.opacity > 0.05);
  const bodies = bodiesOf(visible);
  const placed: Box[] = [];
  return visible.flatMap((actor, index) => {
    const {entity} = actor.prepared;
    if (!entity.label) return [];
    const {fontSize, width, height} = labelMetrics(entity.label);
    const planned = slots?.get(entity.id);
    // A planned side sits as close to its entity as the rendered text allows; the conservative width
    // still keeps it inside the frame. A per-frame choice keeps the original margins.
    const offsetWidth = planned === undefined ? width : textWidth(entity.label, fontSize);
    const others = planned === undefined ? bodies : bodies.filter((_, other) => other !== index);
    const candidates = SLOTS.filter((slot) => planned === undefined || slot === planned).map((preference) => {
      const position = slotPosition(bodies[index], fontSize, offsetWidth, preference);
      const x = Math.max(viewport.x + width / 2 + 12, Math.min(viewport.x + viewport.width - width / 2 - 12, position.x));
      const y = Math.max(viewport.y + height + 8, Math.min(viewport.y + viewport.height - 10, position.y));
      const box = {left: x - width / 2, right: x + width / 2, top: y - fontSize, bottom: y + 6};
      return {x, y, box, score: bodyHits(box, others) * 1000
        + placed.filter((other) => intersects(box, other)).length * 1500 + preference};
    });
    const best = candidates.sort((a, b) => a.score - b.score)[0];
    placed.push(best.box);
    return [{actor, x: best.x, y: best.y, fontSize}];
  });
};

// Rendered label text averages about 0.6 em per character. Fitting keeps labelMetrics' conservative
// width; the side choice uses this closer one so a near miss is not counted as a collision.
const textWidth = (label: string, fontSize: number) => label.length * fontSize * 0.6 + 14;

/**
 * Choose each label's side once for the whole scene, or for every related shot of one stage: the side
 * that touches the fewest bodies and earlier labels over all the sampled frames, ties going to the
 * earlier side in `order`. Labels then never jump sides when someone walks past or a shot changes.
 */
export const planLabelSlots = (shots: Shot[], order: number[] = SLOTS): LabelSlots => {
  const slots: LabelSlots = new Map();
  const samples = shots.flatMap(({program, frames}) => frames.map((frame) => {
    const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}))
      .filter(({state}) => state.opacity > 0.05);
    return {actors, bodies: bodiesOf(actors), placed: [] as Box[]};
  }));
  const labelled = new Map(shots.flatMap(({program}) => program.entities)
    .filter(({entity}) => entity.label).map(({entity}) => [entity.id, entity.label]));
  for (const [id, label] of labelled) {
    const {fontSize} = labelMetrics(label);
    const width = textWidth(label, fontSize);
    const boxesFor = (slot: number) => samples.map(({actors, bodies}): Box | null => {
      const index = actors.findIndex((actor) => actor.prepared.entity.id === id);
      if (index < 0) return null;
      const {x, y} = slotPosition(bodies[index], fontSize, width, slot);
      return {left: x - width / 2, right: x + width / 2, top: y - fontSize, bottom: y + 6};
    });
    const scored = order.map((slot, preference) => {
      const boxes = boxesFor(slot);
      const score = boxes.reduce((sum, box, sample) => box ? sum + bodyHits(box, samples[sample].bodies) * 1000
        + samples[sample].placed.filter((other) => intersects(box, other)).length * 1500 : sum, 0) + preference;
      return {slot, boxes, score};
    }).sort((a, b) => a.score - b.score)[0];
    slots.set(id, scored.slot);
    scored.boxes.forEach((box, sample) => {if (box) samples[sample].placed.push(box);});
  }
  return slots;
};
