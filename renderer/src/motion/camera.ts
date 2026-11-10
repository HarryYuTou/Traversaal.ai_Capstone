import {contactPositionBounds, pathGeometry, STAGE_HEIGHT, STAGE_WIDTH, toStage, type MotionProgram} from './engine';
import {entityExtents, entityHalfExtents, labelMetrics, type IllustrationLook} from './metrics';
import {rotatedRigExtents, transformedRigBounds} from './rig';

export type StageViewport = {x: number; y: number; width: number; height: number};
export const BASE_VIEWPORT: StageViewport = {x: 0, y: 0, width: STAGE_WIDTH, height: STAGE_HEIGHT};

/** Physical video rectangle reserved for actors. SVG clipping is the final title/caption safety guard. */
export const motionStageRect = (width: number, height: number) => ({
  x: width * 90 / 1920, y: height * 205 / 1080,
  width: width * 1740 / 1920, height: height * 655 / 1080,
});

/**
 * Fit once for the complete scene, not for the current frame. Curves use the same sampled geometry as
 * travel; orbits include the entire physical circle. Max scale and rotation envelopes are conservative
 * even when property tracks run concurrently. Label margins are independent of actor scale.
 */
export const fitMotionViewport = (program: MotionProgram, options: {
  fitContent?: boolean; minimumWidth?: number; minimumHeight?: number; labelsBeside?: boolean;
  /** Frame only where things stand (and the walks between those places): departures may leave the shot. */
  settledOnly?: boolean;
  look?: IllustrationLook;
  /** Legacy process framing ignores almost transparent cast; authored custom scenes include every painted actor. */
  visibilityThreshold?: number;
} = {}): StageViewport => {
  let left = options.fitContent ? Infinity : 0;
  let top = options.fitContent ? Infinity : 0;
  let right = options.fitContent ? -Infinity : STAGE_WIDTH;
  let bottom = options.fitContent ? -Infinity : STAGE_HEIGHT;
  const include = (x: number, y: number, rx: number, ry: number) => {
    left = Math.min(left, x - rx); right = Math.max(right, x + rx);
    top = Math.min(top, y - ry); bottom = Math.max(bottom, y + ry);
  };
  // A departure is a walk that ends exactly as the walker finishes fading out.
  const departures = new Set(program.entities.flatMap(({actions}) => actions
    .filter(({action}) => ['move', 'follow-path'].includes(action.kind) && actions.some(({action: fade}) =>
      fade.kind === 'opacity' && fade.value <= 0.05
      && fade.from + fade.durationInFrames === action.from + action.durationInFrames))
    .map(({action}) => action)));
  const settled = (action: (typeof program.entities)[number]['actions'][number]['action']) =>
    !options.settledOnly || !departures.has(action);
  for (const path of program.paths) {
    if (options.settledOnly) continue;
    for (const point of pathGeometry(path).points) include(point.x, point.y, 4, 4);
  }
  for (const prepared of program.entities) {
    const {entity, actions} = prepared;
    // A never-visible future actor must not pull a process shot toward its off-stage spawn point.
    const visibilityThreshold = options.visibilityThreshold ?? 0.05;
    if (options.fitContent && entity.opacity <= visibilityThreshold && !actions.some(({action}) =>
      action.kind === 'opacity' && action.value > visibilityThreshold)) continue;
    const size = Math.max(entity.size, ...actions.filter(({action}) => action.kind === 'scale').map(({action}) => action.value));
    let extent = entityHalfExtents(entity.kind, size, entity.rotation, options.look, prepared.rigExtents);
    if (actions.some(({action}) => action.kind === 'rotate') && !['moon', 'planet'].includes(entity.kind)) {
      if (entity.kind === 'custom' && prepared.rigExtents) {
        const rotations = [entity.rotation, ...actions.filter(({action}) => action.kind === 'rotate').map(({action}) => action.value)];
        const rotated = rotatedRigExtents(prepared.rigExtents, [Math.min(...rotations), Math.max(...rotations)]);
        extent = {x: (rotated.x + 3) * size, y: (rotated.y + 3) * size};
      } else {
        const [w, h] = entityExtents(entity.kind, options.look, prepared.rigExtents);
        const radius = (Math.hypot(w, h) + 3) * size;
        extent = {x: radius, y: radius};
      }
    }
    const label = entity.label ? labelMetrics(entity.label, options.look === 'sketch' ? 1.25 : 1) : null;
    const rx = Math.max(extent.x, label ? label.width / 2 : 0) + 12;
    const ry = extent.y + (label ? label.height + 27 : 0) + 12;
    const sizes = [entity.size, ...actions.filter(({action}) => action.kind === 'scale').map(({action}) => action.value)];
    const rotations = [entity.rotation, ...actions.filter(({action}) => action.kind === 'rotate').map(({action}) => action.value)];
    const custom = entity.kind === 'custom' && prepared.rig
      ? transformedRigBounds(prepared.rig.bounds, [Math.min(...sizes), size], [Math.min(...rotations), Math.max(...rotations)]) : null;
    // Reserve text above/below the actual body, without mirroring asymmetric geometry about its pivot.
    const local = custom ? {left: Math.min(custom.left, label ? -label.width / 2 : Infinity) - 12,
      right: Math.max(custom.right, label ? label.width / 2 : -Infinity) + 12,
      top: Math.min(custom.top, label ? 0 : Infinity) - (label ? label.height + 27 : 0) - 12,
      bottom: Math.max(custom.bottom, label ? 0 : -Infinity) + (label ? label.height + 27 : 0) + 12} : null;
    const includeActor = (x: number, y: number) => {
      if (!local) {include(x, y, rx, ry); return;}
      left = Math.min(left, x + local.left); right = Math.max(right, x + local.right);
      top = Math.min(top, y + local.top); bottom = Math.max(bottom, y + local.bottom);
    };
    const contactBounds = contactPositionBounds(prepared);
    if (contactBounds) {
      includeActor(contactBounds.left, contactBounds.top);
      includeActor(contactBounds.right, contactBounds.bottom);
      // The constraint owns this actor's position. Its raw authored position may never be shown.
      continue;
    }
    const initial = toStage(entity);
    // An arrival's off-stage spawn point is not a place anyone stands.
    if (!options.settledOnly || entity.opacity > 0.05) includeActor(initial.x, initial.y);
    // Room for a label beside a fixed station, the side process scenes prefer (labels.ts).
    if (options.labelsBeside && label && !actions.some(({action}) => ['move', 'follow-path', 'orbit'].includes(action.kind))) {
      include(initial.x + (custom?.right ?? extent.x) + 16 + label.width / 2, initial.y, label.width / 2 + 12, label.height / 2 + 12);
    }
    for (const {action, initial: start, geometry} of actions) {
      if (!settled(action)) continue;
      const at = toStage(start);
      // Settled framing takes positions only from movement: a fade-out starts mid-departure, and an
      // arrival starts at its invisible spawn point.
      const positional = ['move', 'follow-path', 'orbit'].includes(action.kind);
      if (!options.settledOnly || (positional && start.opacity > 0.05)) includeActor(at.x, at.y);
      if (action.kind === 'move') {
        const end = toStage(action);
        includeActor(end.x, end.y);
      } else if (geometry) {
        for (const point of geometry.points) includeActor(point.x, point.y);
      } else if (action.kind === 'orbit') {
        const center = toStage(action);
        const radius = Math.hypot(at.x - center.x, at.y - center.y);
        if (custom) {
          includeActor(center.x - radius, center.y - radius);
          includeActor(center.x + radius, center.y + radius);
        } else include(center.x, center.y, radius + rx, radius + ry);
      }
    }
  }
  if (!Number.isFinite(left)) return {...BASE_VIEWPORT};
  if (options.fitContent) {
    const width = Math.max(right - left, options.minimumWidth ?? 720);
    const height = Math.max(bottom - top, options.minimumHeight ?? 320);
    return {x: (left + right - width) / 2, y: (top + bottom - height) / 2, width, height};
  }
  if (left === 0 && top === 0 && right === STAGE_WIDTH && bottom === STAGE_HEIGHT) return {...BASE_VIEWPORT};
  // Keep the authored aspect ratio so fitting changes scale uniformly, never distorts geometry.
  const width = Math.max(right - left, (bottom - top) * STAGE_WIDTH / STAGE_HEIGHT);
  const height = width * STAGE_HEIGHT / STAGE_WIDTH;
  return {x: (left + right - width) / 2, y: (top + bottom - height) / 2, width, height};
};

/** Process scenes are compiler-positioned. Remove unused authored margins, but share a single
 * envelope across related shots so a counter does not jump merely because the queue got shorter. */
export const fitProcessViewport = (programs: MotionProgram[], settledOnly = false,
  look: IllustrationLook = settledOnly ? 'sketch' : 'vector'): StageViewport => fitMotionViewport({
  entities: programs.flatMap((program) => program.entities),
  paths: programs.flatMap((program) => program.paths),
}, {fitContent: true, labelsBeside: true, settledOnly, look});

/** Generated assets have no fixed catalog size. Frame their complete performance and routes once,
 * while retaining a readable minimum stage and the exact established framing of stock-only scenes. */
export const fitAuthoredMotionViewport = (program: MotionProgram, options: {look?: IllustrationLook} = {}): StageViewport =>
  fitMotionViewport(program, program.entities.some(({entity}) => entity.kind === 'custom')
    ? {...options, fitContent: true, minimumWidth: 720, minimumHeight: 320, visibilityThreshold: 1e-6} : options);
