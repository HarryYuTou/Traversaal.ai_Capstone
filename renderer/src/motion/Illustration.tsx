import React from 'react';
import type {EntityState} from './engine';
import type {StationState} from './processState';
import type {MotionColor, MotionEntity} from './types';
import {carryOf, limbPath, personLimbs, walkBob, workbenchPress, type ActivityPose, type IllustrationPose} from './pose';

export type Palette = Record<MotionColor, string> & {paper: string; soft: string; line: string};
type Props = {entity: MotionEntity; state: EntityState; palette: Palette; prefix: string; pose?: IllustrationPose; station?: StationState | null};

const clamp = (value: number) => Math.max(0, Math.min(1, value));
const smooth = (value: number) => clamp(value) * clamp(value) * (3 - 2 * clamp(value));

/** Blend two #rrggbb colors, so a station warms up from its closed grey instead of switching on one frame. */
export const mixColor = (from: string, to: string, amount: number) => {
  const t = clamp(amount);
  if (t <= 0 || !/^#[0-9a-f]{6}$/i.test(from) || !/^#[0-9a-f]{6}$/i.test(to)) return t >= 1 ? to : from;
  const channel = (hex: string, index: number) => parseInt(hex.slice(1 + 2 * index, 3 + 2 * index), 16);
  return `#${[0, 1, 2].map((index) => Math.round(channel(from, index) + (channel(to, index) - channel(from, index)) * t)
    .toString(16).padStart(2, '0')).join('')}`;
};

/** Grows from its centre with a slight overshoot, settling exactly at full size. */
const popScale = (amount: number) => {
  const t = clamp(amount) - 1;
  return 1 + 2.2 * t ** 3 + 1.2 * t ** 2;
};

/** Service-time progress is an event cue, not a numerical measure or an invented percentage. */
const ActivityMark: React.FC<{activity: ActivityPose; palette: Palette; color: string; grow: number}> = (
  {activity, palette: p, color, grow}) => (
  <g opacity={activity.opacity * clamp(grow * 2)} transform={`scale(${popScale(grow)})`} data-motion-activity={activity.kind}>
    {activity.kind === 'work' ? <>
      <rect x={-14} y={-4} width={28} height={8} rx={3} fill={p.paper} stroke={p.ink} strokeWidth={1.5} />
      <rect x={-12} y={-2} width={24 * activity.progress} height={4} rx={1} fill={color} />
    </> : <>
      <circle r={12} fill={p.paper} stroke={color} strokeWidth={2} />
      <path d="M-6 0-1 5 7-5" fill="none" stroke={p.ink} strokeWidth={3}
        strokeLinecap="round" strokeLinejoin="round" />
    </>}
  </g>
);

/** Original small vector illustrations. All actors share the same ink, stroke weight and materials. */
export const Illustration: React.FC<Props> = ({entity, state, palette: p, prefix, pose, station}) => {
  // How open a station looks: it brightens over its opening instead of switching on its last frame.
  const opened = !station ? 1 : station.open ? 1 : smooth(station.openingProgress);
  const color = station ? mixColor(p.muted, p[entity.color], opened) : p[entity.color];
  const stroke = {stroke: p.ink, strokeWidth: 2.8, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const};
  const filled = {...stroke, fill: p.paper};
  const clip = `${prefix}-${entity.id}-surface`;
  const limbs = personLimbs(pose);
  const activity = pose?.activity;
  const carry = carryOf(pose);
  const breath = pose?.idle ? pose.idle.breath * (1 - (pose.movement.strength ?? 0)) : 0;
  const blink = pose?.idle?.blink ?? 0;
  const content = (() => {
    switch (entity.kind) {
      case 'planet': return <>
        <defs><clipPath id={clip}><circle r={68} /></clipPath></defs>
        <circle r={68} fill={color} {...stroke} />
        <g clipPath={`url(#${clip})`} fill={p.paper} opacity={0.82}>
          <path d="M-55-51-35-61-15-45-25-30-10-17-17-2-36 0-41 18-59 8-72-18Z" />
          <path d="M-15 16 9 10 23 27 14 44-2 65-12 47-6 30Z" />
          <path d="M21-64 49-48 66-26 43-15 28-22 18-9 3-29Z M49 23 68 32 61 50 36 45Z" />
        </g>
        <path d="M-43-47C-64-28-69-1-61 21" fill="none" stroke={p.paper} strokeWidth={4} opacity={0.5} />
      </>;
      case 'moon': return <>
        <circle r={68} fill={p.soft} {...stroke} />
        <path d="M33-59C15-29 16 31 49 47A68 68 0 0 0 33-59" fill={color} opacity={0.17} />
        <g fill={p.paper} stroke={p.ink} strokeWidth={2} opacity={0.55}>
          <ellipse cx={-27} cy={-27} rx={15} ry={12} /><ellipse cx={24} cy={17} rx={20} ry={16} />
          <circle cx={-25} cy={29} r={8} /><circle cx={18} cy={-39} r={7} />
        </g>
        <path d="M-38-28q11-10 23-1M11 16q13-12 27-1" fill="none" stroke={color} strokeWidth={2} opacity={0.5} />
        <circle cx={-5} cy={-1} r={3} fill={p.muted} opacity={0.4} />
      </>;
      case 'spacecraft': return <>
        <path d="M-49-18-65-27-65 27-49 18" fill={color} {...stroke} />
        <path d="M-49-25H-8V25H-49Z" fill={p.soft} {...stroke} />
        <path d="M-7-30 43-5Q52 0 43 5L-7 30Z" {...filled} />
        <path d="M-37-24V24M-26-24V24" fill="none" stroke={p.muted} strokeWidth={2} />
        <path d="M-1-20 20-7 6 0-1-3Z" fill={color} {...stroke} />
        <path d="M-23-26-15-44M-23 26-15 44" {...stroke} />
        <circle cx={-14} cy={-45} r={5} fill={p.paper} {...stroke} />
        <path d="M44 0h13" {...stroke} />
      </>;
      case 'lander':
      case 'lander-base':
      case 'lander-ascent': return <>
        {entity.kind !== 'lander-ascent' ? <>
          <path d="M-26 11-48 48M26 11 48 48M-57 48h21M36 48h21" fill="none" {...stroke} />
          <path d="M-28 6H28L34 24H-34Z" fill={color} {...stroke} />
          <path d="M-8 25-13 38H13L8 25" fill={p.soft} {...stroke} />
          <path d="M-7 10V23M2 10V23M11 10V23" stroke={p.ink} strokeWidth={2} opacity={0.45} />
        </> : null}
        {entity.kind !== 'lander-base' ? <>
          <path d="M-22-31-35-10-20 8H20L35-10 22-31Z" {...filled} />
          <path d="M-18-24-27-9-7-7-5-24Z M18-24 27-9 7-7 5-24Z" fill={p.ink} />
          <path d="M15-32 24-48M13-48h22M-35-4-47-11" fill="none" {...stroke} />
          <circle cx={-49} cy={-12} r={7} fill={p.soft} {...stroke} />
        </> : null}
      </>;
      case 'rocket': return <>
        <path d="M-15 38-23 60 0 52 23 60 15 38" fill={p.secondary} {...stroke} />
        <path d="M-19 23-34 48-18 44M19 23 34 48 18 44" fill={color} {...stroke} />
        <path d="M-19 40V-34Q-17-57 0-74Q17-57 19-34V40Z" {...filled} />
        <path d="M-17-42Q-10-61 0-74Q10-61 17-42Z" fill={color} {...stroke} />
        <path d="M-19 13H19M-19 26H19M-19-12H19" stroke={p.ink} strokeWidth={3} />
        <circle cy={-27} r={8} fill={color} {...stroke} />
        <path d="M-8 40 0 59 8 40" fill={p.paper} stroke={p.ink} strokeWidth={2} />
      </>;
      case 'satellite': return <>
        <path d="M-60-20H-23V20H-60Z M23-20H60V20H23Z" fill={color} {...stroke} />
        <path d="M-48-20V20M-36-20V20M35-20V20M47-20V20M-60 0H-23M23 0H60" stroke={p.paper} strokeWidth={1.5} opacity={0.7} />
        <rect x={-17} y={-25} width={34} height={50} rx={6} fill={p.soft} {...stroke} />
        <path d="M-23 0H-17M17 0H23M0-25V-39M-15-43Q0-28 15-43" fill="none" {...stroke} />
        <circle cy={3} r={7} fill={p.paper} {...stroke} />
      </>;
      case 'person': return <g transform={`translate(0 ${-walkBob(pose)})`}>
        <path d={`${limbPath(limbs.leftLeg)} ${limbPath(limbs.rightLeg)}`} fill="none" {...stroke} strokeWidth={6} />
        <path d="M-22-2Q0-14 22-2L27 34H-27Z" fill={color} {...stroke} />
        {/* Items rise into the hands as service starts and sink away after it ends. */}
        {carry > 0.01 ? <g opacity={carry} transform={`translate(0 ${(1 - carry) * 8})`}>
          <rect x={-16} y={4} width={32} height={25} rx={2} {...filled} strokeWidth={2} />
        </g> : null}
        <path d={`${limbPath(limbs.leftArm)} ${limbPath(limbs.rightArm)}`} fill="none" {...stroke} strokeWidth={6} />
        <g transform={`translate(0 ${-breath * 1.2})`}>
          <circle cy={-31} r={24} {...filled} />
          <path d="M-23-37Q-8-65 17-48L23-37Q2-39-5-49Q-14-36-23-37" fill={p.ink} />
          <ellipse cx={-8} cy={-30} rx={2.5} ry={2.5 * (1 - 0.85 * blink)} fill={p.ink} />
          <ellipse cx={8} cy={-30} rx={2.5} ry={2.5 * (1 - 0.85 * blink)} fill={p.ink} />
          <path d="M-7-20q7 7 14 0" fill="none" {...stroke} strokeWidth={2} />
        </g>
      </g>;
      case 'packet': return <>
        <path d="M-31-21H31V21H-31Z" {...filled} />
        <path d="M-31-21 0 3 31-21M-31 21-9 0M31 21 9 0" fill="none" {...stroke} />
        <circle cx={24} cy={-18} r={9} fill={color} stroke={p.paper} strokeWidth={3} />
      </>;
      case 'server': return <>
        <path d="M-36-57 35-57 44-45V55H-36Z" fill={p.soft} {...stroke} />
        <path d="M35-57V55M35-45h9" fill="none" stroke={p.muted} strokeWidth={2} />
        {[-39, -11, 17].map((y) => <g key={y}>
          <rect x={-28} y={y} width={54} height={21} rx={3} fill={p.paper} {...stroke} strokeWidth={2} />
          <circle cx={-18} cy={y + 10.5} r={3} fill={color} />
          <path d={`M-7 ${y + 8}h23M-7 ${y + 13}h17`} stroke={p.muted} strokeWidth={2} />
        </g>)}
        <path d="M-26 56v7M27 56v7" {...stroke} strokeWidth={5} />
      </>;
      case 'laptop': return <>
        <rect x={-53} y={-42} width={106} height={70} rx={7} fill={p.soft} {...stroke} />
        <path d="M-44-33H44V19H-44Z" fill={p.paper} {...stroke} strokeWidth={2} />
        <path d="M-53 28-66 43Q-67 48-58 48H58Q67 48 66 43L53 28Z" fill={p.soft} {...stroke} />
        <path d="M-14 30-18 39H18L14 30" fill={p.paper} stroke={p.ink} strokeWidth={2} />
        <path d="M-28-16h38M-28-4h24M-28 8h51" stroke={color} strokeWidth={5} strokeLinecap="round" />
      </>;
      case 'cloud': return <>
        <path d="M-45 30C-82 29-82-17-48-20C-46-57 7-68 26-34C61-43 83-11 69 14C63 27 52 30 34 30Z" fill={p.soft} {...stroke} />
        <path d="M-32-3q7-13 20-13M19-18q17-4 27 11" fill="none" stroke={p.paper} strokeWidth={6} strokeLinecap="round" />
        <path d="M-11 9h24M1-3v24" stroke={color} strokeWidth={5} strokeLinecap="round" />
      </>;
      case 'coin': return <>
        <ellipse cx={5} cy={3} rx={36} ry={43} fill={p.soft} {...stroke} />
        <ellipse rx={34} ry={43} fill={color} {...stroke} />
        <ellipse rx={25} ry={33} fill="none" stroke={p.paper} strokeWidth={2} opacity={0.65} />
        <path d="M11-17C-10-28-22-9-3-1C20 7 13 26-12 17M0-28V28" fill="none" stroke={p.paper} strokeWidth={5} strokeLinecap="round" />
      </>;
      case 'box': return <>
        <path d="M-43-23 0-44 43-23V27L0 49-43 27Z" fill={p.soft} {...stroke} />
        <path d="M-43-23 0-1 43-23M0-1V49" fill="none" {...stroke} />
        <path d="M-12-38 29-17V-2L17 4V-11L-25-32Z" fill={color} opacity={0.7} />
        <path d="M-28 10-13 18M-28 18-17 24" stroke={p.muted} strokeWidth={3} />
      </>;
      case 'counter': return <>
        {/* A solid service counter, a paper slip and a terminal distinguish this from a parcel. */}
        <path d="M-50 3H50V48H-50Z" fill={color} {...stroke} />
        <path d="M-43 48v4M43 48v4" fill="none" {...stroke} strokeWidth={4} />
        <rect x={-58} y={-6} width={116} height={12} rx={3} fill={p.soft} {...stroke} />
        <path d="M-36 16H36V36H-36Z" fill={p.paper} opacity={0.55} />
        <path d="M-43-17-20-17-15-7H-38Z" {...filled} strokeWidth={2} />
        <path d="M-35-13h12" stroke={p.muted} strokeWidth={1.5} />
        <path d="M24-20V-9M13-8H35" fill="none" {...stroke} strokeWidth={4} />
        <rect x={5} y={-49} width={38} height={29} rx={3} fill={p.soft} {...stroke} />
        <rect x={9} y={-45} width={30} height={21} rx={1} fill={p.paper} />
        {!activity ? <path d="M16-36h16M16-31h10" stroke={p.muted} strokeWidth={2} strokeLinecap="round" /> : null}
      </>;
      case 'workbench': return <>
        {/* The bench shows tools only; every parcel must be a separately counted actor. */}
        <path d="M-46 4V52M46 4V52M-46 29H46" fill="none" {...stroke} strokeWidth={5} />
        <rect x={-58} y={-6} width={116} height={12} rx={3} fill={p.soft} {...stroke} />
        <path d="M40-7V-45M29-45H46" fill="none" {...stroke} strokeWidth={4} />
        <g transform={`translate(0 ${workbenchPress(activity)})`}>
          <path d="M28-39V-24M20-24H36" fill="none" {...stroke} strokeWidth={4} />
          <rect x={20} y={-43} width={16} height={6} rx={2} fill={color} {...stroke} strokeWidth={2} />
        </g>
      </>;
      case 'marker': return <>
        <path d="M0 45C-8 32-31 7-31-13A31 31 0 0 1 31-13C31 7 8 32 0 45Z" fill={color} {...stroke} />
        <circle cy={-13} r={12} fill={p.paper} {...stroke} />
        <ellipse cy={49} rx={20} ry={4} fill={p.ink} opacity={0.09} />
      </>;
      case 'gauge': return <>
        <path d="M-65 8A65 65 0 0 1 65 8" fill="none" stroke={p.line} strokeWidth={16} strokeLinecap="round" />
        <path d="M-65 8A65 65 0 0 1 65 8" fill="none" stroke={color} strokeWidth={16} strokeLinecap="round"
          pathLength={1} strokeDasharray={`${Math.max(0, Math.min(1, state.value))} 1`} />
        <path d="M0 8 0-42" stroke={p.ink} strokeWidth={4} strokeLinecap="round"
          transform={`rotate(${-90 + 180 * state.value} 0 8)`} />
        <circle cy={8} r={7} fill={p.ink} />
        <text y={39} textAnchor="middle" fill={p.ink} fontSize={22} fontWeight={750} fontVariant="tabular-nums">
          {Math.round(state.value * 100)}%
        </text>
      </>;
    }
  })();
  const mark = entity.kind === 'counter' ? {x: 24, y: -34}
    : entity.kind === 'workbench' ? {x: -13, y: -20}
      : entity.kind === 'person' ? {x: 0, y: 15} : {x: 0, y: 0};
  return <g><g opacity={station ? 0.5 + 0.5 * opened : 1}>{content}</g>{station ? <g data-station-state={station.open ? 'open' : 'closed'}>
    <rect x={-43} y={12} width={86} height={25} rx={4} fill={p.paper}
      stroke={mixColor(p.muted, p.secondary, opened)} strokeWidth={2} />
    <circle cx={-31} cy={24.5} r={3.5} fill={mixColor(p.muted, p.secondary, opened)} />
    <text x={5} y={29} textAnchor="middle" fontSize={11} fontWeight={750}
      letterSpacing={0.5} fill={mixColor(p.muted, p.ink, opened)}>
      {station.open ? 'OPEN' : station.openingProgress > 0 ? 'OPENING' : 'CLOSED'}
    </text>
    {/* The opening bar fills, then fades over the last part of the opening so OPEN arrives without a jump. */}
    {!station.open && station.openingProgress > 0 ?
      <path d="M-39 34H39" pathLength={1} stroke={p.secondary} strokeWidth={3}
        opacity={clamp((1 - station.openingProgress) / 0.15)}
        strokeDasharray={`${station.openingProgress} 1`} /> : null}
  </g> : null}{activity ? <g transform={`translate(${mark.x} ${mark.y})`}>
    <ActivityMark activity={activity} palette={p} color={color} grow={pose?.markIn ?? 1} />
  </g> : null}</g>;
};
