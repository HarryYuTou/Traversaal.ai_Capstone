import {easing, entityAtFrame, toStage, type PreparedEntity} from './engine';
import type {MotionActivity, MotionPoint} from './types';

export type ActivityPose = {kind: MotionActivity['kind']; progress: number; phase: number; opacity: number};
/** facing runs -1 (walking left) to 1 (walking right), fading to 0 as the walker stops. */
export type MovementPose = {walking: boolean; phase: number; strength: number; facing: number};
/** breath runs -1..1 on a slow cycle; blink is 0 (open) to 1 (closed). */
export type IdlePose = {breath: number; blink: number};
/**
 * carry blends a person between resting arms (0) and holding their items at the counter (1);
 * markIn grows a service mark from 0 to 1 as it appears. Both default to the old on/off behaviour.
 */
export type IllustrationPose = {movement: MovementPose; activity: ActivityPose | null; carry?: number;
  markIn?: number; idle?: IdlePose};
const still: MovementPose = {walking: false, phase: 0, strength: 0, facing: 0};
const clamp = (value: number) => Math.max(0, Math.min(1, value));
const smooth = (value: number) => clamp(value) * clamp(value) * (3 - 2 * clamp(value));

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

export const activityAtFrame = (activities: readonly MotionActivity[], frame: number): ActivityPose | null => {
  const active = activeActivity(activities, frame);
  if (!active) return null;
  const elapsed = frame - active.from;
  const remaining = active.durationInFrames - elapsed;
  return {kind: active.kind, progress: clamp(elapsed / active.durationInFrames),
    phase: (elapsed / 18) % 1,
    // Work is visible throughout its interval; only the completion acknowledgement fades away.
    opacity: active.kind === 'complete' ? clamp(remaining / Math.min(5, active.durationInFrames)) : 1};
};

/** Items come up over CARRY_FRAMES once work starts and go down over the same time after it ends. */
export const carryAtFrame = (activities: readonly MotionActivity[], frame: number) => {
  let carry = 0;
  for (const activity of activities) {
    if (activity.kind !== 'work' || activity.durationInFrames <= 0 || frame < activity.from) continue;
    const end = activity.from + activity.durationInFrames;
    carry = Math.max(carry, frame < end ? smooth((frame - activity.from) / CARRY_FRAMES)
      : smooth(Math.min(1, (end - activity.from) / CARRY_FRAMES) - (frame - end) / CARRY_FRAMES));
  }
  return carry;
};

/**
 * A stride is tied to distance on the active positional track, never wall time or a prior render.
 * The short endpoint envelope lets the character plant its feet at each stop; idle actors stay still.
 */
export const movementPoseAtFrame = (prepared: PreparedEntity, frame: number): MovementPose => {
  if (prepared.entity.kind !== 'person') return still;
  const current = prepared.actions.filter(({action}) => ['move', 'follow-path', 'orbit'].includes(action.kind)
    && frame >= action.from && frame < action.from + action.durationInFrames).at(-1);
  if (!current) return still;
  const {action, initial, geometry} = current;
  const before = toStage(entityAtFrame(prepared, Math.max(action.from, frame - 0.5)));
  const after = toStage(entityAtFrame(prepared, Math.min(action.from + action.durationInFrames, frame + 0.5)));
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
  const strength = Math.min(1, elapsed / 4, remaining / 4);
  return {walking: true, phase: cycles % 1, strength, facing: (after.x - before.x) / step * strength};
};

/** A stable number in [0, 1) per actor, so idle cycles never march in lockstep. */
const seed = (id: string) => {
  let hash = 2166136261;
  for (let index = 0; index < id.length; index++) hash = Math.imul(hash ^ id.charCodeAt(index), 16777619);
  return (hash >>> 0) / 4294967296;
};

/** Breathing and blinking depend only on the absolute frame and the actor id, so any frame can be rendered alone. */
export const idlePoseAtFrame = (id: string, frame: number): IdlePose => {
  const offset = seed(id);
  const blinkAt = ((frame + offset * BLINK_EVERY) % BLINK_EVERY) / BLINK_FRAMES;
  return {breath: Math.sin(2 * Math.PI * (frame / BREATH_FRAMES + offset)),
    blink: blinkAt < 1 ? Math.sin(blinkAt * Math.PI) : 0};
};

export const illustrationPoseAtFrame = (prepared: PreparedEntity, frame: number): IllustrationPose => {
  const movement = movementPoseAtFrame(prepared, frame);
  const active = activeActivity(prepared.activities, frame);
  return {movement, activity: activityAtFrame(prepared.activities, frame),
    carry: carryAtFrame(prepared.activities, frame) * (1 - movement.strength),
    markIn: active ? smooth((frame - active.from + 1) / MARK_IN_FRAMES) : 0,
    idle: prepared.entity.kind === 'person' ? idlePoseAtFrame(prepared.entity.id, frame) : undefined};
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
  const tap = Math.sin((pose?.activity?.phase ?? 0) * Math.PI * 2) * 2 * carry;
  // Resting arms carry a straight elbow point so they blend point by point into the carrying pose.
  const leftHand = {x: -38 + Math.abs(swing) * 4, y: 24 + swing * 10};
  const rightHand = {x: 38 - Math.abs(swing) * 4, y: 24 - swing * 10};
  return {
    leftLeg: [{x: -17, y: 32}, {x: -20 + swing * 8, y: 60 - Math.max(0, swing) * 9},
      {x: -34 + swing * 4, y: 60 - Math.max(0, swing) * 9}],
    rightLeg: [{x: 17, y: 32}, {x: 20 - swing * 8, y: 60 - Math.max(0, -swing) * 9},
      {x: 34 - swing * 4, y: 60 - Math.max(0, -swing) * 9}],
    leftArm: mixPoints([{x: -23, y: 1}, {x: (-23 + leftHand.x) / 2, y: (1 + leftHand.y) / 2}, leftHand],
      [{x: -23, y: 1}, {x: -30, y: 20}, {x: -8, y: 14 + tap}], carry),
    rightArm: mixPoints([{x: 23, y: 1}, {x: (23 + rightHand.x) / 2, y: (1 + rightHand.y) / 2}, rightHand],
      [{x: 23, y: 1}, {x: 30, y: 20}, {x: 8, y: 14 - tap}], carry),
  };
};

/** Each footfall lifts the body slightly; the lift fades with the stride at the start and end of a walk. */
export const walkBob = (pose?: IllustrationPose) => pose?.movement.walking
  ? Math.abs(Math.sin(pose.movement.phase * Math.PI * 2)) * 3 * pose.movement.strength : 0;

export const limbPath = (points: MotionPoint[]) => points.map(({x, y}, index) => `${index ? 'L' : 'M'}${x},${y}`).join(' ');

/** One press during this item's processing, followed by release; the tool never moves when idle. */
export const workbenchPress = (activity: ActivityPose | null | undefined) => activity?.kind === 'work'
  ? Math.sin(clamp((activity.progress - 0.55) / 0.35) * Math.PI) * 7 : 0;
