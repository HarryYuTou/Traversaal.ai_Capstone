import React, {useMemo} from 'react';
import {loadFont} from '@remotion/google-fonts/PatrickHand';
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

/** Labels in the sketch look are hand-lettered (Patrick Hand, OFL), fetched once at render start. */
export const loadSketchFont = () => loadFont('normal', {weights: ['400'], subsets: ['latin']}).fontFamily;

/** A stable number in [0, 2^32) per id. */
export const hash = (id: string) => {
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

// The drawn figure is kept down to just below the hips; legs below are a rig that can walk.
const HIP_CUT = 0.56;
const HIP_Y = -FIGURE_HEIGHT * (1 - HIP_CUT);
const THIGH = 31;
const SHIN = 29;
// Two trouser legs as wide as the drawn hips, so the cut edge of the drawing disappears into them.
const HIP_SPREAD = 6;

type Leg = {hip: {x: number; y: number}; knee: {x: number; y: number}; ankle: {x: number; y: number}; toe: number};

/**
 * Both legs at a point in the stride. phase runs once per two steps (pose.ts); a leg swings forward
 * with its knee bent and plants straight, and both stand straight when strength falls to 0.
 */
export const legsAt = (phase: number, strength: number, direction: number): Leg[] => [0, 0.5].map((offset, index) => {
  const turn = 2 * Math.PI * (phase + offset);
  const thigh = Math.sin(turn) * 20 * strength * Math.PI / 180;
  const knee = Math.max(0, Math.cos(turn)) * 34 * strength * Math.PI / 180;
  const hip = {x: index ? HIP_SPREAD : -HIP_SPREAD, y: HIP_Y - 5};
  const kneeAt = {x: hip.x + direction * Math.sin(thigh) * THIGH, y: hip.y + Math.cos(thigh) * THIGH};
  const shin = thigh - knee;
  const ankle = {x: kneeAt.x + direction * Math.sin(shin) * SHIN, y: kneeAt.y + Math.cos(shin) * SHIN};
  return {hip, knee: kneeAt, ankle, toe: shin * 180 / Math.PI};
});

const LegDrawing: React.FC<{leg: Leg; ink: string; paper: string; direction: number}> = ({leg, ink, paper, direction}) => {
  const {hip, knee, ankle} = leg;
  return <g>
    <path d={`M${hip.x},${hip.y} L${knee.x},${knee.y}`} fill="none" stroke={ink} strokeWidth={12.5}
      strokeLinecap="round" />
    <path d={`M${knee.x},${knee.y} L${ankle.x},${ankle.y}`} fill="none" stroke={ink} strokeWidth={10.5}
      strokeLinecap="round" />
    {/* A sneaker in the Open Peeps manner: white with an ink outline, tilting with the shin. */}
    <g transform={`translate(${ankle.x} ${ankle.y + 1}) rotate(${-direction * leg.toe * 0.6}) scale(${direction} 1)`}>
      <path d="M-5,-4 C-5,-7 1,-6 3,-3 C7,-2 11,-1 11,2.5 L11,4 L-6,4 Z" fill={paper} stroke={ink} strokeWidth={1.6}
        strokeLinejoin="round" />
      <path d="M-6,2 L11,2" stroke={ink} strokeWidth={1.2} />
    </g>
  </g>;
};

/**
 * A hand-drawn person. The upper body is an Open Peeps drawing that never changes; the legs are a rig
 * that walks with steps tied to the distance covered (pose.ts) and stands straight when still. A blink
 * swaps in the closed-eyes face for a few frames.
 */
export const SketchPerson: React.FC<{id: string; fill: string; ink: string; paper: string; pose?: IllustrationPose}> = (
  {id, fill, ink, paper, pose}) => {
  const {outfit, hair} = sketchCast(id);
  const movement = pose?.movement;
  const strength = movement?.walking ? movement.strength : 0;
  const direction = (movement?.facing ?? 0) < -0.2 ? -1 : 1;
  const legs = legsAt(movement?.phase ?? 0, strength, direction);
  const lean = direction * 2.5 * strength;
  const breath = pose?.idle ? pose.idle.breath * (1 - strength) : 0;
  const blinking = (pose?.idle?.blink ?? 0) > 0.5;
  const clip = `sketch-body-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  // The body rides up as a leg passes under it; the feet stay where the legs put them.
  const lift = walkBob(pose) * 1.2;
  return <g transform="translate(0 60)">
    <defs><clipPath id={clip}><rect x={-60} y={-FIGURE_HEIGHT - 20} width={120} height={FIGURE_HEIGHT * HIP_CUT + 20} /></clipPath></defs>
    {/* Back leg first, then the body over both hip joints, then nothing covers the front foot. */}
    <g transform={`translate(0 ${-lift * 0.3})`}>
      {legs.map((leg, index) => <LegDrawing key={index} leg={leg} ink={ink} paper={paper} direction={direction} />)}
    </g>
    <g transform={`translate(0 ${-lift}) rotate(${lean} 0 ${HIP_Y}) scale(1 ${1 + breath * 0.008})`}>
      <g clipPath={`url(#${clip})`}>
        {/* Peep draws its own <svg> at 100% of the enclosing viewport, so this one sets the figure's size. */}
        <svg x={-FIGURE_WIDTH / 2} y={-FIGURE_HEIGHT} width={FIGURE_WIDTH} height={FIGURE_HEIGHT} overflow="visible">
          <Peep style={{overflow: 'visible'}}
            viewBox={{x: String(PEEP_BOX.x), y: String(PEEP_BOX.y), width: String(PEEP_BOX.width),
              height: String(PEEP_BOX.height)}}
            body={outfit as never} hair={hair as never} face={(blinking ? 'EyesClosed' : 'Smile') as never}
            strokeColor={ink} backgroundColor={fill} />
        </svg>
      </g>
    </g>
  </g>;
};

type Shape = {d: string; stroke: string; strokeWidth: number; fill?: string};

/** rough.js outlines for one entity, regenerated only when its inputs change; geometry follows the seed. */
export const useRough = (id: string, draw: (generator: ReturnType<typeof rough.generator>, seed: number) => unknown[],
  deps: (string | number)[]): Shape[] => useMemo(() => {
  const generator = rough.generator();
  return draw(generator, hash(id) % 2147483646 + 1)
    .flatMap((drawable) => generator.toPaths(drawable as never)) as Shape[];
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [id, ...deps]);

export const Shapes: React.FC<{shapes: Shape[]}> = ({shapes}) => <>{shapes.map((shape, index) =>
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

/** Other process stations and moving items, hand-drawn on the vector drawings' footprints. */
export const SKETCHED_KINDS = new Set(['server', 'workbench', 'packet', 'box', 'coin']);

export const SketchObject: React.FC<{id: string; kind: string; color: string; paper: string; soft: string;
  ink: string; muted: string; press?: number}> = ({id, kind, color, paper, soft, ink, muted, press = 0}) => {
  const shapes = useRough(id, (g, seed) => {
    const line = {seed, roughness: 1.3, bowing: 1.1, stroke: ink, strokeWidth: 2.4};
    const solid = (fill: string) => ({...line, fill, fillStyle: 'solid'});
    const hatched = {...line, fill: color, fillStyle: 'hachure', hachureGap: 6, fillWeight: 1.4, hachureAngle: -41};
    switch (kind) {
      case 'server': return [
        g.path('M-36-57 35-57 44-45V55H-36Z', solid(soft)),
        g.line(35, -57, 35, 55, {...line, stroke: muted, strokeWidth: 1.6}),
        ...[-39, -11, 17].flatMap((y) => [
          g.rectangle(-28, y, 54, 21, {...solid(paper), strokeWidth: 1.8}),
          g.circle(-18, y + 10.5, 7, {...line, strokeWidth: 1, fill: color, fillStyle: 'solid'}),
          g.line(-7, y + 8, 16, y + 8, {...line, stroke: muted, strokeWidth: 1.6}),
          g.line(-7, y + 13, 10, y + 13, {...line, stroke: muted, strokeWidth: 1.6}),
        ]),
        g.line(-26, 56, -26, 63, {...line, strokeWidth: 4}), g.line(27, 56, 27, 63, {...line, strokeWidth: 4}),
      ];
      case 'workbench': return [
        g.line(-46, 4, -46, 52, {...line, strokeWidth: 4}), g.line(46, 4, 46, 52, {...line, strokeWidth: 4}),
        g.line(-46, 29, 46, 29, {...line, strokeWidth: 3.5}),
        g.rectangle(-58, -6, 116, 12, solid(soft)),
        g.line(40, -7, 40, -45, {...line, strokeWidth: 3.5}), g.line(29, -45, 46, -45, {...line, strokeWidth: 3.5}),
      ];
      case 'packet': return [
        g.rectangle(-31, -21, 62, 42, solid(paper)),
        g.linearPath([[-31, -21], [0, 3], [31, -21]], line),
        g.line(-31, 21, -9, 0, line), g.line(31, 21, 9, 0, line),
        g.circle(24, -18, 18, {...line, stroke: paper, strokeWidth: 2.5, fill: color, fillStyle: 'solid'}),
      ];
      case 'box': return [
        g.polygon([[-43, -23], [0, -44], [43, -23], [43, 27], [0, 49], [-43, 27]], solid(soft)),
        g.linearPath([[-43, -23], [0, -1], [43, -23]], line), g.line(0, -1, 0, 49, line),
        g.polygon([[-12, -38], [29, -17], [29, -2], [17, 4], [17, -11], [-25, -32]],
          {...line, strokeWidth: 0.8, stroke: color, fill: color, fillStyle: 'hachure', hachureGap: 4}),
        g.line(-28, 10, -13, 18, {...line, stroke: muted, strokeWidth: 2}),
        g.line(-28, 18, -17, 24, {...line, stroke: muted, strokeWidth: 2}),
      ];
      case 'coin': return [
        g.ellipse(5, 3, 72, 86, solid(soft)),
        g.ellipse(0, 0, 68, 86, hatched),
        g.ellipse(0, 0, 50, 66, {...line, stroke: paper, strokeWidth: 1.6}),
        g.path('M11-17C-10-28-22-9-3-1C20 7 13 26-12 17M0-28V28', {...line, stroke: paper, strokeWidth: 4}),
      ];
      default: return [];
    }
  }, [kind, color, paper, soft, ink, muted]);
  // The press head is the only moving part of a bench; it is drawn on its own so the frame never shifts.
  const head = useRough(`${id}-press`, (g, seed) => kind !== 'workbench' ? [] : [
    g.line(28, -39, 28, -24, {seed, roughness: 1.2, stroke: ink, strokeWidth: 3.5}),
    g.line(20, -24, 36, -24, {seed, roughness: 1.2, stroke: ink, strokeWidth: 3.5}),
    g.rectangle(20, -43, 16, 6, {seed, roughness: 1, stroke: ink, strokeWidth: 1.8, fill: color, fillStyle: 'solid'}),
  ], [kind, color, ink]);
  return <><Shapes shapes={shapes} /><g transform={`translate(0 ${press})`}><Shapes shapes={head} /></g></>;
};
