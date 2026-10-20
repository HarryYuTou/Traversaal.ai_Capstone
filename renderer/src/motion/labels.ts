import {toStage, type EntityState, type PreparedEntity} from './engine';
import {BASE_VIEWPORT, type StageViewport} from './camera';
import {entityHalfExtents, labelMetrics} from './metrics';

export type Actor = {prepared: PreparedEntity; state: EntityState};
type Box = {left: number; top: number; right: number; bottom: number};
const intersects = (a: Box, b: Box) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/** Keep labels outside illustrated bodies, particularly a lander approaching the Moon's surface. */
export const placeActorLabels = (actors: Actor[], viewport: StageViewport = BASE_VIEWPORT) => {
  const visible = actors.filter(({state}) => state.opacity > 0.05);
  const bodies = visible.map(({prepared, state}) => {
    const point = toStage(state);
    const {x: rx, y: ry} = entityHalfExtents(prepared.entity.kind, state.size, state.rotation);
    return {point, radius: ['moon', 'planet'].includes(prepared.entity.kind) ? 68 * state.size : null,
      box: {left: point.x - rx, right: point.x + rx, top: point.y - ry, bottom: point.y + ry}};
  });
  const placed: Box[] = [];
  return visible.flatMap((actor, index) => {
    const {entity} = actor.prepared;
    if (!entity.label) return [];
    const {point, box: body} = bodies[index];
    const {fontSize, width, height} = labelMetrics(entity.label);
    const positions = [
      {x: point.x, y: body.bottom + 27}, {x: point.x, y: body.top - 17},
      {x: body.right + width / 2 + 16, y: point.y + fontSize / 3},
      {x: body.left - width / 2 - 16, y: point.y + fontSize / 3},
    ];
    const candidates = positions.map((position, preference) => {
      const x = Math.max(viewport.x + width / 2 + 12, Math.min(viewport.x + viewport.width - width / 2 - 12, position.x));
      const y = Math.max(viewport.y + height + 8, Math.min(viewport.y + viewport.height - 10, position.y));
      const box = {left: x - width / 2, right: x + width / 2, top: y - fontSize, bottom: y + 6};
      const hits = bodies.filter((other) => {
        if (other.radius === null) return intersects(box, other.box);
        const nearestX = Math.max(box.left, Math.min(box.right, other.point.x));
        const nearestY = Math.max(box.top, Math.min(box.bottom, other.point.y));
        return Math.hypot(other.point.x - nearestX, other.point.y - nearestY) < other.radius + 6;
      }).length;
      return {x, y, box, score: hits * 1000 + placed.filter((other) => intersects(box, other)).length * 1500 + preference};
    });
    const best = candidates.sort((a, b) => a.score - b.score)[0];
    placed.push(best.box);
    return [{actor, x: best.x, y: best.y, fontSize}];
  });
};
