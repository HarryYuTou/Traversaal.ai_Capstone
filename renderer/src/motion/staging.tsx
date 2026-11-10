import React from 'react';
import {entityAtFrame, toStage, type MotionProgram} from './engine';
import type {StageViewport} from './camera';
import {placeActorLabels, type LabelSlots} from './labels';
import {entityExtents, entityHalfExtents} from './metrics';
import {useRough, Shapes} from './sketch';
import type {EntityKind} from './types';

/**
 * Set dressing for the sketch look's process stages: a lit floor, soft contact shadows from one light
 * (above and to the left) and a few background props placed where nobody ever walks. Everything here
 * is static or follows an entity, so it never changes between frames on its own.
 */

// The light comes from the upper left, so every shadow falls a little to the right of what casts it.
const SHADOW_SHIFT = 7;

/** Distance from an entity's centre down to where it touches the floor. */
export const groundOffset = (kind: EntityKind, size: number, rigExtents?: [number, number]) =>
  (kind === 'person' ? 60 : entityExtents(kind, 'vector', rigExtents)[1] * 0.94) * size;

const SHADOW_WIDTH: Partial<Record<EntityKind, number>> = {
  person: 25, counter: 64, workbench: 62, server: 48, box: 44, packet: 32, coin: 34,
};

export const StageDefs: React.FC<{ink: string; prefix: string}> = ({ink, prefix}) => <defs>
  <radialGradient id={`${prefix}-shadow`}>
    <stop offset="0%" stopColor={ink} stopOpacity={0.38} />
    <stop offset="55%" stopColor={ink} stopOpacity={0.17} />
    <stop offset="100%" stopColor={ink} stopOpacity={0} />
  </radialGradient>
</defs>;

/** Where the back wall meets the floor (stage units) and where the exit door stands on that wall. */
export type Room = {horizon: number; doorX: number};

// A warm wall, a slightly deeper floor, and the sky through the windows.
const ROOM = {wallTop: '#f3ede3', wallLow: '#e7dfd1', baseboard: '#d3c7b3', floorFar: '#dcd1be', floorNear: '#ebe3d5',
  skyTop: '#bcd9ee', skyLow: '#e3f0f8', cloud: '#ffffff', door: '#c9b18f'};

/**
 * Lay out the room once for a whole stage: the wall stands just behind the farthest point anyone's feet
 * reach (but never lower than a fifth of the way down the frame), and the door is where people who leave
 * along the back wall finally fade out.
 */
export const planRoom = (shots: {program: MotionProgram; frames: number[]}[], viewport: StageViewport): Room => {
  let nearestWall = Infinity;
  let doorX = viewport.x + viewport.width * 0.9;
  let doorDepth = Infinity;
  for (const {program, frames} of shots) {
    for (const frame of frames) {
      for (const prepared of program.entities) {
        const state = entityAtFrame(prepared, frame);
        if (state.opacity <= 0.05) continue;
        const at = toStage(state);
        const feet = at.y + groundOffset(prepared.entity.kind, state.size);
        nearestWall = Math.min(nearestWall, feet);
        // The last place a departing person is seen near the back of the room marks the door.
        if (state.opacity < 0.5 && prepared.entity.kind === 'person' && feet <= doorDepth + 1) {
          doorDepth = feet;
          doorX = Math.max(viewport.x + 50, Math.min(viewport.x + viewport.width - 50, at.x));
        }
      }
    }
  }
  const horizon = Math.min(nearestWall - 16, viewport.y + viewport.height * 0.2);
  return {horizon, doorX: doorDepth < horizon + 90 ? doorX : viewport.x + viewport.width * 0.9};
};

/**
 * The room the scene happens in, seen from slightly above: a back wall with a baseboard, two windows
 * onto the sky and an exit door, and a floor with perspective tiles and sunlight from the windows. It is
 * drawn far past the stage so it fills the whole frame behind the title.
 */
export const StageRoom: React.FC<{viewport: StageViewport; room: Room; prefix: string; ink: string}> = (
  {viewport: v, room, prefix, ink}) => {
  const h = room.horizon;
  const far = {left: v.x - v.width * 2, right: v.x + v.width * 3, top: v.y - v.height * 3, bottom: v.y + v.height * 3};
  const windows = [v.x + v.width * 0.47, v.x + v.width * 0.7].filter((x) => Math.abs(x - room.doorX) > 110);
  const pane = {width: 104, height: 72, bottom: h - 30};
  const lines = useRough(`${prefix}-room`, (g, seed) => {
    const line = {seed, roughness: 0.9, bowing: 0.7, stroke: ink, strokeWidth: 2};
    const faint = {...line, strokeWidth: 1.4};
    // Floor tiles: rows crowd toward the wall, columns meet at a point high above the frame.
    const vanish = {x: v.x + v.width * 0.5, y: h - v.height * 2.4};
    const rows = Array.from({length: 7}, (_, index) => h + (v.y + v.height * 1.15 - h) * ((index + 1) / 7) ** 1.5);
    const columns = Array.from({length: 11}, (_, index) => v.x - v.width * 0.4 + v.width * 1.8 * index / 10);
    const bottom = v.y + v.height * 1.2;
    return [
      g.line(far.left, h, far.right, h, line),
      g.line(far.left, h - 9, far.right, h - 9, faint),
      ...windows.flatMap((x) => [
        g.rectangle(x - pane.width / 2, pane.bottom - pane.height, pane.width, pane.height, line),
        g.line(x, pane.bottom - pane.height, x, pane.bottom, faint),
        g.line(x - pane.width / 2, pane.bottom - pane.height / 2, x + pane.width / 2, pane.bottom - pane.height / 2, faint),
        g.line(x - pane.width / 2 - 6, pane.bottom + 3, x + pane.width / 2 + 6, pane.bottom + 3, {...line, strokeWidth: 3}),
      ]),
      g.rectangle(room.doorX - 30, h - 104, 60, 104, {...line, fill: ROOM.door, fillStyle: 'solid'}),
      g.circle(room.doorX + 19, h - 52, 5, {...faint, fill: ink, fillStyle: 'solid'}),
      g.rectangle(room.doorX - 22, h - 128, 44, 16, {...faint, fill: '#7fb08f', fillStyle: 'solid'}),
      ...rows.map((y) => g.line(far.left, y, far.right, y, faint)),
      ...columns.map((x) => {
        const lean = (x - vanish.x) / (bottom - vanish.y);
        return g.line(vanish.x + lean * (h - vanish.y), h, x, bottom, faint);
      }),
    ];
  }, [ink, h, room.doorX, v.x, v.y, v.width, v.height]);
  return <g>
    <defs>
      <linearGradient id={`${prefix}-wall`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={ROOM.wallTop} /><stop offset="100%" stopColor={ROOM.wallLow} />
      </linearGradient>
      <linearGradient id={`${prefix}-floor`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={ROOM.floorFar} /><stop offset="100%" stopColor={ROOM.floorNear} />
      </linearGradient>
      <linearGradient id={`${prefix}-sky`} x1="0" y1="0" x2="0" y2="1">
        <stop offset="0%" stopColor={ROOM.skyTop} /><stop offset="100%" stopColor={ROOM.skyLow} />
      </linearGradient>
      <linearGradient id={`${prefix}-sun`} x1="0" y1="0" x2="0.4" y2="1">
        <stop offset="0%" stopColor="#fffaf0" stopOpacity={0.8} /><stop offset="100%" stopColor="#fffaf0" stopOpacity={0} />
      </linearGradient>
    </defs>
    {/* The wall darkens slightly toward the floor; the floor is deeper in tone far away. */}
    <rect x={far.left} y={far.top} width={far.right - far.left} height={h - far.top} fill={`url(#${prefix}-wall)`} />
    <rect x={far.left} y={h - 9} width={far.right - far.left} height={9} fill={ROOM.baseboard} />
    <rect x={far.left} y={h} width={far.right - far.left} height={far.bottom - h} fill={`url(#${prefix}-floor)`} />
    {windows.map((x) => <g key={x}>
      <rect x={x - pane.width / 2} y={pane.bottom - pane.height} width={pane.width} height={pane.height}
        fill={`url(#${prefix}-sky)`} />
      <ellipse cx={x - 18} cy={pane.bottom - pane.height * 0.62} rx={22} ry={8} fill={ROOM.cloud} opacity={0.9} />
      <ellipse cx={x + 22} cy={pane.bottom - pane.height * 0.32} rx={16} ry={6} fill={ROOM.cloud} opacity={0.8} />
      {/* Sunlight through this window lands on the floor below and to the right. */}
      <polygon points={`${x - pane.width / 2},${h + 4} ${x + pane.width / 2},${h + 4} ${x + pane.width / 2 + 70},${h + 150}
        ${x - pane.width / 2 + 70},${h + 150}`} fill={`url(#${prefix}-sun)`} />
    </g>)}
    {/* The last 18 lines are floor tiles, drawn faintly; the wall's lines are drawn firmly. */}
    <g opacity={0.08}><Shapes shapes={lines.slice(-(7 + 11))} /></g>
    <g opacity={0.8}><Shapes shapes={lines.slice(0, -(7 + 11))} /></g>
    <text x={room.doorX} y={h - 116} textAnchor="middle" fontSize={11} fontWeight={800} fill="#ffffff"
      letterSpacing={1}>EXIT</text>
  </g>;
};

/** A soft shadow where an entity meets the floor; it stays on the ground while a walker bobs. */
export const ContactShadow: React.FC<{kind: EntityKind; x: number; y: number; size: number; opacity: number;
  prefix: string; rigExtents?: [number, number]}> = ({kind, x, y, size, opacity, prefix, rigExtents}) => {
  const width = (SHADOW_WIDTH[kind] ?? entityHalfExtents(kind, 1, 0, 'vector', rigExtents).x) * size;
  return <ellipse cx={x + SHADOW_SHIFT * size} cy={y + groundOffset(kind, size, rigExtents) + 2 * size} rx={width}
    ry={width * 0.24} fill={`url(#${prefix}-shadow)`} opacity={opacity} />;
};

export type PropKind = 'shelf' | 'plant' | 'baskets';
export type PropPlacement = {id: string; kind: PropKind; x: number; y: number};
// Footprints in stage units: width and height above the floor point (x, y).
const PROP_SIZE: Record<PropKind, {width: number; height: number; shadow: number}> = {
  shelf: {width: 132, height: 122, shadow: 70}, plant: {width: 54, height: 86, shadow: 26},
  baskets: {width: 64, height: 46, shadow: 34},
};
// What dresses each kind of process: preferred spots as fractions of the frame (floor point).
const SETS: Record<string, {kind: PropKind; at: [number, number]}[]> = {
  counter: [{kind: 'shelf', at: [0.12, 0.34]}, {kind: 'baskets', at: [0.1, 0.95]}, {kind: 'plant', at: [0.97, 0.62]},
    {kind: 'shelf', at: [0.33, 0.3]}],
  default: [{kind: 'plant', at: [0.06, 0.6]}, {kind: 'plant', at: [0.97, 0.6]}],
};

type Box = {left: number; top: number; right: number; bottom: number};
const overlaps = (a: Box, b: Box) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

/**
 * Place props once for a whole stage: each takes the free spot nearest its preferred place, clear of
 * every body, label and walk in every sampled frame of every shot, and of the props placed before it.
 */
export const planProps = (shots: {program: MotionProgram; frames: number[]}[], viewport: StageViewport,
  slots: LabelSlots, horizon = -Infinity): PropPlacement[] => {
  const kinds = new Set(shots.flatMap(({program}) => program.entities.map(({entity}) => entity.kind)));
  const set = SETS[[...kinds].find((kind) => SETS[kind]) ?? 'default'];
  const taken: Box[] = [];
  for (const {program, frames} of shots) {
    for (const frame of frames.filter((_, index) => index % 3 === 0)) {
      const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
      for (const {prepared, state} of actors) {
        if (state.opacity <= 0.05) continue;
        const at = toStage(state);
        const {x, y} = entityHalfExtents(prepared.entity.kind, state.size, state.rotation, 'sketch', prepared.rigExtents);
        // Props keep a clear margin around anyone, so a shelf never looks like a hat.
        taken.push({left: at.x - x - 22, right: at.x + x + 22, top: at.y - y - 26, bottom: at.y + y + 22});
      }
      for (const label of placeActorLabels(actors, viewport, slots)) {
        taken.push({left: label.bounds.left - 8, right: label.bounds.right + 8,
          top: label.bounds.top - 8, bottom: label.bounds.bottom + 8});
      }
    }
  }
  const placed: PropPlacement[] = [];
  set.forEach(({kind, at}, index) => {
    const {width, height} = PROP_SIZE[kind];
    const want = {x: viewport.x + at[0] * viewport.width, y: viewport.y + at[1] * viewport.height};
    let best: {x: number; y: number; cost: number} | null = null;
    for (let x = viewport.x + width / 2 + 6; x <= viewport.x + viewport.width - width / 2 - 6; x += 8) {
      // Props stand on the floor, in front of the back wall.
      for (let y = Math.max(viewport.y + height + 6, horizon + 12); y <= viewport.y + viewport.height - 6; y += 8) {
        const box = {left: x - width / 2, right: x + width / 2, top: y - height, bottom: y + 8};
        if (taken.some((other) => overlaps(box, other))) continue;
        const cost = Math.hypot((x - want.x) / viewport.width, (y - want.y) / viewport.height);
        if (!best || cost < best.cost) best = {x, y, cost};
      }
    }
    // A prop that would have to wander far from its place would only clutter the frame.
    if (!best || best.cost > 0.3) return;
    placed.push({id: `${kind}-${index}`, kind, x: best.x, y: best.y});
    taken.push({left: best.x - width / 2 - 16, right: best.x + width / 2 + 16, top: best.y - height - 16, bottom: best.y + 16});
  });
  return placed;
};

// Background props are drawn in quieter colours so the cast stays the subject.
const PROP_COLORS = ['#c9b79c', '#a9bfb8', '#d9b3a3', '#b8c2d6', '#d8cf9f'];

/** One background prop, hand-drawn and seeded by its id, standing on its floor point. */
export const Prop: React.FC<{prop: PropPlacement; ink: string; paper: string; soft: string; prefix: string}> = (
  {prop, ink, paper, soft, prefix}) => {
  const shapes = useRough(`${prefix}-${prop.id}`, (g, seed) => {
    const line = {seed, roughness: 1.2, bowing: 1, stroke: ink, strokeWidth: 2};
    const fill = (color: string) => ({...line, fill: color, fillStyle: 'solid'});
    switch (prop.kind) {
      case 'shelf': {
        const shelves = [-118, -80, -42];
        return [
          g.rectangle(-64, -122, 128, 122, fill(soft)),
          ...shelves.map((y) => g.line(-64, y + 36, 64, y + 36, line)),
          // Goods on each shelf: boxes and jars of a few muted colours, sized by the seed.
          ...shelves.flatMap((y, row) => Array.from({length: 5}, (_, item) => {
            const width = 16 + ((seed >> (row * 5 + item)) & 7);
            const height = 18 + ((seed >> (row + item * 3)) & 9);
            const left = -58 + item * 24;
            const color = PROP_COLORS[(row * 2 + item) % PROP_COLORS.length];
            return item % 2
              ? g.ellipse(left + width / 2, y + 36 - height / 2, width - 2, height, {...fill(color), strokeWidth: 1.4})
              : g.rectangle(left, y + 36 - height, width, height, {...fill(color), strokeWidth: 1.4});
          })),
          g.line(-60, 0, -60, 6, {...line, strokeWidth: 3}), g.line(60, 0, 60, 6, {...line, strokeWidth: 3}),
        ];
      }
      case 'plant': return [
        g.polygon([[-17, -30], [17, -30], [12, 0], [-12, 0]], fill('#d9a98c')),
        ...[[-14, -56, 18, 34], [0, -78, 16, 40], [14, -58, 18, 34], [-6, -68, 14, 30], [7, -70, 14, 30]].map(
          ([x, y, width, height]) => g.ellipse(x, y, width, height, {...fill('#9fc3a0'), strokeWidth: 1.6})),
        g.line(0, -30, 0, -76, line),
      ];
      case 'baskets': return [0, 1].flatMap((level) => {
        const top = -46 + level * 14;
        return [
          g.polygon([[-30, top], [30, top], [24, top + 32], [-24, top + 32]], fill(level ? '#e4a37f' : '#d98b66')),
          g.line(-27, top + 10, 27, top + 10, {...line, stroke: paper, strokeWidth: 1.4}),
          g.line(-25, top + 20, 25, top + 20, {...line, stroke: paper, strokeWidth: 1.4}),
        ];
      });
    }
  }, [ink, paper, soft]);
  const {shadow} = PROP_SIZE[prop.kind];
  return <g transform={`translate(${prop.x} ${prop.y})`}>
    <ellipse cx={SHADOW_SHIFT} cy={4} rx={shadow} ry={shadow * 0.2} fill={`url(#${prefix}-shadow)`} />
    <Shapes shapes={shapes} />
  </g>;
};
