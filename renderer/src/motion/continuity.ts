import type {TimelineScene} from '../types';
import {compileMotion, displayedPaths, entityAtFrame} from './engine';
import {illustrationPoseAtFrame} from './pose';
import {objectPerformanceAtFrame} from './objectPerformance';
import {motionEffectsAtFrame} from './motionEffects';
import {processStateAtFrame, stationStateAtFrame} from './processState';
import {rigPictureAtFrame} from './rig';

type MotionScene = Extract<TimelineScene, {template: 'motion'}>;
const EPSILON = 1e-6;
const clamp = (value: number) => Math.max(0, Math.min(1, value));

/** Compare rendered values, never object references or action-array identity. */
const equivalent = (a: unknown, b: unknown): boolean => {
  if (typeof a === 'number' && typeof b === 'number') {
    return Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) <= EPSILON;
  }
  if (a === b) return true;
  if (!a || !b || typeof a !== 'object' || typeof b !== 'object') return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    return Array.isArray(a) && Array.isArray(b) && a.length === b.length
      && a.every((value, index) => equivalent(value, b[index]));
  }
  const left = a as Record<string, unknown>;
  const right = b as Record<string, unknown>;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length
    && keys.every((key) => Object.hasOwn(right, key) && equivalent(left[key], right[key]));
};

const snapshot = (scene: MotionScene, frame: number, fps: number) => {
  const program = compileMotion(scene.visual);
  const actors = program.entities.flatMap((prepared) => {
    const state = entityAtFrame(prepared, frame);
    // Labels remain unscaled, so a scale-zero actor can still have visible text.
    if (state.opacity <= EPSILON) return [];
    const {entity} = prepared;
    const rotation = state.rotation % 360 * Math.PI / 180;
    const pose = illustrationPoseAtFrame(prepared, frame, fps);
    const station = scene.processTrace ? stationStateAtFrame(scene.processTrace, entity.id, frame) : null;
    return [{id: entity.id, kind: entity.kind, color: entity.color, label: entity.label,
      state: {...state, rotation: undefined, rotationX: Math.cos(rotation), rotationY: Math.sin(rotation)},
      // Human limbs, gaze and idle motion may retain history after a move or work interval ends.
      // Semantic object parts can also retain history (for example a package's completed seal).
      pose: prepared.rig ? undefined : entity.kind === 'person' ? pose : {activity: pose.activity, markIn: pose.markIn},
      objectPose: entity.kind === 'person' || prepared.rig ? undefined : objectPerformanceAtFrame(prepared, frame, fps),
      rigPicture: prepared.rig ? rigPictureAtFrame(prepared.rig, frame) : undefined,
      station: station ? {...station, openingProgress: station.open ? 1 : station.openingProgress} : null}];
  });
  // Source order is retained: overlapping SVG actors can change their appearance if reordered.
  const routes = scene.processTrace ? [] : displayedPaths(program, frame).flatMap((route) => {
    const shown = clamp((frame - route.from) / 10);
    return shown <= EPSILON ? [] : [{geometry: route.geometry.d, color: route.path.color,
      shown, progress: route.progress}];
  });
  // Rolling counts use their last nine frames as well as the current value. Matching only the final
  // count would allow a newly compiled scene to reset a roll that is still visible at the boundary.
  const counts = scene.processTrace ? Array.from({length: 10}, (_, offset) => {
    const {waiting, inService, unfinished} = processStateAtFrame(scene.processTrace!, frame - offset);
    return {waiting, inService, unfinished};
  }) : null;
  const effects = motionEffectsAtFrame(program, frame, fps, Boolean(scene.processTrace));
  return {actors, routes, counts, effects};
};

/**
 * Sharing a camera does not imply a continuous performance. Compare the mathematical boundary
 * frame on both sides: a replay, changed cast or restarted pose fades, while a true continuation
 * can cut without duplicating characters. This is independent of topic and never rewrites a scene.
 */
export const motionBoundaryIsContinuous = (before: MotionScene, after: MotionScene, fps = 30): boolean => {
  const boundary = before.from + before.durationInFrames;
  if (before.durationInFrames <= 0 || after.durationInFrames <= 0 || boundary !== after.from
    || before.chapterId !== after.chapterId || Boolean(before.processTrace) !== Boolean(after.processTrace)) return false;
  return equivalent(snapshot(before, boundary, fps), snapshot(after, after.from, fps));
};
