import type {EntityKind} from './types';

// Bounds include the illustration's widest extremities; fitting adds stroke and antialiasing space.
export const ENTITY_EXTENTS: Record<Exclude<EntityKind, 'custom'>, [number, number]> = {
  planet: [68, 68], moon: [68, 68], spacecraft: [65, 45], lander: [57, 55],
  'lander-base': [57, 48], 'lander-ascent': [56, 55], rocket: [34, 74], satellite: [60, 48],
  person: [41, 63], packet: [36, 28], server: [44, 63], laptop: [66, 48], cloud: [78, 60],
  coin: [41, 46], box: [43, 49], marker: [31, 53], gauge: [75, 65],
  counter: [58, 52], workbench: [58, 52],
};

export type IllustrationLook = 'vector' | 'sketch';

/** Sketch people stand on the same floor but their hair reaches above the vector head. */
export const entityExtents = (kind: EntityKind, look: IllustrationLook = 'vector',
  rigExtents?: [number, number]): [number, number] => kind === 'custom' ? rigExtents ?? [0, 0]
    : kind === 'person' && look === 'sketch' ? [45, 94] : ENTITY_EXTENTS[kind];

export const entityHalfExtents = (kind: EntityKind, size: number, rotation: number,
  look: IllustrationLook = 'vector', rigExtents?: [number, number]) => {
  const [w, h] = entityExtents(kind, look, rigExtents);
  if (kind === 'planet' || kind === 'moon') return {x: (w + 3) * size, y: (h + 3) * size};
  const angle = (rotation % 360) * Math.PI / 180;
  return {x: size * (Math.abs(w * Math.cos(angle)) + Math.abs(h * Math.sin(angle)) + 3),
    y: size * (Math.abs(w * Math.sin(angle)) + Math.abs(h * Math.cos(angle)) + 3)};
};

export const labelMetrics = (label: string, fontScale = 1) => {
  const fontSize = (label.length > 24 ? 19 : 22) * fontScale;
  // One em per code unit is deliberately conservative for wide capitals, CJK and fallback fonts.
  return {fontSize, width: label.length * fontSize + 14, height: fontSize + 10};
};
