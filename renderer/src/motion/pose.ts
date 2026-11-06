import {easing, entityAtFrame, toStage, type PreparedAction, type PreparedEntity} from './engine';
import type {MotionActivity, MotionPoint} from './types';

export type ActivityPose = {kind: MotionActivity['kind']; progress: number; phase: number; opacity: number};
/** facing runs -1 (walking left) to 1 (walking right), fading to 0 as the walker stops. */
export type MovementPose = {walking: boolean; phase: number; strength: number; facing: number};
/** breath runs -1..1 on a slow cycle; blink is 0 (open) to 1 (closed). */
export type IdlePose = {breath: number; blink: number};
/** Local secondary motion only: authored positions, event timing and travel paths remain untouched. */
export type PerformancePose = {lookX: number; lean: number; headTilt: number; settle: number;
  reach: number; acknowledge: number};
/**
 * carry blends a person between resting arms (0) and holding their items at the counter (1);
 * markIn grows a service mark from 0 to 1 as it appears. Both default to the old on/off behaviour.
 */
export type IllustrationPose = {movement: MovementPose; activity: ActivityPose | null; carry?: number;
  markIn?: number; idle?: IdlePose; performance?: PerformancePose};
const still: MovementPose = {walking: false, phase: 0, strength: 0, facing: 0};
const clamp = (value: number) => Math.max(0, Math.min(1, value));
const smooth = (value: number) => clamp(value) * clamp(value) * (3 - 2 * clamp(value));
const frameScale = (fps: number) => Number.isFinite(fps) && fps > 0 ? fps / 30 : 1;
// Position interpolation can leave ~1e-13 horizontal drift on a vertical route. It must never
// become a left/right view change. This is a directional tolerance, independent of actor scale.
export const HORIZONTAL_DIRECTION_EPSILON = 1e-6;
const horizontalDirection = (x: number, y: number) => {
  const distance = Math.hypot(x, y);
  return distance > 1e-8 && Math.abs(x) > Math.max(1e-8, distance * HORIZONTAL_DIRECTION_EPSILON)
    ? x / distance : 0;
};

// Frames for a person to raise or lower their items, and for a service mark to grow in.
export const CARRY_FRAMES = 7;
export const MARK_IN_FRAMES = 8;
// One slow breath every 2.6 s and a blink about every 4 s at 30 fps; each actor gets its own offset.
const BREATH_FRAMES = 78;
const BLINK_EVERY = 121;
const BLINK_FRAMES = 5;

/** A completion interval wins over concurrent work, independent of source array order. */
const activeActivity = (activities: readonly MotionActivity[], frame: number) => activities
  .filter((activity) => activity.durationInFrames > 0
    && frame >= activity.from && frame < activity.from + activity.durationInFrames)
  .sort((a, b) => Number(b.kind === 'complete') - Number(a.kind === 'complete')
    || b.from - a.from || b.durationInFrames - a.durationInFrames)[0];

export const activityAtFrame = (activities: readonly MotionActivity[], frame: number, fps = 30): ActivityPose | null => {
  const active = activeActivity(activities, frame);
  if (!active) return null;
  const elapsed = frame - active.from;
  const remaining = active.durationInFrames - elapsed;
  const cycles = elapsed / (18 * frameScale(fps));
  const phase = Math.abs(cycles - Math.round(cycles)) < 1e-9 ? 0 : cycles % 1;
  return {kind: active.kind, progress: clamp(elapsed / active.durationInFrames),
    phase,
    // Work is visible throughout its interval; only the completion acknowledgement fades away.
    opacity: active.kind === 'complete' ? clamp(remaining / Math.min(5 * frameScale(fps), active.durationInFrames)) : 1};
};

/** Items come up over CARRY_FRAMES once work starts and go down over the same time after it ends. */
export const carryAtFrame = (activities: readonly MotionActivity[], frame: number, fps = 30) => {
  const ramp = CARRY_FRAMES * frameScale(fps);
  let carry = 0;
  for (const activity of activities) {
    if (activity.kind !== 'work' || activity.durationInFrames <= 0 || frame < activity.from) continue;
    const end = activity.from + activity.durationInFrames;
    carry = Math.max(carry, frame < end ? smooth((frame - activity.from) / ramp)
      : smooth(Math.min(1, (end - activity.from) / ramp) - (frame - end) / ramp));
  }
  return carry;
};

/**
 * A stride is tied to distance on the active positional track, never wall time or a prior render.
 * The short endpoint envelope lets the character plant its feet at each stop; idle actors stay still.
 */
export const movementPoseAtFrame = (prepared: PreparedEntity, frame: number, fps = 30): MovementPose => {
  if (prepared.entity.kind !== 'person') return still;
  const current = prepared.actions.filter(({action}) => ['move', 'follow-path', 'orbit'].includes(action.kind)
    && frame >= action.from && frame < action.from + action.durationInFrames).at(-1);
  if (!current) return still;
  const {action, initial, geometry} = current;
  const sample = 0.5 * frameScale(fps);
  const before = toStage(entityAtFrame(prepared, Math.max(action.from, frame - sample)));
  const after = toStage(entityAtFrame(prepared, Math.min(action.from + action.durationInFrames, frame + sample)));
  const step = Math.hypot(after.x - before.x, after.y - before.y);
  if (step < 1e-5) return still;
  const progress = easing((frame - action.from) / Math.max(1, action.durationInFrames), action.easing);
  const origin = toStage(initial);
  const destination = toStage(action);
  const stride = 44 * Math.max(0.25, initial.size);
  let cycles: number;
  if (action.kind === 'orbit') {
    const radius = Math.hypot(origin.x - destination.x, origin.y - destination.y);
    // Reduce the number of turns before multiplying by radius, including finite huge authored angles.
    const cyclesPerDegree = radius * Math.PI / (180 * stride);
    cycles = cyclesPerDegree ? ((Math.abs(action.value * progress) % (1 / cyclesPerDegree)) * cyclesPerDegree) : 0;
  } else {
    const length = geometry?.length ?? Math.hypot(destination.x - origin.x, destination.y - origin.y);
    cycles = length * progress / stride;
  }
  const elapsed = frame - action.from;
  const remaining = action.from + action.durationInFrames - frame;
  const strength = smooth(Math.min(1, elapsed / (4 * frameScale(fps)), remaining / (4 * frameScale(fps))));
  return {walking: true, phase: cycles % 1, strength,
    facing: horizontalDirection(after.x - before.x, after.y - before.y) * strength};
};

/** A stable number in [0, 1) per actor, so idle cycles never march in lockstep. */
const seed = (id: string) => {
  let hash = 2166136261;
  for (let index = 0; index < id.length; index++) hash = Math.imul(hash ^ id.charCodeAt(index), 16777619);
  return (hash >>> 0) / 4294967296;
};

/** Breathing and blinking depend only on the absolute frame and the actor id, so any frame can be rendered alone. */
export const idlePoseAtFrame = (id: string, frame: number, fps = 30): IdlePose => {
  const offset = seed(id);
  const time = frame / frameScale(fps);
  const blinkAt = (((time + offset * BLINK_EVERY) % BLINK_EVERY + BLINK_EVERY) % BLINK_EVERY) / BLINK_FRAMES;
  return {breath: Math.sin(2 * Math.PI * (time / BREATH_FRAMES + offset)),
    blink: blinkAt < 1 ? Math.sin(blinkAt * Math.PI) : 0};
};

const hasTravel = ({action, initial, geometry}: PreparedAction) => {
  if (!['move', 'follow-path', 'orbit'].includes(action.kind) || action.durationInFrames <= 0) return false;
  if (geometry) return geometry.length > 0.001;
  const start = toStage(initial);
  const end = toStage(action);
  return Math.hypot(end.x - start.x, end.y - start.y) > 0.001
    && (action.kind !== 'orbit' || Math.abs(action.value) > 0.001);
};

/** Sample the authored trajectory in physical time. The same tangent is obtained at 24/30/60 fps. */
const travelVector = (prepared: PreparedEntity, travel: PreparedAction, frame: number, scale: number) => {
  const {action} = travel;
  const at = Math.max(action.from, Math.min(action.from + action.durationInFrames, frame));
  const a = Math.max(action.from, at - scale);
  const b = Math.min(action.from + action.durationInFrames, at + scale);
  const before = toStage(entityAtFrame(prepared, a));
  const after = toStage(entityAtFrame(prepared, b));
  const x = after.x - before.x;
  const y = after.y - before.y;
  const distance = Math.hypot(x, y);
  return {direction: horizontalDirection(x, y), speed: distance * scale / Math.max(1e-8, b - a)};
};

/** A vertical stretch has no new left/right intention. Recover the last meaningful direction
 * from the authored route, not from a previously rendered frame, so seeks stay deterministic. */
const attentionDirection = (prepared: PreparedEntity, travel: PreparedAction, frame: number,
  scale: number, held: number): number => {
  const current = travelVector(prepared, travel, frame, scale).direction;
  if (current !== 0) return current;
  const {action, geometry} = travel;
  if (geometry) {
    const distance = easing((frame - action.from) / Math.max(1, action.durationInFrames), action.easing) * geometry.length;
    for (let index = geometry.points.length - 1; index > 0; index--) {
      if (geometry.lengths[index - 1] >= distance) continue;
      const a = geometry.points[index - 1];
      const b = geometry.points[index];
      const direction = horizontalDirection(b.x - a.x, b.y - a.y);
      if (direction !== 0) return direction;
    }
  } else if (action.kind === 'orbit' && frame > action.from) {
    // At an orbit's exactly vertical tangent, keep the approach direction through the zero.
    const approach = travelVector(prepared, travel, Math.max(action.from, frame - scale), scale).direction;
    if (approach !== 0) return approach;
  }
  return held;
};

/** Attention leads travel, then holds the final direction until another authored movement begins.
 * This is reconstructed from tracks each time: no mutable facing state or dependence on render order. */
export const performanceAtFrame = (prepared: PreparedEntity, frame: number, fps = 30): PerformancePose | undefined => {
  if (prepared.entity.kind !== 'person') return undefined;
  const scale = frameScale(fps);
  const lead = 5 * scale;
  const turn = 3 * scale;
  const travels = prepared.actions.filter(hasTravel);
  const movement = movementPoseAtFrame(prepared, frame, fps);
  let lookX = 0;
  let preparation = 0;
  let lastStop = -Infinity;
  let active: PreparedAction | undefined;
  for (let index = 0; index < travels.length; index++) {
    const travel = travels[index];
    const {action} = travel;
    const end = Math.min(action.from + action.durationInFrames, travels[index + 1]?.action.from ?? Infinity);
    if (frame < action.from - lead) break;
    const target = attentionDirection(prepared, travel,
      Math.min(end, Math.max(action.from, frame + lead)), scale, lookX);
    if (frame < end) {
      const attention = smooth((frame - (action.from - lead)) / (lead + turn));
      lookX += (target - lookX) * attention;
      const preparationPhase = (frame - (action.from - lead)) / (lead + 6 * scale);
      preparation = preparationPhase > 0 && preparationPhase < 1 ? Math.sin(Math.PI * preparationPhase) ** 2 : 0;
      if (frame >= action.from) active = travel;
      // Adjacent moves can turn without pausing. Let the next track lead the eyes before the
      // current one ends, instead of changing facing abruptly on their shared boundary.
      if (!travels[index + 1] || frame < travels[index + 1].action.from - lead) break;
      continue;
    }
    lookX = attentionDirection(prepared, travel, end, scale, lookX);
    lastStop = end;
  }
  const stopPhase = (frame - lastStop) / (12 * scale);
  const settle = stopPhase > 0 && stopPhase < 1
    ? Math.sin(Math.PI * stopPhase) ** 2 * 1.4 * (1 - movement.strength) : 0;
  let acceleration = 0;
  if (active) {
    const before = travelVector(prepared, active, frame - 3 * scale, scale).speed;
    const after = travelVector(prepared, active, frame + 3 * scale, scale).speed;
    acceleration = Math.max(-1, Math.min(1, (after - before) / Math.max(0.1, before, after)));
  }
  const completion = activeActivity(prepared.activities, frame);
  const nodPhase = completion?.kind === 'complete'
    ? (frame - completion.from) / Math.min(completion.durationInFrames, 18 * scale) : -1;
  const acknowledge = nodPhase > 0 && nodPhase < 1 ? Math.sin(Math.PI * nodPhase) ** 2 : 0;
  const lean = lookX * (movement.strength * (1.4 + acceleration * 1.5) + preparation * 1.2 - settle * 0.35);
  return {lookX, lean: Math.max(-3.4, Math.min(3.4, lean)),
    headTilt: lookX * 1.1 - acknowledge * 2.2 + settle * 0.3, settle,
    reach: carryAtFrame(prepared.activities, frame, fps) * (1 - movement.strength), acknowledge};
};

export const illustrationPoseAtFrame = (prepared: PreparedEntity, frame: number, fps = 30): IllustrationPose => {
  const movement = movementPoseAtFrame(prepared, frame, fps);
  const active = activeActivity(prepared.activities, frame);
  return {movement, activity: activityAtFrame(prepared.activities, frame, fps),
    carry: carryAtFrame(prepared.activities, frame, fps) * (1 - movement.strength),
    markIn: active ? smooth((frame - active.from + frameScale(fps)) / (MARK_IN_FRAMES * frameScale(fps))) : 0,
    idle: prepared.entity.kind === 'person' ? idlePoseAtFrame(prepared.entity.id, frame, fps) : undefined,
    performance: performanceAtFrame(prepared, frame, fps)};
};

/** How far a person is into holding their items; poses built without `carry` keep the old on/off rule. */
export const carryOf = (pose?: IllustrationPose) => pose?.carry
  ?? (pose?.activity?.kind === 'work' && !pose.movement.walking ? 1 : 0);

const mixPoints = (rest: MotionPoint[], work: MotionPoint[], amount: number) =>
  rest.map((point, index) => ({x: point.x + (work[index].x - point.x) * amount,
    y: point.y + (work[index].y - point.y) * amount}));

/** Shared coordinates make every articulated limb testable against the unchanged person footprint. */
export const personLimbs = (pose?: IllustrationPose): Record<'leftLeg' | 'rightLeg' | 'leftArm' | 'rightArm', MotionPoint[]> => {
  const walk = pose?.movement;
  const swing = walk?.walking ? Math.sin(walk.phase * Math.PI * 2) * walk.strength : 0;
  const carry = carryOf(pose);
  const direction = pose?.performance?.lookX ?? walk?.facing ?? 1;
  // Feet follow the current trajectory, not the anticipatory gaze that may already face the next
  // turn. Movement facing includes the endpoint envelope; remove it before applying stride strength.
  const footDirection = walk?.walking && walk.strength > 1e-8
    ? Math.max(-1, Math.min(1, (walk.facing ?? walk.strength) / walk.strength)) : 0;
  const reach = direction * (pose?.performance?.reach ?? 0) * 7;
  const tap = pose?.performance ? -pose.performance.acknowledge * 1.5 * carry
    : Math.sin((pose?.activity?.phase ?? 0) * Math.PI * 2) * 2 * carry;
  const leg = (side: number, offset: number): MotionPoint[] => {
    const phase = ((walk?.phase ?? 0) + offset) % 1;
    // Each foot spends 60% of a stride on the floor. During stance it travels backward at a
    // constant local speed; the shorter swing lifts and returns it smoothly to the next landing.
    const stance = phase < 0.6;
    const progress = stance ? phase / 0.6 : (phase - 0.6) / 0.4;
    const travel = stance ? 1 - 2 * progress : -1 + 2 * smooth(progress);
    const strength = walk?.walking ? walk.strength : 0;
    const lift = stance ? 0 : Math.sin(Math.PI * progress) ** 2 * 8 * strength;
    // During 60% of a 44-unit stride the body travels 26.4 units. Equal opposite foot travel
    // cancels that translation at full strength. Narrower walking shoes retain the original bounds.
    const x = side * (20 - 2 * strength) + travel * 13.2 * strength * footDirection;
    return [{x: side * 17, y: 32}, {x: (side * 17 + x) / 2, y: 46 - lift * 0.6},
      {x, y: 60 - lift}, {x: x + side * (14 - 8 * strength), y: 60 - lift}];
  };
  // Resting arms carry a straight elbow point so they blend point by point into the carrying pose.
  const leftHand = {x: -38 + Math.abs(swing) * 4, y: 24 + swing * 10};
  const rightHand = {x: 38 - Math.abs(swing) * 4, y: 24 - swing * 10};
  return {
    leftLeg: leg(-1, 0),
    rightLeg: leg(1, 0.5),
    leftArm: mixPoints([{x: -23, y: 1}, {x: (-23 + leftHand.x) / 2, y: (1 + leftHand.y) / 2}, leftHand],
      [{x: -23, y: 1}, {x: -30 + reach * 0.4, y: 20}, {x: -8 + reach, y: 14 + tap}], carry),
    rightArm: mixPoints([{x: 23, y: 1}, {x: (23 + rightHand.x) / 2, y: (1 + rightHand.y) / 2}, rightHand],
      [{x: 23, y: 1}, {x: 30 + reach * 0.4, y: 20}, {x: 8 + reach, y: 14 - tap}], carry),
  };
};

/** Each footfall lifts the body slightly; the lift fades with the stride at the start and end of a walk. */
export const walkBob = (pose?: IllustrationPose) => pose?.movement.walking
  ? Math.abs(Math.sin(pose.movement.phase * Math.PI * 2)) * 3 * pose.movement.strength : 0;

export const limbPath = (points: MotionPoint[]) => points.map(({x, y}, index) => `${index ? 'L' : 'M'}${x},${y}`).join(' ');

/** One press during this item's processing, followed by release; the tool never moves when idle. */
export const workbenchPress = (activity: ActivityPose | null | undefined) => activity?.kind === 'work'
  ? Math.sin(clamp((activity.progress - 0.55) / 0.35) * Math.PI) * 7 : 0;
