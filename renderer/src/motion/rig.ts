import type {CustomRig, RigClip, RigKeyframe, RigPart, RigPerformance, RigProperty, RigShape, RigTransform} from './types';

export type RigBounds = {left: number; top: number; right: number; bottom: number};
type Bounds = RigBounds;
type Range = [number, number];
type TransformRanges = Record<RigProperty, Range>;
export type RigPose = Record<string, RigTransform>;
export type PreparedRigPerformance = {performance: RigPerformance; clip: RigClip; initial: RigPose};
export type PreparedRig = {definition: CustomRig; performances: PreparedRigPerformance[];
  extents: [number, number]; bounds: RigBounds};
export type RigMatrix = [number, number, number, number, number, number];
const PROPERTIES: RigProperty[] = ['x', 'y', 'rotation', 'scaleX', 'scaleY', 'opacity'];
const COLOR = /^(?:ink|accent|secondary|muted|paper|soft|line|none|#[0-9a-fA-F]{6})$/;
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const validId = (id: string) => typeof id === 'string' && id.length <= 48 && ID.test(id);
const finite = (n: number, limit = Infinity) => Number.isFinite(n) && Math.abs(n) <= limit;
const clamp = (n: number) => Math.max(0, Math.min(1, n));
const fail = (message: string): never => {throw new Error(`Invalid custom rig: ${message}`);};
const scaled = (property: RigProperty) => property === 'scaleX' || property === 'scaleY';
const transformOf = (part: RigPart): RigTransform => ({x: part.x, y: part.y, rotation: part.rotation,
  scaleX: part.scaleX, scaleY: part.scaleY, opacity: part.opacity});
const ease = (t: number, curve: RigKeyframe['easing']) => curve === 'linear' ? t : curve === 'ease-out'
  ? 1 - (1 - t) ** 3 : t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;

/** Explicit absolute SVG commands only. Control points bound Bezier curves by their convex hull. */
export const rigPathPoints = (path: string): {x: number; y: number}[] => {
  const tokens = path.match(/[MLQCZ]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?/g) ?? [];
  if (!path || path.length > 2048 || path.replace(/[MLQCZ]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[\s,]/g, '')
    || tokens[0] !== 'M') return fail('path must contain explicit absolute M/L/Q/C/Z commands');
  const points: {x: number; y: number}[] = [];
  let i = 0;
  let commands = 0;
  while (i < tokens.length) {
    if (++commands > 128) return fail('path exceeds 128 commands');
    const command = tokens[i++];
    const arity = ({M: 2, L: 2, Q: 4, C: 6, Z: 0} as Record<string, number>)[command];
    if (arity === undefined || i + arity > tokens.length) return fail('invalid path command');
    for (let offset = 0; offset < arity; offset += 2) {
      const x = Number(tokens[i++]);
      const y = Number(tokens[i++]);
      if (!finite(x, 256) || !finite(y, 256)) return fail('path coordinate outside ±256');
      points.push({x, y});
    }
  }
  if (!points.length) return fail('empty path');
  return points;
};

const union = (boxes: Bounds[]): Bounds => ({left: Math.min(...boxes.map((b) => b.left)),
  top: Math.min(...boxes.map((b) => b.top)), right: Math.max(...boxes.map((b) => b.right)),
  bottom: Math.max(...boxes.map((b) => b.bottom))});
const zeroBounds = (): Bounds => ({left: 0, top: 0, right: 0, bottom: 0});
const shapeBounds = (shape: RigShape): Bounds => {
  const stroke = shape.stroke === 'none' ? 0 : shape.strokeWidth / 2;
  let box: Bounds;
  if (shape.kind === 'path') {
    const points = rigPathPoints(shape.path);
    box = {left: Math.min(...points.map((p) => p.x)), top: Math.min(...points.map((p) => p.y)),
      right: Math.max(...points.map((p) => p.x)), bottom: Math.max(...points.map((p) => p.y))};
  } else if (shape.kind === 'ellipse') {
    box = {left: shape.x - shape.width / 2, top: shape.y - shape.height / 2,
      right: shape.x + shape.width / 2, bottom: shape.y + shape.height / 2};
  } else box = {left: shape.x, top: shape.y, right: shape.x + shape.width, bottom: shape.y + shape.height};
  return {left: box.left - stroke, top: box.top - stroke, right: box.right + stroke, bottom: box.bottom + stroke};
};

/** Weighted harmonic PCHIP tangent, expressed as the distance travelled in this segment's width.
 * Log ratios avoid overflow for valid, extremely uneven key times. The sign test preserves extrema
 * and flat spans; a single performance rests at its endpoints, while repeats share one seam tangent. */
const smoothTangent = (keys: RigKeyframe[], index: number, span: number, repeated: boolean) => {
  const last = keys.length - 1;
  if (!repeated && (index === 0 || index === last)) return 0;
  const before = index === 0 || index === last ? last : index;
  const after = index === 0 || index === last ? 1 : index + 1;
  const beforeWidth = keys[before].at - keys[before - 1].at;
  const afterWidth = keys[after].at - keys[after - 1].at;
  const beforeDelta = keys[before].value - keys[before - 1].value;
  const afterDelta = keys[after].value - keys[after - 1].value;
  if (!beforeDelta || !afterDelta || Math.sign(beforeDelta) !== Math.sign(afterDelta)) return 0;
  const widthScale = Math.max(beforeWidth, afterWidth);
  const a = beforeWidth / widthScale; const b = afterWidth / widthScale;
  const beforeWeight = (2 * b + a) / (3 * (a + b));
  const beforeSlope = Math.log(Math.abs(beforeDelta)) - Math.log(beforeWidth);
  const afterSlope = Math.log(Math.abs(afterDelta)) - Math.log(afterWidth);
  const smallerSlope = Math.min(beforeSlope, afterSlope);
  const divisor = beforeWeight * Math.exp(smallerSlope - beforeSlope)
    + (1 - beforeWeight) * Math.exp(smallerSlope - afterSlope);
  return Math.sign(beforeDelta) * Math.exp(smallerSlope + Math.log(span) - Math.log(divisor));
};

const sample = (keyframes: RigKeyframe[], at: number, repeated: boolean) => {
  if (at <= 0) return keyframes[0].value;
  if (at >= 1) return keyframes[keyframes.length - 1].value;
  const index = keyframes.findIndex((key) => key.at >= at);
  const before = keyframes[index - 1];
  const after = keyframes[index];
  if (after.easing === 'smooth') {
    const width = after.at - before.at;
    const t = (at - before.at) / width;
    const startTangent = smoothTangent(keyframes, index - 1, width, repeated);
    const endTangent = smoothTangent(keyframes, index, width, repeated);
    const value = (2 * t ** 3 - 3 * t ** 2 + 1) * before.value
      + (t ** 3 - 2 * t ** 2 + t) * startTangent
      + (-2 * t ** 3 + 3 * t ** 2) * after.value + (t ** 3 - t ** 2) * endTangent;
    // The shape-preserving tangents already prevent overshoot; clamp floating-point roundoff only.
    return Math.max(Math.min(before.value, after.value), Math.min(Math.max(before.value, after.value), value));
  }
  const t = ease((at - before.at) / (after.at - before.at), after.easing);
  return before.value * (1 - t) + after.value * t;
};

/** Every seek reconstructs the same held pose; neither previous render nor elapsed wall time is used. */
export const rigPoseAtFrame = (rig: PreparedRig, frame: number): RigPose => {
  const pose = Object.fromEntries(rig.definition.parts.map((part) => [part.id, transformOf(part)]));
  for (const {performance, clip, initial} of rig.performances) {
    if (frame < performance.from) continue;
    const progress = clamp((frame - performance.from) / performance.durationInFrames);
    const phase = progress >= 1 ? 1 : progress * performance.repeat % 1;
    for (const track of clip.tracks) {
      const value = sample(track.keyframes, phase, performance.repeat > 1);
      const start = initial[track.partId][track.property];
      pose[track.partId][track.property] = scaled(track.property) ? start * value : start + value;
    }
  }
  return pose;
};

const validateDefinition = (definition: CustomRig) => {
  if (!validId(definition.id) || !definition.parts.length || definition.parts.length > 32 || definition.clips.length > 12) return fail('rig complexity limit');
  const parts = new Map(definition.parts.map((part) => [part.id, part]));
  if (parts.size !== definition.parts.length || parts.has('__proto__') || parts.has('constructor') || parts.has('prototype')) {
    return fail('duplicate or reserved part id');
  }
  let shapeCount = 0;
  for (const part of definition.parts) {
    if (!validId(part.id) || part.parentId === part.id || (part.parentId && !parts.has(part.parentId))) return fail('invalid parent reference');
    let depth = 0;
    let ancestor: RigPart | undefined = part;
    while (ancestor) {
      if (++depth > 8) return fail('cyclic hierarchy or depth greater than 8');
      ancestor = parts.get(ancestor.parentId);
    }
    if (!finite(part.x, 256) || !finite(part.y, 256) || !finite(part.rotation, 3600)
      || !finite(part.opacity) || part.opacity < 0 || part.opacity > 1
      || ![part.scaleX, part.scaleY].every((n) => finite(n) && n >= 0.1 && n <= 4)) return fail('invalid base transform');
    shapeCount += part.shapes.length;
    if (part.shapes.length > 8) return fail('more than eight shapes in one part');
    for (const shape of part.shapes) {
      if (!['ellipse', 'rect', 'path'].includes(shape.kind) || !COLOR.test(shape.fill) || !COLOR.test(shape.stroke)
        || !finite(shape.x, 256) || !finite(shape.y, 256)
        || ![shape.width, shape.height].every((n) => finite(n) && n >= 0 && n <= 512)
        || !finite(shape.radius, 256) || shape.radius < 0 || !finite(shape.strokeWidth, 12) || shape.strokeWidth < 0) {
        return fail('invalid shape');
      }
      if (shape.kind === 'path') {
        rigPathPoints(shape.path);
        if ([shape.x, shape.y, shape.width, shape.height, shape.radius].some((n) => n !== 0)) return fail('path has unused geometry fields');
      } else if (shape.path !== '' || shape.width <= 0 || shape.height <= 0
        || (shape.kind === 'ellipse' && shape.radius !== 0)
        || (shape.kind === 'rect' && shape.radius > Math.min(shape.width, shape.height) / 2)) return fail('invalid primitive geometry');
    }
  }
  if (!shapeCount) return fail('rig has no shapes');
  const clips = new Set<string>();
  for (const clip of definition.clips) {
    if (!validId(clip.id) || clips.has(clip.id) || !clip.tracks.length || clip.tracks.length > 32) return fail('invalid clip');
    clips.add(clip.id);
    const channels = new Set<string>();
    for (const track of clip.tracks) {
      const channel = `${track.partId}:${track.property}`;
      if (!parts.has(track.partId) || !PROPERTIES.includes(track.property) || channels.has(channel)) return fail('invalid track channel');
      channels.add(channel);
      if (track.keyframes.length < 2 || track.keyframes.length > 16 || track.keyframes[0].at !== 0
        || track.keyframes.at(-1)!.at !== 1 || track.keyframes[0].value !== (scaled(track.property) ? 1 : 0)) return fail('invalid track endpoints');
      if (track.keyframes.some((key) => key.easing === 'smooth')
        && !track.keyframes.every((key) => key.easing === 'smooth')) return fail('smooth easing must apply to the whole track');
      track.keyframes.forEach((key, index) => {
        const limit = track.property === 'rotation' ? 720 : track.property === 'opacity' ? 1 : scaled(track.property) ? 4 : 256;
        if (!finite(key.at) || key.at < 0 || key.at > 1 || (index > 0 && key.at <= track.keyframes[index - 1].at)
          || !finite(key.value, limit) || (scaled(track.property) && key.value < 0.1)
          || !['linear', 'ease-in-out', 'ease-out', 'smooth'].includes(key.easing)) return fail('invalid keyframe');
      });
    }
  }
};

const productRange = (a: Range, b: Range): Range => {
  const values = [a[0] * b[0], a[0] * b[1], a[1] * b[0], a[1] * b[1]];
  return [Math.min(...values), Math.max(...values)];
};
/** Exact extrema of a*cos(angle)+b*sin(angle), including turning points between any two frames. */
const rotatedCoordinateRange = (a: number, b: number, rotation: Range): Range => {
  const radius = Math.hypot(a, b);
  const span = rotation[1] - rotation[0];
  if (span >= 360) return [-radius, radius];
  const from = rotation[0] % 360 * Math.PI / 180;
  const to = from + span * Math.PI / 180;
  const value = (angle: number) => a * Math.cos(angle) + b * Math.sin(angle);
  const candidates = [value(from), value(to)];
  const turning = Math.atan2(b, a);
  for (let turn = Math.ceil((from - turning) / Math.PI); turn <= Math.floor((to - turning) / Math.PI); turn++) {
    candidates.push(value(turning + turn * Math.PI));
  }
  return [Math.min(...candidates), Math.max(...candidates)];
};

/** Reuse the same analytic interval for a generated actor's authored whole-object rotation. */
export const rotatedRigExtents = (extents: [number, number], rotation: [number, number]) => {
  const corners = [-extents[0], extents[0]].flatMap((x) => [-extents[1], extents[1]].map((y) => ({
    x: rotatedCoordinateRange(x, -y, rotation), y: rotatedCoordinateRange(y, x, rotation),
  })));
  return {x: Math.max(...corners.flatMap((point) => point.x.map(Math.abs))),
    y: Math.max(...corners.flatMap((point) => point.y.map(Math.abs)))};
};

const transformedBounds = (box: Bounds, range: TransformRanges, restrictedRotation: boolean): Bounds => {
  const x = productRange([box.left, box.right], range.scaleX);
  const y = productRange([box.top, box.bottom], range.scaleY);
  let rotated: Bounds;
  if (range.rotation[0] !== range.rotation[1] && !restrictedRotation) {
    const radius = Math.hypot(Math.max(Math.abs(x[0]), Math.abs(x[1])), Math.max(Math.abs(y[0]), Math.abs(y[1])));
    rotated = {left: -radius, top: -radius, right: radius, bottom: radius};
  } else {
    const corners = x.flatMap((px) => y.map((py) => ({x: rotatedCoordinateRange(px, -py, range.rotation),
      y: rotatedCoordinateRange(py, px, range.rotation)})));
    rotated = {left: Math.min(...corners.map((p) => p.x[0])), right: Math.max(...corners.map((p) => p.x[1])),
      top: Math.min(...corners.map((p) => p.y[0])), bottom: Math.max(...corners.map((p) => p.y[1]))};
  }
  return {left: rotated.left + range.x[0], right: rotated.right + range.x[1],
    top: rotated.top + range.y[0], bottom: rotated.bottom + range.y[1]};
};

/** Directional complete-motion bounds under the actor's outer transform. Keeping their offset
 * avoids reserving a mirror image of a long arm or stem on the empty side of its origin. */
export const transformedRigBounds = (bounds: RigBounds, size: Range, rotation: Range): RigBounds => {
  const transformed = transformedBounds(bounds, {x: [0, 0], y: [0, 0], rotation,
    scaleX: size, scaleY: size, opacity: [1, 1]}, true);
  const padding = 3 * Math.max(...size);
  return {left: transformed.left - padding, right: transformed.right + padding,
    top: transformed.top - padding, bottom: transformed.bottom + padding};
};

const halfExtents = (bounds: Bounds): [number, number] => [Math.max(Math.abs(bounds.left), Math.abs(bounds.right)),
  Math.max(Math.abs(bounds.top), Math.abs(bounds.bottom))];

/** Interval composition bounds all parent/child combinations and held poses; it never samples frames.
 * Restricted angle bounds frame small gestures closely. Full circles retain the shared validation limit. */
const rigBounds = (rig: PreparedRig, restrictedRotation = false): Bounds => {
  const ranges = new Map(rig.definition.parts.map((part) => [part.id,
    Object.fromEntries(PROPERTIES.map((property) => [property, [part[property], part[property]]])) as TransformRanges]));
  for (const {clip, initial} of rig.performances) for (const track of clip.tracks) {
    const start = initial[track.partId][track.property];
    const values = track.keyframes.map(({value}) => scaled(track.property) ? start * value : start + value);
    const previous = ranges.get(track.partId)![track.property];
    ranges.get(track.partId)![track.property] = [Math.min(previous[0], ...values), Math.max(previous[1], ...values)];
  }
  const visit = (part: RigPart): Bounds => {
    const own = part.shapes.map(shapeBounds);
    const children = rig.definition.parts.filter((child) => child.parentId === part.id).map(visit);
    const boxes = [...own, ...children];
    return transformedBounds(boxes.length ? union(boxes) : zeroBounds(), ranges.get(part.id)!, restrictedRotation);
  };
  const bounds = union(rig.definition.parts.filter((part) => !part.parentId).map(visit));
  const extents = halfExtents(bounds);
  if (!extents.every((n) => finite(n, 800))) return fail('derived motion envelope exceeds 800 units');
  return bounds;
};

export const prepareRig = (definition: CustomRig, performances: RigPerformance[]): PreparedRig => {
  validateDefinition(definition);
  if (performances.length > 48) return fail('too many performances');
  const prepared: PreparedRig = {definition, performances: [], extents: [0, 0], bounds: zeroBounds()};
  for (const performance of [...performances].sort((a, b) => a.from - b.from || a.clipId.localeCompare(b.clipId))) {
    const clip = definition.clips.find((candidate) => candidate.id === performance.clipId);
    if (!clip || !finite(performance.from) || !finite(performance.durationInFrames) || performance.durationInFrames <= 0
      || !Number.isInteger(performance.repeat) || performance.repeat < 1 || performance.repeat > 12) return fail('invalid performance');
    if (performance.repeat > 1 && clip.tracks.some((track) => track.keyframes[0].value !== track.keyframes.at(-1)!.value)) {
      return fail('repeated clip must return every channel to its initial value');
    }
    if (performance.repeat > 1 && performance.durationInFrames < performance.repeat * 4) {
      return fail('allow at least four frames per repeated cycle');
    }
    for (const previous of prepared.performances) {
      if (previous.performance.from + previous.performance.durationInFrames <= performance.from) continue;
      if (previous.clip.tracks.some((a) => clip.tracks.some((b) => a.partId === b.partId && a.property === b.property))) {
        return fail('overlapping performances write the same channel');
      }
    }
    const initial = rigPoseAtFrame(prepared, performance.from);
    for (const track of clip.tracks) {
      if (track.property === 'opacity' && track.keyframes.some(({value}) => {
        const opacity = initial[track.partId].opacity + value;
        return opacity < 0 || opacity > 1;
      })) return fail('accumulated opacity must remain between 0 and 1');
    }
    prepared.performances.push({performance, clip, initial});
  }
  // Keep the conservative input safety contract identical to the Python validator. Framing can use
  // tighter analytic angle intervals without allowing previously rejected oversized rigs through.
  rigBounds(prepared);
  prepared.bounds = rigBounds(prepared, true);
  prepared.extents = halfExtents(prepared.bounds);
  return prepared;
};

const multiply = (a: RigMatrix, b: RigMatrix): RigMatrix => [a[0] * b[0] + a[2] * b[1],
  a[1] * b[0] + a[3] * b[1], a[0] * b[2] + a[2] * b[3], a[1] * b[2] + a[3] * b[3],
  a[0] * b[4] + a[2] * b[5] + a[4], a[1] * b[4] + a[3] * b[5] + a[5]];
const matrixOf = (pose: RigTransform): RigMatrix => {
  const angle = pose.rotation % 360 * Math.PI / 180;
  return [Math.cos(angle) * pose.scaleX, Math.sin(angle) * pose.scaleX,
    -Math.sin(angle) * pose.scaleY, Math.cos(angle) * pose.scaleY, pose.x, pose.y];
};

/** Exactly the painted picture, in SVG order. Hidden/empty parts and unused clip definitions are absent. */
export const rigPictureAtFrame = (rig: PreparedRig, frame: number) => {
  const pose = rigPoseAtFrame(rig, frame);
  const picture: {matrix: RigMatrix; opacity: number; shape: RigShape}[] = [];
  const visit = (part: RigPart, parent: RigMatrix, parentOpacity: number) => {
    const matrix = multiply(parent, matrixOf(pose[part.id]));
    const opacity = parentOpacity * clamp(pose[part.id].opacity);
    if (opacity <= 1e-6) return;
    for (const shape of part.shapes) if (shape.fill !== 'none' || (shape.stroke !== 'none' && shape.strokeWidth > 0)) {
      picture.push({matrix, opacity, shape});
    }
    for (const child of rig.definition.parts) if (child.parentId === part.id) visit(child, matrix, opacity);
  };
  for (const root of rig.definition.parts) if (!root.parentId) visit(root, [1, 0, 0, 1, 0, 0], 1);
  return picture;
};
