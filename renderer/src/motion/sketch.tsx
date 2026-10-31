import React, {useMemo} from 'react';
import Peep from 'react-peeps';
import rough from 'roughjs';
import type {IllustrationPose} from './pose';
import {walkBob} from './pose';

/**
 * The `sketch` look: hand-drawn people from Open Peeps (Pablo Stanley, CC0; react-peeps, MIT) and
 * objects outlined with rough.js. Every choice is derived from the entity id and every rough.js shape
 * uses a seed from that id, so a drawing is identical on every frame and in every shot.
 */
export type Look = 'vector' | 'sketch';
export const LookContext = React.createContext<Look>('vector');

/** A stable number in [0, 2^32) per id. */
const hash = (id: string) => {
  let value = 2166136261;
  for (let index = 0; index < id.length; index++) value = Math.imul(value ^ id.charCodeAt(index), 16777619);
  return value >>> 0;
};

// Casual outfits whose light parts take the actor's colour; hair varies so people stay tellable apart.
const OUTFITS = ['ShirtPantsWB', 'RestingWB', 'EasingWB', 'CrossedArmsWB', 'BlazerPantsWB'] as const;
const HAIRS = ['Medium', 'ShortVolumed', 'Bun', 'Afro', 'MediumShort', 'LongCurly', 'Pomp', 'ShortWavy'] as const;
// The standing figures span about this box of Open Peeps' own coordinates.
const PEEP_BOX = {x: 40, y: 80, width: 1010, height: 2820};
// Feet stand on the person footprint's base (metrics.ts: 41 x 63 half extents). The figure is drawn a
// little taller than the vector person, since Open Peeps are slimmer and their linework needs the size;
// at 51 units wide it stays well inside the 82-unit footprint the layout spaces people by.
const FIGURE_HEIGHT = 148;
const FIGURE_WIDTH = FIGURE_HEIGHT * PEEP_BOX.width / PEEP_BOX.height;

export const sketchCast = (id: string) => {
  const value = hash(id);
  return {outfit: OUTFITS[value % OUTFITS.length], hair: HAIRS[(value >>> 8) % HAIRS.length]};
};

/**
 * A hand-drawn person. Walking is a bounce and a gentle rock on each step, the classic cut-out walk, so
 * the drawing itself never changes; a blink swaps in the closed-eyes face for a few frames.
 */
export const SketchPerson: React.FC<{id: string; fill: string; ink: string; pose?: IllustrationPose}> = (
  {id, fill, ink, pose}) => {
  const {outfit, hair} = sketchCast(id);
  const movement = pose?.movement;
  const rock = movement?.walking ? Math.sin(movement.phase * Math.PI * 2) * 3 * movement.strength : 0;
  const breath = pose?.idle ? pose.idle.breath * (1 - (movement?.strength ?? 0)) : 0;
  const blinking = (pose?.idle?.blink ?? 0) > 0.5;
  return <g transform={`translate(0 ${60 - walkBob(pose) * 1.4}) rotate(${rock}) scale(1 ${1 + breath * 0.008})`}>
    {/* Peep draws its own <svg> at 100% of the enclosing viewport, so this one sets the figure's size. */}
    <svg x={-FIGURE_WIDTH / 2} y={-FIGURE_HEIGHT} width={FIGURE_WIDTH} height={FIGURE_HEIGHT} overflow="visible">
      <Peep style={{overflow: 'visible'}}
        viewBox={{x: String(PEEP_BOX.x), y: String(PEEP_BOX.y), width: String(PEEP_BOX.width),
          height: String(PEEP_BOX.height)}}
        body={outfit as never} hair={hair as never} face={(blinking ? 'EyesClosed' : 'Smile') as never}
        strokeColor={ink} backgroundColor={fill} />
    </svg>
  </g>;
};

type Shape = {d: string; stroke: string; strokeWidth: number; fill?: string};

/** rough.js outlines for one entity, regenerated only when its colours change; geometry follows the seed. */
const useRough = (id: string, draw: (generator: ReturnType<typeof rough.generator>, seed: number) => unknown[],
  colors: string[]): Shape[] => useMemo(() => {
  const generator = rough.generator();
  return draw(generator, hash(id) % 2147483646 + 1)
    .flatMap((drawable) => generator.toPaths(drawable as never)) as Shape[];
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [id, ...colors]);

const Shapes: React.FC<{shapes: Shape[]}> = ({shapes}) => <>{shapes.map((shape, index) =>
  <path key={index} d={shape.d} stroke={shape.stroke} strokeWidth={shape.strokeWidth} fill={shape.fill ?? 'none'}
    strokeLinecap="round" strokeLinejoin="round" />)}</>;

/** A hand-drawn service counter with the same parts and footprint as the vector one. */
export const SketchCounter: React.FC<{id: string; color: string; paper: string; soft: string; ink: string}> = (
  {id, color, paper, soft, ink}) => {
  const shapes = useRough(id, (g, seed) => {
    const line = {seed, roughness: 1.3, bowing: 1.1, stroke: ink, strokeWidth: 2.4};
    return [
      g.rectangle(-50, 3, 100, 45, {...line, fill: color, fillStyle: 'hachure', hachureGap: 6, fillWeight: 1.4,
        hachureAngle: -41}),
      g.line(-43, 48, -43, 53, line), g.line(43, 48, 43, 53, line),
      g.rectangle(-58, -6, 116, 12, {...line, fill: soft, fillStyle: 'solid'}),
      g.polygon([[-43, -17], [-20, -17], [-15, -7], [-38, -7]], {...line, strokeWidth: 1.8, fill: paper, fillStyle: 'solid'}),
      g.line(24, -20, 24, -9, {...line, strokeWidth: 3}), g.line(13, -8, 35, -8, {...line, strokeWidth: 3}),
      g.rectangle(5, -49, 38, 29, {...line, fill: soft, fillStyle: 'solid'}),
      g.rectangle(9, -45, 30, 21, {...line, roughness: 0.6, strokeWidth: 1, stroke: soft, fill: paper, fillStyle: 'solid'}),
    ];
  }, [color, paper, soft, ink]);
  return <Shapes shapes={shapes} />;
};
