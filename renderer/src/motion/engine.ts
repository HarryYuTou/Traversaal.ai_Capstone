import type {MotionAction, MotionActivity, MotionContact, MotionCue, MotionEasing, MotionEntity, MotionPath, MotionPoint, MotionVisual} from './types';
import {prepareRig, rigPoseAtFrame, type PreparedRig} from './rig';

// All geometry, including orbit radii, is evaluated in these physical SVG coordinates.
export const STAGE_WIDTH = 1200;
export const STAGE_HEIGHT = 500;
export const toStage = ({x, y}: MotionPoint): MotionPoint => ({x: x * STAGE_WIDTH / 100, y: y * STAGE_HEIGHT / 100});
const fromStage = ({x, y}: MotionPoint): MotionPoint => ({x: x * 100 / STAGE_WIDTH, y: y * 100 / STAGE_HEIGHT});
// Weighted endpoints avoid overflowing b - a when valid finite rotation targets have opposite signs.
const mix = (a: number, b: number, t: number) => (1 - t) * a + t * b;
const distance = (a: MotionPoint, b: MotionPoint) => Math.hypot(a.x - b.x, a.y - b.y);
const clamp = (n: number) => Math.max(0, Math.min(1, n));

// Share of a walk spent speeding up, and again slowing down, at its ends.
export const WALK_RAMP = 0.25;
// Distance covered while speed rises smoothly from 0 to 1 over a unit ramp (integral of smoothstep).
const rampDistance = (x: number) => x ** 3 - x ** 4 / 2;

/** Matches the existing renderer's cubic ease-out; constant travel uses linear. A walk eases in and
 * out over WALK_RAMP of its time and keeps one steady pace in between (top speed 1.33x the average,
 * where the cubic ease-in-out peaks at 3x), so feet and distance stay in step without a mid-route lurch. */
export const easing = (t: number, curve: MotionEasing) => {
  const p = clamp(t);
  if (curve === 'linear') return p;
  if (curve === 'ease-out') return 1 - (1 - p) ** 3;
  if (curve === 'walk') {
    const top = 1 / (1 - WALK_RAMP);
    if (p < WALK_RAMP) return top * WALK_RAMP * rampDistance(p / WALK_RAMP);
    if (p > 1 - WALK_RAMP) return 1 - top * WALK_RAMP * rampDistance((1 - p) / WALK_RAMP);
    return top * (p - WALK_RAMP / 2);
  }
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
export type PreparedEntity = {entity: MotionEntity; actions: PreparedAction[]; activities: MotionActivity[]; cues?: MotionCue[];
  rig?: PreparedRig; rigExtents?: [number, number]; contacts?: PreparedContact[]};
export type PreparedContact = {contact: MotionContact; target: PreparedEntity};
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

const rawEntityAtFrame = (prepared: PreparedEntity, frame: number): EntityState =>
  prepared.actions.reduce<EntityState>((state, action) => apply(state, action, frame), {...prepared.entity});

/** A named part's local point follows precisely the same hierarchy as its SVG geometry. */
const anchorVectorAtFrame = (prepared: PreparedEntity, partId: string, point: MotionPoint,
  frame: number, state: EntityState): MotionPoint => {
  let local = {...point};
  if (partId && prepared.rig) {
    const pose = rigPoseAtFrame(prepared.rig, frame);
    let part = prepared.rig.definition.parts.find((candidate) => candidate.id === partId);
    while (part) {
      const transform = pose[part.id];
      const angle = transform.rotation % 360 * Math.PI / 180;
      const x = local.x * transform.scaleX; const y = local.y * transform.scaleY;
      local = {x: transform.x + x * Math.cos(angle) - y * Math.sin(angle),
        y: transform.y + x * Math.sin(angle) + y * Math.cos(angle)};
      part = prepared.rig.definition.parts.find((candidate) => candidate.id === part!.parentId);
    }
  }
  const angle = state.rotation % 360 * Math.PI / 180;
  return {x: state.size * (local.x * Math.cos(angle) - local.y * Math.sin(angle)),
    y: state.size * (local.x * Math.sin(angle) + local.y * Math.cos(angle))};
};

type StateCache = Map<PreparedEntity, Map<number, EntityState>>;
const solveEntity = (prepared: PreparedEntity, frame: number, cache: StateCache): EntityState => {
  const cached = cache.get(prepared)?.get(frame);
  if (cached) return cached;
  const raw = rawEntityAtFrame(prepared, frame);
  let offset = {x: 0, y: 0};
  for (const {contact, target} of prepared.contacts ?? []) {
    if (frame < contact.from) break;
    const end = contact.from + contact.durationInFrames;
    const at = Math.min(frame, end);
    const sourceState = at === frame ? raw : rawEntityAtFrame(prepared, at);
    const sourcePoint = anchorVectorAtFrame(prepared, contact.partId, contact, at, sourceState);
    const targetState = solveEntity(target, at, cache);
    const targetPoint = anchorVectorAtFrame(target, contact.targetPartId,
      {x: contact.targetX, y: contact.targetY}, at, targetState);
    const sourceOrigin = toStage(sourceState); const targetOrigin = toStage(targetState);
    const solved = {x: targetOrigin.x + targetPoint.x - sourcePoint.x - sourceOrigin.x,
      y: targetOrigin.y + targetPoint.y - sourcePoint.y - sourceOrigin.y};
    // Smooth acquisition starts at the unconstrained pose, including the last release offset.
    // The acquisition blend has flat endpoints. Release holds position, without inherited momentum.
    const p = contact.approachFrames === 0 ? 1 : clamp((at - contact.from) / contact.approachFrames);
    const blend = p * p * (3 - 2 * p);
    offset = {x: mix(offset.x, solved.x, blend), y: mix(offset.y, solved.y, blend)};
    if (frame <= end) break;
  }
  const position = toStage(raw);
  const result = {...raw, ...fromStage({x: position.x + offset.x, y: position.y + offset.y})};
  if (!cache.has(prepared)) cache.set(prepared, new Map());
  cache.get(prepared)!.set(frame, result);
  return result;
};

/** Pure random-access evaluation: contact acquisition, following and release never depend on playback order. */
export const entityAtFrame = (prepared: PreparedEntity, frame: number): EntityState =>
  prepared.contacts?.length ? solveEntity(prepared, frame, new Map()) : rawEntityAtFrame(prepared, frame);

export const contactAnchorAtFrame = (prepared: PreparedEntity, partId: string, point: MotionPoint, frame: number) => {
  const state = entityAtFrame(prepared, frame);
  const origin = toStage(state); const local = anchorVectorAtFrame(prepared, partId, point, frame, state);
  return {x: origin.x + local.x, y: origin.y + local.y};
};

const prepareContacts = (entities: PreparedEntity[], contacts: MotionContact[]) => {
  const fail = (message: string): never => {throw new Error(`Invalid contact: ${message}`);};
  if (contacts.length > 24) fail('at most 24 contacts per scene');
  const byId = new Map(entities.map((entity) => [entity.entity.id, entity]));
  const partExists = (entity: PreparedEntity, partId: string) => partId === '' ||
    Boolean(entity.rig?.definition.parts.some((part) => part.id === partId));
  for (const contact of [...contacts].sort((a, b) => a.from - b.from || a.entityId.localeCompare(b.entityId))) {
    const source = byId.get(contact.entityId); const target = byId.get(contact.targetId);
    if (!source || !target || source === target) fail('missing or self-referencing entity');
    if (!partExists(source!, contact.partId) || !partExists(target!, contact.targetPartId)) fail('missing part anchor');
    if (![contact.x, contact.y, contact.targetX, contact.targetY].every((n) => Number.isFinite(n) && Math.abs(n) <= 256)) {
      fail('anchor coordinates must be within ±256');
    }
    if (![contact.from, contact.durationInFrames, contact.approachFrames].every(Number.isSafeInteger)
      || contact.from < 0 || contact.durationInFrames <= 0 || !Number.isFinite(contact.approach)
      || contact.approach < 0 || contact.approach > 0.5 || contact.approachFrames < 0
      || contact.approachFrames > contact.durationInFrames
      || (contact.approach > 0 && contact.approachFrames < 2)
      || (contact.approach === 0 && (contact.approachFrames !== 0 || contact.startLine !== 0 || contact.startOffset !== 0))) {
      fail('invalid acquisition timing');
    }
    const end = contact.from + contact.durationInFrames;
    if (source!.contacts?.some(({contact: before}) => before.from + before.durationInFrames > contact.from)) {
      fail('overlapping contacts on the same source');
    }
    if (source!.actions.some(({action}) => ['move', 'follow-path', 'orbit'].includes(action.kind)
      && action.from < end && action.from + action.durationInFrames > contact.from)) fail('source travel overlaps contact');
    (source!.contacts ??= []).push({contact, target: target!});
  }
  const visited = new Set<PreparedEntity>();
  const visit = (entity: PreparedEntity, stack: Set<PreparedEntity>) => {
    if (stack.has(entity)) fail('cyclic contact dependency');
    if (visited.has(entity)) return;
    const next = new Set(stack).add(entity);
    for (const {target} of entity.contacts ?? []) visit(target, next);
    visited.add(entity);
  };
  for (const entity of entities) visit(entity, new Set());
};

const contactBoundsCache = new WeakMap<PreparedEntity, {left: number; right: number; top: number; bottom: number}>();
/** Exact root positions of every rendered integer frame, including released travel. Local geometry
 * is enclosed separately by analytic rig bounds. No sparse storyboard sample can miss a contact excursion. */
export const contactPositionBounds = (prepared: PreparedEntity) => {
  if (!prepared.contacts?.length) return null;
  const cached = contactBoundsCache.get(prepared); if (cached) return cached;
  const intervals: {from: number; durationInFrames: number}[] = [];
  const visited = new Set<PreparedEntity>();
  const collect = (entity: PreparedEntity) => {
    if (visited.has(entity)) return; visited.add(entity);
    intervals.push(...entity.actions.map(({action}) => action), ...(entity.rig?.performances.map(({performance}) => performance) ?? []));
    for (const {contact, target} of entity.contacts ?? []) {intervals.push(contact); collect(target);}
  };
  collect(prepared);
  if (intervals.some((item) => !Number.isSafeInteger(item.from) || item.from < 0
    || !Number.isSafeInteger(item.durationInFrames) || item.durationInFrames <= 0
    || !Number.isSafeInteger(item.from + item.durationInFrames))) {
    throw new Error('Invalid contact framing interval');
  }
  const start = Math.floor(Math.min(...intervals.map((item) => item.from)));
  const end = Math.ceil(Math.max(...intervals.map((item) => item.from + item.durationInFrames)));
  if (end - start > 100_000) throw new Error('Contact framing exceeds 100000 frames');
  const bounds = {left: Infinity, right: -Infinity, top: Infinity, bottom: -Infinity};
  const includePoint = (point: MotionPoint) => {
    bounds.left = Math.min(bounds.left, point.x); bounds.right = Math.max(bounds.right, point.x);
    bounds.top = Math.min(bounds.top, point.y); bounds.bottom = Math.max(bounds.bottom, point.y);
  };
  const include = (frame: number) => includePoint(toStage(entityAtFrame(prepared, frame)));
  // A scene-initial lock is active before the first rendered frame; its raw ungrounded pose is not content.
  if (start > 0 && !prepared.contacts.some(({contact}) => contact.approach === 0 && contact.from === start)) include(start - 1);
  for (let frame = start; frame <= end; frame++) include(frame);
  // The route is a continuous drawn line even when very short travel samples only its endpoints.
  for (const {action, geometry} of prepared.actions) if (geometry) {
    const solved = toStage(entityAtFrame(prepared, action.from));
    const raw = toStage(rawEntityAtFrame(prepared, action.from));
    for (const point of geometry.points) includePoint({x: point.x + solved.x - raw.x, y: point.y + solved.y - raw.y});
  }
  contactBoundsCache.set(prepared, bounds);
  return bounds;
};

/** Stateless compilation captures the state at every action's start, never at the last rendered frame. */
export const compileMotion = (visual: MotionVisual): MotionProgram => {
  if ((visual.rigs?.length ?? 0) > 6 || (visual.performances?.length ?? 0) > 48) throw new Error('Custom rig scene complexity limit');
  const paths = new Map(visual.paths.map((path) => [path.id, path]));
  const entities = visual.entities.map((entity): PreparedEntity => {
    const prepared: PreparedEntity = {entity, actions: [], cues: (visual.cues ?? [])
      .filter((cue) => cue.entityId === entity.id)
      .sort((a, b) => a.from - b.from || a.kind.localeCompare(b.kind)), activities: (visual.activities ?? [])
      .filter((activity) => activity.entityId === entity.id)
      .sort((a, b) => a.from - b.from || a.kind.localeCompare(b.kind))};
    if (entity.kind === 'custom') {
      const definition = visual.rigs?.find((rig) => rig.id === entity.rigId);
      if (!definition) throw new Error(`Custom entity ${entity.id} references missing rig ${entity.rigId ?? ''}`);
      prepared.rig = prepareRig(definition, (visual.performances ?? []).filter((item) => item.entityId === entity.id));
      prepared.rigExtents = prepared.rig.extents;
    }
    const actions = visual.actions.filter((action) => action.entityId === entity.id)
      .sort((a, b) => a.from - b.from || a.kind.localeCompare(b.kind) || a.pathId.localeCompare(b.pathId));
    for (const action of actions) {
      const initial = rawEntityAtFrame(prepared, action.from);
      const path = paths.get(action.pathId);
      prepared.actions.push({action, initial,
        geometry: action.kind === 'follow-path' && path ? pathGeometry(path, initial) : undefined});
    }
    return prepared;
  });
  prepareContacts(entities, visual.contacts ?? []);
  return {entities, paths: visual.paths};
};

/** Include a connecting segment when a follow-path starts away from its declared first point. */
export const displayedPaths = (program: MotionProgram, frame: number) => program.paths.flatMap((path) => {
  const uses = program.entities.flatMap((entity) => entity.actions.map((prepared) => {
    if (!prepared.geometry || !entity.contacts?.length) return prepared;
    const from = prepared.action.from;
    const solved = toStage(entityAtFrame(entity, from)); const raw = toStage(rawEntityAtFrame(entity, from));
    const points = prepared.geometry.points.map((point) => ({x: point.x + solved.x - raw.x, y: point.y + solved.y - raw.y}));
    return {...prepared, geometry: {...prepared.geometry, points,
      d: points.map((point, i) => `${i ? 'L' : 'M'}${point.x.toFixed(3)},${point.y.toFixed(3)}`).join(' ')}};
  }))
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
