import {entityAtFrame, type PreparedEntity} from './engine';
import {activityAtFrame, type ActivityPose} from './pose';
import type {EntityKind, MotionCue} from './types';

export type ObjectPerformancePose = {
  activity: ActivityPose | null;
  processing: number;
  workProgress: number;
  complete: number;
  phase: number;
  pack: {close: number; tape: number; label: number} | null;
  scan: {progress: number; opacity: number} | null;
  signal: {kind: 'send' | 'receive'; progress: number; opacity: number} | null;
  compute: {progress: number; opacity: number; phase: number} | null;
  thrust: number;
  thrustPhase: number;
  arrival: number;
  change: number;
};

const clamp = (n: number) => Math.max(0, Math.min(1, n));
const smooth = (n: number) => {const t = clamp(n); return t * t * (3 - 2 * t);};
const part = (progress: number, from: number, to: number) => smooth((progress - from) / (to - from));

/** Local acting is limited to an object's actual capabilities; motion alone never implies a burn,
 * a successful delivery, or a packed parcel. Keep this vocabulary aligned with the scene schema. */
export const OBJECT_CUE_KINDS: Record<MotionCue['kind'], readonly EntityKind[]> = {
  pack: ['box'], scan: ['box', 'packet'],
  send: ['packet', 'server', 'laptop', 'cloud', 'satellite'],
  receive: ['packet', 'server', 'laptop', 'cloud', 'satellite'],
  compute: ['packet', 'server', 'laptop', 'cloud'],
  thrust: ['rocket', 'spacecraft', 'lander', 'lander-ascent', 'satellite'],
};

/** A cue's envelope reaches zero at both ends, including when a scene is sought out of order. */
const envelope = (cue: MotionCue, frame: number, fps: number) => {
  const duration = Math.max(1, cue.durationInFrames);
  const elapsed = frame - cue.from;
  const ramp = Math.min(duration / 3, fps * 0.16);
  return smooth(elapsed / ramp) * smooth((duration - elapsed) / ramp);
};

/** Stateless object acting follows explicit cues and existing work events. It never changes an
 * entity's position, route, dimensions, numerical value, or the process's participant count. */
export const objectPerformanceAtFrame = (prepared: PreparedEntity, frame: number, fps = 30): ObjectPerformancePose => {
  // Equivalent second-to-frame conversions can straddle an exact cue endpoint by 1e-14 frames.
  // Canonicalize only the acting clock; authored geometry is never modified.
  frame = Math.round(frame * 1e9) / 1e9;
  const rate = Number.isFinite(fps) && fps > 0 ? fps : 30;
  const cues = (prepared.cues ?? []).filter((cue) =>
    OBJECT_CUE_KINDS[cue.kind]?.includes(prepared.entity.kind))
    .slice().sort((a, b) => a.from - b.from || a.kind.localeCompare(b.kind));
  const active = (kind: MotionCue['kind']) => [...cues].reverse().find((cue) => cue.kind === kind &&
    frame >= cue.from && frame < cue.from + cue.durationInFrames);
  const progress = (cue: MotionCue) => clamp((frame - cue.from) / Math.max(1, cue.durationInFrames));
  const timed = (cue: MotionCue | undefined) => cue ? {progress: progress(cue), opacity: envelope(cue, frame, rate)} : null;
  const activity = activityAtFrame(prepared.activities ?? [], frame, rate);
  const work = activity?.kind === 'work' ? activity : null;
  const processing = work?.opacity ?? 0;
  const packCues = cues.filter((cue) => cue.kind === 'pack');
  const packingState = prepared.entity.kind === 'box' ? prepared.entity.packingState : undefined;
  const initialPacking = packingState === 'sealed' ? 1 : packingState === 'prepared' ? 0.5 : 0;
  // A persistent package cannot reopen at a later cue or a continued service interval. An
  // unfinished interval closes the flaps without claiming finished tape and a shipping label.
  const packing = packCues.reduce((amount, cue) => {
    if (frame < cue.from) return amount;
    const start = cue.continued ? 0.5 : 0;
    const end = cue.complete === false ? 0.5 : 1;
    return Math.max(amount, start + progress(cue) * (end - start));
  }, Math.max(initialPacking, packCues[0]?.continued ? 0.5 : 0));
  const send = active('send');
  const receive = active('receive');
  const signalCue = receive && (!send || receive.from >= send.from) ? receive : send;
  const compute = active('compute');
  const thrust = active('thrust');
  const moving = new Set(['move', 'follow-path', 'orbit']);
  const arrivals = prepared.actions.filter(({action}) => moving.has(action.kind) || action.kind === 'opacity');
  const state = entityAtFrame(prepared, frame);
  const arrival = arrivals.reduce((strength, {action, initial, geometry}) => {
    if (action.kind === 'opacity' && action.value <= initial.opacity) return strength;
    if (action.kind === 'move' && Math.hypot(action.x - initial.x, action.y - initial.y) < 1e-6 ||
      action.kind === 'follow-path' && (!geometry || geometry.length < 1e-6) ||
      action.kind === 'orbit' && (Math.abs(action.value) < 1e-6 ||
        Math.hypot(action.x - initial.x, action.y - initial.y) < 1e-6) || state.opacity < 0.001) return strength;
    const elapsed = (frame - action.from - action.durationInFrames) / rate;
    return elapsed >= 0 && elapsed <= 0.5 ? Math.max(strength, Math.sin(elapsed / 0.5 * Math.PI)) : strength;
  }, 0);
  const change = prepared.actions.reduce((strength, {action, initial}) => {
    if (!['value', 'rotate'].includes(action.kind) || frame < action.from ||
      frame > action.from + action.durationInFrames) return strength;
    if (action.kind === 'value' && action.value === initial.value ||
      action.kind === 'rotate' && action.value === initial.rotation) return strength;
    const t = clamp((frame - action.from) / Math.max(1, action.durationInFrames));
    return Math.max(strength, Math.sin(t * Math.PI));
  }, 0);
  return {
    activity, processing, workProgress: work?.progress ?? 0,
    complete: activity?.kind === 'complete' ? activity.opacity : 0,
    phase: work?.phase ?? 0,
    pack: packCues.length || packingState ? {close: part(packing, 0.08, 0.5), tape: part(packing, 0.53, 0.77),
      label: part(packing, 0.8, 0.96)} : null,
    scan: timed(active('scan')),
    signal: signalCue ? {...timed(signalCue)!, kind: signalCue.kind as 'send' | 'receive'} : null,
    compute: compute ? {...timed(compute)!, phase: (frame - compute.from) / rate} : null,
    thrust: thrust ? envelope(thrust, frame, rate) : 0,
    thrustPhase: thrust ? (frame - thrust.from) / rate : 0,
    arrival, change: Number.isFinite(state.value) ? change : 0,
  };
};
