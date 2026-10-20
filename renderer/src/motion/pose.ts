import {easing, entityAtFrame, toStage, type PreparedEntity} from './engine';
import type {MotionActivity, MotionPoint} from './types';

export type ActivityPose = {kind: MotionActivity['kind']; progress: number; phase: number; opacity: number};
export type MovementPose = {walking: boolean; phase: number; strength: number};
export type IllustrationPose = {movement: MovementPose; activity: ActivityPose | null};
const still: MovementPose = {walking: false, phase: 0, strength: 0};
const clamp = (value: number) => Math.max(0, Math.min(1, value));

/** A completion interval wins over concurrent work, independent of source array order. */
export const activityAtFrame = (activities: readonly MotionActivity[], frame: number): ActivityPose | null => {
  const active = activities.filter((activity) => activity.durationInFrames > 0
    && frame >= activity.from && frame < activity.from + activity.durationInFrames)
    .sort((a, b) => Number(b.kind === 'complete') - Number(a.kind === 'complete')
      || b.from - a.from || b.durationInFrames - a.durationInFrames)[0];
  if (!active) return null;
  const elapsed = frame - active.from;
  const remaining = active.durationInFrames - elapsed;
  return {kind: active.kind, progress: clamp(elapsed / active.durationInFrames),
    phase: (elapsed / 18) % 1,
    // Work is visible throughout its interval; only the completion acknowledgement fades away.
    opacity: active.kind === 'complete' ? clamp(remaining / Math.min(5, active.durationInFrames)) : 1};
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
  if (Math.hypot(after.x - before.x, after.y - before.y) < 1e-5) return still;
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
  return {walking: true, phase: cycles % 1, strength: Math.min(1, elapsed / 4, remaining / 4)};
};

export const illustrationPoseAtFrame = (prepared: PreparedEntity, frame: number): IllustrationPose => ({
  movement: movementPoseAtFrame(prepared, frame), activity: activityAtFrame(prepared.activities, frame),
});

/** Shared coordinates make every articulated limb testable against the unchanged person footprint. */
export const personLimbs = (pose?: IllustrationPose): Record<'leftLeg' | 'rightLeg' | 'leftArm' | 'rightArm', MotionPoint[]> => {
  const walk = pose?.movement;
  const swing = walk?.walking ? Math.sin(walk.phase * Math.PI * 2) * walk.strength : 0;
  const working = pose?.activity?.kind === 'work' && !walk?.walking;
  const tap = working ? Math.sin(pose!.activity!.phase * Math.PI * 2) * 2 : 0;
  return {
    leftLeg: [{x: -17, y: 32}, {x: -20 + swing * 8, y: 60 - Math.max(0, swing) * 9},
      {x: -34 + swing * 4, y: 60 - Math.max(0, swing) * 9}],
    rightLeg: [{x: 17, y: 32}, {x: 20 - swing * 8, y: 60 - Math.max(0, -swing) * 9},
      {x: 34 - swing * 4, y: 60 - Math.max(0, -swing) * 9}],
    leftArm: working ? [{x: -23, y: 1}, {x: -30, y: 20}, {x: -8, y: 14 + tap}]
      : [{x: -23, y: 1}, {x: -38 + Math.abs(swing) * 4, y: 24 + swing * 10}],
    rightArm: working ? [{x: 23, y: 1}, {x: 30, y: 20}, {x: 8, y: 14 - tap}]
      : [{x: 23, y: 1}, {x: 38 - Math.abs(swing) * 4, y: 24 - swing * 10}],
  };
};

export const limbPath = (points: MotionPoint[]) => points.map(({x, y}, index) => `${index ? 'L' : 'M'}${x},${y}`).join(' ');

/** One press during this item's processing, followed by release; the tool never moves when idle. */
export const workbenchPress = (activity: ActivityPose | null | undefined) => activity?.kind === 'work'
  ? Math.sin(clamp((activity.progress - 0.55) / 0.35) * Math.PI) * 7 : 0;
