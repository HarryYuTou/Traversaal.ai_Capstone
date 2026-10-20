import type {MotionAction, MotionActivity, MotionEasing, MotionEntity, MotionPath, MotionPoint, MotionVisual} from './types';

// All geometry, including orbit radii, is evaluated in these physical SVG coordinates.
export const STAGE_WIDTH = 1200;
export const STAGE_HEIGHT = 500;
export const toStage = ({x, y}: MotionPoint): MotionPoint => ({x: x * STAGE_WIDTH / 100, y: y * STAGE_HEIGHT / 100});
const fromStage = ({x, y}: MotionPoint): MotionPoint => ({x: x * 100 / STAGE_WIDTH, y: y * 100 / STAGE_HEIGHT});
// Weighted endpoints avoid overflowing b - a when valid finite rotation targets have opposite signs.
const mix = (a: number, b: number, t: number) => (1 - t) * a + t * b;
const distance = (a: MotionPoint, b: MotionPoint) => Math.hypot(a.x - b.x, a.y - b.y);
const clamp = (n: number) => Math.max(0, Math.min(1, n));

/** Matches the existing renderer's cubic ease-out; constant travel uses linear. */
export const easing = (t: number, curve: MotionEasing) => {
  const p = clamp(t);
  if (curve === 'linear') return p;
  if (curve === 'ease-out') return 1 - (1 - p) ** 3;
  return p < 0.5 ? 4 * p ** 3 : 1 - (-2 * p + 2) ** 3 / 2;
};

export type PathGeometry = {points: MotionPoint[]; lengths: number[]; length: number; d: string};

/** One sampled geometry drives both the SVG route and distance-based motion along it. */
export const pathGeometry = (path: MotionPath, start?: MotionPoint): PathGeometry => {
  const control = path.points.map(toStage);
  const startMatches = !start || !control.length || distance(toStage(start), control[0]) <= 0.001;
  if (path.closed && control.length > 1 && distance(control[0], control[control.length - 1]) > 0.001) {
    control.push({...control[0]});
  }
  if (start) {
    const at = toStage(start);
    if (!control.length || distance(at, control[0]) > 0.001) control.unshift(at);
  }
  const points: MotionPoint[] = [];
  if (path.curved && control.length > 2) {
    for (let i = 0; i < control.length - 1; i++) {
      const p0 = i === 0 && path.closed && startMatches ? control[control.length - 2] : control[Math.max(0, i - 1)];
      const p1 = control[i];
      const p2 = control[i + 1];
      const p3 = i === control.length - 2 && path.closed && startMatches ? control[1] : control[Math.min(control.length - 1, i + 2)];
      for (let j = 0; j < 32; j++) {
        const t = j / 32;
        const at = (axis: 'x' | 'y') => 0.5 * ((2 * p1[axis]) + (-p0[axis] + p2[axis]) * t
          + (2 * p0[axis] - 5 * p1[axis] + 4 * p2[axis] - p3[axis]) * t * t
          + (-p0[axis] + 3 * p1[axis] - 3 * p2[axis] + p3[axis]) * t * t * t);
        points.push({x: at('x'), y: at('y')});
      }
    }
    points.push(control[control.length - 1]);
  } else points.push(...control);
  if (!points.length) points.push({x: 0, y: 0});
  const lengths = [0];
  for (let i = 1; i < points.length; i++) lengths.push(lengths[i - 1] + distance(points[i - 1], points[i]));
  return {points, lengths, length: lengths[lengths.length - 1],
    d: points.map((point, i) => `${i ? 'L' : 'M'}${point.x.toFixed(3)},${point.y.toFixed(3)}`).join(' ')};
};

export const pointOnPath = (geometry: PathGeometry, progress: number): MotionPoint => {
  const {points, lengths, length} = geometry;
  if (length === 0) return {...points[0]};
  const target = clamp(progress) * length;
  let hi = lengths.length - 1;
  let lo = 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (lengths[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  const index = Math.max(1, lo);
  const fraction = (target - lengths[index - 1]) / (lengths[index] - lengths[index - 1] || 1);
  return {x: mix(points[index - 1].x, points[index].x, fraction), y: mix(points[index - 1].y, points[index].y, fraction)};
};

export type EntityState = Pick<MotionEntity, 'x' | 'y' | 'size' | 'rotation' | 'opacity' | 'value'>;
export type PreparedAction = {action: MotionAction; initial: EntityState; geometry?: PathGeometry};
export type PreparedEntity = {entity: MotionEntity; actions: PreparedAction[]; activities: MotionActivity[]};
export type MotionProgram = {entities: PreparedEntity[]; paths: MotionPath[]};

const apply = (state: EntityState, prepared: PreparedAction, frame: number): EntityState => {
  const {action, initial, geometry} = prepared;
  if (frame < action.from) return state;
  const p = easing((frame - action.from) / Math.max(1, action.durationInFrames), action.easing);
  switch (action.kind) {
    case 'move': return {...state, x: mix(initial.x, action.x, p), y: mix(initial.y, action.y, p)};
    case 'follow-path': return geometry ? {...state, ...fromStage(pointOnPath(geometry, p))} : state;
    case 'orbit': {
      const center = toStage(action);
      const point = toStage(initial);
      const angle = ((action.value * p) % 360) * Math.PI / 180;
      const dx = point.x - center.x;
      const dy = point.y - center.y;
      return {...state, ...fromStage({x: center.x + dx * Math.cos(angle) - dy * Math.sin(angle),
        y: center.y + dx * Math.sin(angle) + dy * Math.cos(angle)})};
    }
    case 'opacity': return {...state, opacity: mix(initial.opacity, action.value, p)};
    case 'scale': return {...state, size: mix(initial.size, action.value, p)};
    case 'rotate': return {...state, rotation: mix(initial.rotation, action.value, p)};
    case 'value': return {...state, value: mix(initial.value, action.value, p)};
  }
};

export const entityAtFrame = (prepared: PreparedEntity, frame: number): EntityState =>
  prepared.actions.reduce<EntityState>((state, action) => apply(state, action, frame), {...prepared.entity});

/** Stateless compilation captures the state at every action's start, never at the last rendered frame. */
export const compileMotion = (visual: MotionVisual): MotionProgram => {
  const paths = new Map(visual.paths.map((path) => [path.id, path]));
  const entities = visual.entities.map((entity): PreparedEntity => {
    const prepared: PreparedEntity = {entity, actions: [], activities: (visual.activities ?? [])
      .filter((activity) => activity.entityId === entity.id)
      .sort((a, b) => a.from - b.from || a.kind.localeCompare(b.kind))};
    const actions = visual.actions.filter((action) => action.entityId === entity.id)
      .sort((a, b) => a.from - b.from || a.kind.localeCompare(b.kind) || a.pathId.localeCompare(b.pathId));
    for (const action of actions) {
      const initial = entityAtFrame(prepared, action.from);
      const path = paths.get(action.pathId);
      prepared.actions.push({action, initial,
        geometry: action.kind === 'follow-path' && path ? pathGeometry(path, initial) : undefined});
    }
    return prepared;
  });
  return {entities, paths: visual.paths};
};

/** Include a connecting segment when a follow-path starts away from its declared first point. */
export const displayedPaths = (program: MotionProgram, frame: number) => program.paths.flatMap((path) => {
  const uses = program.entities.flatMap((entity) => entity.actions)
    .filter(({action, geometry}) => action.pathId === path.id && geometry)
    .sort((a, b) => a.action.from - b.action.from);
  if (!uses.length) return [{key: path.id, path, geometry: pathGeometry(path), from: 0, progress: 1}];
  // A shared path may have different connecting segments for different actors. Keep every geometry
  // separate so one actor starting later cannot change another actor's visible trajectory.
  const groups = new Map<string, PreparedAction[]>();
  for (const use of uses) {
    const key = use.geometry!.d;
    groups.set(key, [...(groups.get(key) ?? []), use]);
  }
  return [...groups.values()].map((group, index) => ({key: `${path.id}-${index}`, path,
    geometry: group[0].geometry!, from: group[0].action.from,
    progress: Math.max(...group.map(({action}) => easing((frame - action.from) / Math.max(1, action.durationInFrames), action.easing)))}));
});
