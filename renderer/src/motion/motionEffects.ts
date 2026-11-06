import {entityAtFrame, toStage, type MotionProgram, type PreparedEntity} from './engine';
import {entityHalfExtents} from './metrics';
import type {MotionColor, MotionPoint} from './types';

const clamp = (value: number) => Math.max(0, Math.min(1, value));
const smooth = (value: number) => clamp(value) ** 2 * (3 - 2 * clamp(value));
const movingKinds = new Set(['moon', 'planet', 'satellite', 'rocket', 'spacecraft', 'lander',
  'lander-ascent', 'packet', 'coin']);
export type MotionTrace = {id: string; color: MotionColor; opacity: number; points: MotionPoint[];
  arrow: MotionPoint[]};
export type OrbitGuide = {id: string; color: MotionColor; opacity: number; x: number; y: number; radius: number};
export type MotionEffects = {traces: MotionTrace[]; orbits: OrbitGuide[]};
const distance = (a: MotionPoint, b: MotionPoint) => Math.hypot(a.x - b.x, a.y - b.y);
const positional = (kind: string) => ['move', 'follow-path', 'orbit'].includes(kind);

/** Stop a direction trace at the back of its own object, never through its drawing or label. */
const trimTip = (points: MotionPoint[], clearance: number) => {
  const result = [...points];
  let left = clearance;
  while (result.length > 1) {
    const tip = result.at(-1)!;
    const previous = result.at(-2)!;
    const length = distance(tip, previous);
    if (length > left) {
      result[result.length - 1] = {x: tip.x + (previous.x - tip.x) * left / length,
        y: tip.y + (previous.y - tip.y) * left / length};
      return result;
    }
    left -= length;
    result.pop();
  }
  return [];
};

const traceFor = (prepared: PreparedEntity, frame: number, fps: number): MotionTrace | null => {
  const scale = fps / 30;
  const track = prepared.actions.filter(({action}) => positional(action.kind) && action.durationInFrames > 0
    && frame >= action.from && frame < action.from + action.durationInFrames).at(-1);
  if (!track) return null;
  const {action} = track;
  const end = action.from + action.durationInFrames;
  const at = Math.min(frame, end);
  const state = entityAtFrame(prepared, frame);
  if (state.opacity < 0.001 || state.size <= 0) return null;
  // History is a geometric cue: it follows actual positions, and conveys neither thrust nor speed units.
  // Use up to one quarter of this move so slower narrated examples still have a legible direction.
  const history = Math.min(action.durationInFrames * 0.25, 2 * fps);
  const start = Math.max(action.from, at - history);
  const points = Array.from({length: 49}, (_, i) =>
    toStage(entityAtFrame(prepared, start + (at - start) * i / 48)));
  const extent = entityHalfExtents(prepared.entity.kind, state.size, state.rotation);
  const tip = points.at(-1)!;
  const near = points.at(-2)!;
  const tangent = distance(tip, near);
  const ux = tangent ? (tip.x - near.x) / tangent : 1;
  const uy = tangent ? (tip.y - near.y) / tangent : 0;
  const clearance = Math.hypot(extent.x * ux, extent.y * uy) + 10;
  const trimmed = trimTip(points, clearance);
  if (trimmed.length < 2) return null;
  const length = trimmed.slice(1).reduce((sum, point, i) => sum + distance(point, trimmed[i]), 0);
  if (length < 1) return null;
  const head = trimmed.at(-1)!;
  const tail = trimmed.at(-2)!;
  const norm = distance(head, tail);
  const dx = norm ? (head.x - tail.x) / norm : ux;
  const dy = norm ? (head.y - tail.y) / norm : uy;
  const size = 7 * smooth(length / 16);
  const arrow = [{x: head.x - dx * size - dy * size * 0.6, y: head.y - dy * size + dx * size * 0.6},
    head, {x: head.x - dx * size + dy * size * 0.6, y: head.y - dy * size - dx * size * 0.6}];
  const opacity = state.opacity * smooth((frame - action.from) / (8 * scale))
    * smooth((end - frame) / (9 * scale)) * smooth(length / 28);
  return {id: prepared.entity.id, color: prepared.entity.color, opacity, points: trimmed, arrow};
};

/** Frame-pure visual explanations of existing movement. No new motion, forces or causal events. */
export const motionEffectsAtFrame = (program: MotionProgram, frame: number, fps = 30,
  process = false): MotionEffects => {
  if (process) return {traces: [], orbits: []};
  const safeFps = Number.isFinite(fps) && fps > 0 ? fps : 30;
  const traces: MotionTrace[] = [];
  const orbits: OrbitGuide[] = [];
  for (const prepared of program.entities) {
    if (!movingKinds.has(prepared.entity.kind)) continue;
    const trace = traceFor(prepared, frame, safeFps);
    if (trace) traces.push(trace);
    // Orbit actions do not require an authored path. Show their real circle, not an invented ellipse.
    const orbit = prepared.actions.filter(({action}) => action.kind === 'orbit'
      && action.durationInFrames > 0 && frame >= action.from).at(-1);
    if (!orbit || orbit.action.value === 0) continue;
    const center = toStage(orbit.action);
    const radius = distance(toStage(orbit.initial), center);
    if (radius <= 1e-6) continue;
    orbits.push({id: prepared.entity.id, color: prepared.entity.color, x: center.x, y: center.y, radius,
      opacity: entityAtFrame(prepared, frame).opacity * smooth((frame - orbit.action.from) / (safeFps * 0.3))});
  }
  return {traces, orbits};
};
