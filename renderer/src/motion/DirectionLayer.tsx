import React from 'react';
import type {Palette} from './Illustration';
import type {MotionEffects as Effects} from './motionEffects';
import type {MotionPoint} from './types';

const path = (points: MotionPoint[]) => points.map((point, index) =>
  `${index ? 'L' : 'M'}${point.x.toFixed(4)} ${point.y.toFixed(4)}`).join(' ');

/** Direction and travel history stay behind the objects; labels keep their independent stable layout. */
export const DirectionLayer: React.FC<{effects: Effects; palette: Palette}> = ({effects, palette}) => <g
  fill="none" strokeLinecap="round" strokeLinejoin="round" data-motion-layer="direction">
  {effects.orbits.map((orbit) => <g key={orbit.id} opacity={orbit.opacity}>
    <circle cx={orbit.x} cy={orbit.y} r={orbit.radius} stroke={palette[orbit.color]}
      strokeWidth={2} strokeDasharray="3 9" opacity={0.28} />
  </g>)}
  {effects.traces.map((trace) => <g key={trace.id} opacity={trace.opacity} stroke={palette[trace.color]}>
    {trace.points.slice(1).map((point, index) => <path key={index}
      d={path([trace.points[index], point])} strokeWidth={3.8}
      opacity={0.12 + 0.68 * (index + 1) / trace.points.length} />)}
    <path d={path(trace.arrow)} strokeWidth={2.6} opacity={0.85} />
  </g>)}
</g>;
