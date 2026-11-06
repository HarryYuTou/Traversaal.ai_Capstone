import React, {useMemo} from 'react';
import {loadFont} from '@remotion/google-fonts/PatrickHand';
import Peep from 'react-peeps';
import rough from 'roughjs';
import type {IllustrationPose} from './pose';
import {HORIZONTAL_DIRECTION_EPSILON, walkBob} from './pose';

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
// Feet stand at y=60. Sketch people have their own 45 x 94 half-extents in metrics.ts;
// the taller Open Peeps head and hair must be included in camera and label planning.
const FIGURE_HEIGHT = 148;
const FIGURE_WIDTH = FIGURE_HEIGHT * PEEP_BOX.width / PEEP_BOX.height;

export const sketchCast = (id: string) => {
  const value = hash(id);
  return {outfit: OUTFITS[value % OUTFITS.length], hair: HAIRS[(value >>> 8) % HAIRS.length]};
};

// The drawn figure is kept down to just below the hips; legs below are a rig that can walk.
const HIP_CUT = 0.56;
const HIP_Y = -FIGURE_HEIGHT * (1 - HIP_CUT);
const THIGH = 36;
const SHIN = 34;
// Two trouser legs as wide as the drawn hips, so the cut edge of the drawing disappears into them.
const HIP_SPREAD = 6;

type Leg = {hip: {x: number; y: number}; knee: {x: number; y: number}; ankle: {x: number; y: number}; toe: number};

/**
 * Both legs at a point in the stride. phase runs once per two steps (pose.ts); a leg swings forward
 * with its knee bent and plants straight, and both stand straight when strength falls to 0.
 */
export const legsAt = (phase: number, strength: number, direction: number): Leg[] => [0, 0.5].map((offset, index) => {
  const cycle = ((phase + offset) % 1 + 1) % 1;
  const stance = cycle < 0.5;
  const progress = stance ? cycle * 2 : (cycle - 0.5) * 2;
  const hip = {x: index ? HIP_SPREAD : -HIP_SPREAD, y: HIP_Y - 5};
  // Half a 44-unit stride is a planted step. Its backwards travel cancels the actor's forward travel;
  // the other half swings above the floor. A still shoe's sole is exactly at local y=0.
  const travel = stance ? 11 - 22 * progress : -11 * Math.cos(Math.PI * progress);
  const lift = stance ? 0 : Math.sin(Math.PI * progress) * 10 * strength;
  const ankle = {x: hip.x + direction * travel * strength, y: -5 - lift};
  const dx = ankle.x - hip.x;
  const dy = ankle.y - hip.y;
  const distance = Math.hypot(dx, dy);
  const along = (THIGH * THIGH - SHIN * SHIN + distance * distance) / (2 * distance);
  const bend = Math.sqrt(Math.max(0, THIGH * THIGH - along * along)) * strength;
  const knee = {x: hip.x + dx / distance * along + direction * dy / distance * bend,
    y: hip.y + dy / distance * along - direction * dx / distance * bend};
  return {hip, knee, ankle, toe: stance ? 0 : Math.sin(Math.PI * progress) * 14 * strength};
});

/** Feet follow actual travel; a head can look toward the next turn without redirecting a planted step. */
export const sketchLegPose = (pose?: IllustrationPose) => {
  const movement = pose?.movement;
  const strength = movement?.walking ? movement.strength : 0;
  const attention = pose?.performance?.lookX ?? movement?.facing ?? 0;
  const tangent = strength > 1e-6 ? Math.max(-1, Math.min(1, (movement?.facing ?? 0) / strength)) : attention;
  return {legs: legsAt(movement?.phase ?? 0, strength, tangent),
    // The shoe silhouette settles toward the held gaze after a stop, without changing foot placement.
    direction: attention + (tangent - attention) * strength};
};

/** Two readable drawn views, with a brief narrower turning pose instead of scaling through zero. */
export const sketchView = (pose?: IllustrationPose) => {
  const attention = Math.max(-1, Math.min(1, pose?.performance?.lookX ?? pose?.movement.facing ?? 0));
  const amount = Math.abs(attention);
  const width = 0.86 + 0.14 * amount * amount * (3 - 2 * amount);
  // Directly supplied poses get the same protection as poses evaluated from motion tracks.
  const left = attention < -HORIZONTAL_DIRECTION_EPSILON;
  return {facing: left ? 'left' : 'right', scaleX: (left ? -1 : 1) * width};
};

const LegDrawing: React.FC<{leg: Leg; ink: string; paper: string; direction: number}> = ({leg, ink, paper, direction}) => {
  const {hip, knee, ankle} = leg;
  const left = -8.5 + direction * 2.5;
  const right = 8.5 + direction * 2.5;
  const heel = -4 - direction * 2;
  const toe = -4 + direction * 2;
  return <g>
    <path d={`M${hip.x},${hip.y} L${knee.x},${knee.y}`} fill="none" stroke={ink} strokeWidth={12.5}
      strokeLinecap="round" />
    <path d={`M${knee.x},${knee.y} L${ankle.x},${ankle.y}`} fill="none" stroke={ink} strokeWidth={10.5}
      strokeLinecap="round" />
    {/* A sneaker in the Open Peeps manner: white with an ink outline, tilting with the shin. */}
    <g transform={`translate(${ankle.x} ${ankle.y + 1}) rotate(${-direction * leg.toe * 0.6})`}>
      <path d={`M${left},4 L${left},-1 Q${left},${heel} ${left + 4},${heel} L${right - 4},${toe} Q${right},${toe} ${right},1 L${right},4 Z`}
        fill={paper} stroke={ink} strokeWidth={1.6}
        strokeLinejoin="round" />
      <path d={`M${left},2 L${right},2`} stroke={ink} strokeWidth={1.2} />
    </g>
  </g>;
};

/**
 * One stable Open Peeps outfit and hair per identity. The public body/head/face layers articulate
 * separately, while planted feet and distance-based strides anchor the drawing to the floor.
 */
export const SketchPerson: React.FC<{id: string; fill: string; ink: string; paper: string; pose?: IllustrationPose}> = (
  {id, fill, ink, paper, pose}) => {
  const {outfit, hair} = sketchCast(id);
  const movement = pose?.movement;
  const performance = pose?.performance;
  const strength = movement?.walking ? movement.strength : 0;
  const direction = performance?.lookX ?? movement?.facing ?? 0;
  const gait = sketchLegPose(pose);
  const view = sketchView(pose);
  const lean = performance?.lean ?? direction * 2.5 * strength;
  const acknowledge = performance?.acknowledge ?? 0;
  const breath = pose?.idle ? pose.idle.breath * (1 - strength) : 0;
  const blinking = (pose?.idle?.blink ?? 0) > 0.5;
  const clip = `sketch-body-${id.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  // The body rides up as a leg passes under it; the feet stay where the legs put them.
  const lift = walkBob(pose) * 0.8 - (performance?.settle ?? 0) * 0.6;
  const viewBox = {x: String(PEEP_BOX.x), y: String(PEEP_BOX.y), width: String(PEEP_BOX.width),
    height: String(PEEP_BOX.height)};
  const artwork = {x: -FIGURE_WIDTH / 2, y: -FIGURE_HEIGHT, width: FIGURE_WIDTH,
    height: FIGURE_HEIGHT, overflow: 'visible' as const};
  return <g transform="translate(0 60)" data-character-rig="sketch">
    <defs><clipPath id={clip}><rect x={-60} y={-FIGURE_HEIGHT - 20} width={120} height={FIGURE_HEIGHT * HIP_CUT + 20} /></clipPath></defs>
    {/* Back leg first, then the body over both hip joints, then nothing covers the front foot. */}
    <g data-character-part="feet">
      {gait.legs.map((leg, index) => <LegDrawing key={index} leg={leg} ink={ink} paper={paper} direction={gait.direction} />)}
    </g>
    <g data-character-part="torso" transform={`translate(0 ${-lift}) rotate(${lean} 0 ${HIP_Y})`}>
      <g data-character-facing={view.facing} transform={`scale(${view.scaleX} 1)`}>
        <g clipPath={`url(#${clip})`}>
        {/* Body-only rendering keeps every garment and its original arms intact, without overlay limbs. */}
        <svg {...artwork}>
          <Peep style={{overflow: 'visible'}} viewBox={viewBox} body={outfit as never}
            strokeColor={ink} backgroundColor={fill} />
        </svg>
        </g>
      </g>
      <g data-character-part="head" transform={`translate(${direction * 1.6} ${acknowledge * 1.8 - breath * 0.45}) rotate(${performance?.headTilt ?? 0} 0 -120)`}>
        <g data-character-facing={view.facing} transform={`scale(${view.scaleX} 1)`}>
        <svg {...artwork}>
          <Peep style={{overflow: 'visible'}} viewBox={viewBox} hair={hair as never}
            strokeColor={ink} backgroundColor={fill} />
        </svg>
        {/* This offset is in the drawn view; the enclosing mirror gives it the world-facing sign. */}
        <g transform={`translate(${Math.abs(direction) * 0.8} 0)`}>
          <svg {...artwork}>
            <Peep style={{overflow: 'visible'}} viewBox={viewBox} face={(blinking ? 'EyesClosed' : 'Smile') as never}
              strokeColor={ink} backgroundColor={fill} />
          </svg>
        </g>
        </g>
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
