import {pathGeometry, STAGE_HEIGHT, STAGE_WIDTH, toStage, type MotionProgram} from './engine';
import {entityExtents, entityHalfExtents, labelMetrics, type IllustrationLook} from './metrics';

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
    if (options.fitContent && entity.opacity <= 0.05 && !actions.some(({action}) =>
      action.kind === 'opacity' && action.value > 0.05)) continue;
    const size = Math.max(entity.size, ...actions.filter(({action}) => action.kind === 'scale').map(({action}) => action.value));
    let extent = entityHalfExtents(entity.kind, size, entity.rotation, options.look);
    if (actions.some(({action}) => action.kind === 'rotate') && !['moon', 'planet'].includes(entity.kind)) {
      const [w, h] = entityExtents(entity.kind, options.look);
      const radius = (Math.hypot(w, h) + 3) * size;
      extent = {x: radius, y: radius};
    }
    const label = entity.label ? labelMetrics(entity.label, options.look === 'sketch' ? 1.25 : 1) : null;
    const rx = Math.max(extent.x, label ? label.width / 2 : 0) + 12;
    const ry = extent.y + (label ? label.height + 27 : 0) + 12;
    const initial = toStage(entity);
    // An arrival's off-stage spawn point is not a place anyone stands.
    if (!options.settledOnly || entity.opacity > 0.05) include(initial.x, initial.y, rx, ry);
    // Room for a label beside a fixed station, the side process scenes prefer (labels.ts).
    if (options.labelsBeside && label && !actions.some(({action}) => ['move', 'follow-path', 'orbit'].includes(action.kind))) {
      include(initial.x + extent.x + 16 + label.width / 2, initial.y, label.width / 2 + 12, label.height / 2 + 12);
    }
    for (const {action, initial: start, geometry} of actions) {
      if (!settled(action)) continue;
      const at = toStage(start);
      // Settled framing takes positions only from movement: a fade-out starts mid-departure, and an
      // arrival starts at its invisible spawn point.
      const positional = ['move', 'follow-path', 'orbit'].includes(action.kind);
      if (!options.settledOnly || (positional && start.opacity > 0.05)) include(at.x, at.y, rx, ry);
      if (action.kind === 'move') {
        const end = toStage(action);
        include(end.x, end.y, rx, ry);
      } else if (geometry) {
        for (const point of geometry.points) include(point.x, point.y, rx, ry);
      } else if (action.kind === 'orbit') {
        const center = toStage(action);
        const radius = Math.hypot(at.x - center.x, at.y - center.y);
        include(center.x, center.y, radius + rx, radius + ry);
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
