import React from 'react';
import {entityAtFrame, toStage, type MotionProgram} from './engine';
import type {StageViewport} from './camera';
import {placeActorLabels, type LabelSlots} from './labels';
import {ENTITY_EXTENTS, entityHalfExtents} from './metrics';
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
export const groundOffset = (kind: EntityKind, size: number) =>
  (kind === 'person' ? 60 : ENTITY_EXTENTS[kind][1] * 0.94) * size;

const SHADOW_WIDTH: Partial<Record<EntityKind, number>> = {
  person: 25, counter: 64, workbench: 62, server: 48, box: 44, packet: 32, coin: 34,
};

export const StageDefs: React.FC<{ink: string; prefix: string}> = ({ink, prefix}) => <defs>
  <radialGradient id={`${prefix}-shadow`}>
    <stop offset="0%" stopColor={ink} stopOpacity={0.38} />
    <stop offset="55%" stopColor={ink} stopOpacity={0.17} />
    <stop offset="100%" stopColor={ink} stopOpacity={0} />
  </radialGradient>
  <radialGradient id={`${prefix}-floor-fade`}>
    <stop offset="0%" stopColor="#ffffff" stopOpacity={1} />
    <stop offset="100%" stopColor="#ffffff" stopOpacity={0} />
  </radialGradient>
  <radialGradient id={`${prefix}-light`} cx="38%" cy="40%" r="62%">
    <stop offset="0%" stopColor="#fffdf7" stopOpacity={0.95} />
    <stop offset="55%" stopColor="#fbf8f1" stopOpacity={0.55} />
    <stop offset="100%" stopColor="#f6f2e9" stopOpacity={0} />
  </radialGradient>
</defs>;

/**
 * A warm pool of light on the floor, with faint hand-drawn floor tiles inside it so it reads as ground.
 * Both fade to nothing well inside the stage, so neither has an edge.
 */
export const StageFloor: React.FC<{viewport: StageViewport; prefix: string; ink: string}> = ({viewport: v, prefix, ink}) => {
  const center = {x: v.x + v.width * 0.45, y: v.y + v.height * 0.55};
  const radius = {x: v.width * 0.62, y: v.height * 0.72};
  // Rows get closer toward the back and columns lean toward a point above the stage: a gentle perspective.
  const tiles = useRough(`${prefix}-floor`, (g, seed) => {
    const line = {seed, roughness: 0.8, bowing: 0.6, stroke: ink, strokeWidth: 1.4};
    const top = v.y - v.height * 0.1;
    const bottom = v.y + v.height * 1.1;
    const rows = Array.from({length: 7}, (_, index) => top + (bottom - top) * (index / 6) ** 1.25);
    const vanish = {x: center.x, y: v.y - v.height * 2.2};
    const columns = Array.from({length: 11}, (_, index) => v.x - v.width * 0.1 + v.width * 1.2 * index / 10);
    return [
      ...rows.map((y) => g.line(v.x - v.width * 0.1, y, v.x + v.width * 1.1, y, line)),
      ...columns.map((x) => {
        const lean = (x - vanish.x) / (bottom - vanish.y);
        return g.line(vanish.x + lean * (top - vanish.y), top, x, bottom, line);
      }),
    ];
  }, [ink, v.x, v.y, v.width, v.height]);
  return <g>
    <ellipse cx={center.x} cy={center.y} rx={radius.x} ry={radius.y} fill={`url(#${prefix}-light)`} />
    <mask id={`${prefix}-floor-mask`}>
      <ellipse cx={center.x} cy={center.y} rx={radius.x} ry={radius.y} fill={`url(#${prefix}-floor-fade)`} />
    </mask>
    <g mask={`url(#${prefix}-floor-mask)`} opacity={0.1}><Shapes shapes={tiles} /></g>
  </g>;
};

/** A soft shadow where an entity meets the floor; it stays on the ground while a walker bobs. */
export const ContactShadow: React.FC<{kind: EntityKind; x: number; y: number; size: number; opacity: number;
  prefix: string}> = ({kind, x, y, size, opacity, prefix}) => {
  const width = (SHADOW_WIDTH[kind] ?? entityHalfExtents(kind, 1, 0).x) * size;
  return <ellipse cx={x + SHADOW_SHIFT * size} cy={y + groundOffset(kind, size) + 2 * size} rx={width}
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
  slots: LabelSlots): PropPlacement[] => {
  const kinds = new Set(shots.flatMap(({program}) => program.entities.map(({entity}) => entity.kind)));
  const set = SETS[[...kinds].find((kind) => SETS[kind]) ?? 'default'];
  const taken: Box[] = [];
  for (const {program, frames} of shots) {
    for (const frame of frames.filter((_, index) => index % 3 === 0)) {
      const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
      for (const {prepared, state} of actors) {
        if (state.opacity <= 0.05) continue;
        const at = toStage(state);
        const {x, y} = entityHalfExtents(prepared.entity.kind, state.size, state.rotation);
        // Props keep a clear margin around anyone, so a shelf never looks like a hat.
        taken.push({left: at.x - x - 22, right: at.x + x + 22, top: at.y - y - 26, bottom: at.y + y + 22});
      }
      for (const label of placeActorLabels(actors, viewport, slots)) {
        const half = label.actor.prepared.entity.label.length * label.fontSize * 0.36 + 10;
        taken.push({left: label.x - half, right: label.x + half, top: label.y - label.fontSize - 8, bottom: label.y + 10});
      }
    }
  }
  const placed: PropPlacement[] = [];
  set.forEach(({kind, at}, index) => {
    const {width, height} = PROP_SIZE[kind];
    const want = {x: viewport.x + at[0] * viewport.width, y: viewport.y + at[1] * viewport.height};
    let best: {x: number; y: number; cost: number} | null = null;
    for (let x = viewport.x + width / 2 + 6; x <= viewport.x + viewport.width - width / 2 - 6; x += 8) {
      for (let y = viewport.y + height + 6; y <= viewport.y + viewport.height - 6; y += 8) {
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
