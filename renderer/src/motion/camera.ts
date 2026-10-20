import {pathGeometry, STAGE_HEIGHT, STAGE_WIDTH, toStage, type MotionProgram} from './engine';
import {ENTITY_EXTENTS, entityHalfExtents, labelMetrics} from './metrics';

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
export const fitMotionViewport = (program: MotionProgram): StageViewport => {
  let left = 0; let top = 0; let right = STAGE_WIDTH; let bottom = STAGE_HEIGHT;
  const include = (x: number, y: number, rx: number, ry: number) => {
    left = Math.min(left, x - rx); right = Math.max(right, x + rx);
    top = Math.min(top, y - ry); bottom = Math.max(bottom, y + ry);
  };
  for (const path of program.paths) {
    for (const point of pathGeometry(path).points) include(point.x, point.y, 4, 4);
  }
  for (const prepared of program.entities) {
    const {entity, actions} = prepared;
    const size = Math.max(entity.size, ...actions.filter(({action}) => action.kind === 'scale').map(({action}) => action.value));
    let extent = entityHalfExtents(entity.kind, size, entity.rotation);
    if (actions.some(({action}) => action.kind === 'rotate') && !['moon', 'planet'].includes(entity.kind)) {
      const [w, h] = ENTITY_EXTENTS[entity.kind];
      const radius = (Math.hypot(w, h) + 3) * size;
      extent = {x: radius, y: radius};
    }
    const label = entity.label ? labelMetrics(entity.label) : null;
    const rx = Math.max(extent.x, label ? label.width / 2 : 0) + 12;
    const ry = extent.y + (label ? label.height + 27 : 0) + 12;
    const initial = toStage(entity);
    include(initial.x, initial.y, rx, ry);
    for (const {action, initial: start, geometry} of actions) {
      const at = toStage(start);
      include(at.x, at.y, rx, ry);
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
  if (left === 0 && top === 0 && right === STAGE_WIDTH && bottom === STAGE_HEIGHT) return {...BASE_VIEWPORT};
  // Keep the authored aspect ratio so fitting changes scale uniformly, never distorts geometry.
  const width = Math.max(right - left, (bottom - top) * STAGE_WIDTH / STAGE_HEIGHT);
  const height = width * STAGE_HEIGHT / STAGE_WIDTH;
  return {x: (left + right - width) / 2, y: (top + bottom - height) / 2, width, height};
};
