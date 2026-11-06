import React from 'react';
import type {Palette} from './Illustration';
import type {ObjectPerformancePose} from './objectPerformance';
import type {EntityKind} from './types';

const clamp = (n: number) => Math.max(0, Math.min(1, n));
const smooth = (n: number) => {const t = clamp(n); return t * t * (3 - 2 * t);};
const mix = (a: number, b: number, t: number) => a + (b - a) * t;

/** A parcel's flaps, sealing tape and shipping label are independent parts. All poses stay inside
 * the same box footprint, including the initial open pose, so labels and cameras do not breathe. */
export const PackingBox: React.FC<{pose: NonNullable<ObjectPerformancePose['pack']>; palette: Palette;
  color: string; prefix: string; sketch?: boolean}> = ({pose, palette: p, color, prefix, sketch}) => {
  const stroke = {stroke: p.ink, strokeWidth: sketch ? 2.4 : 2.8,
    strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const};
  const rear = smooth(pose.close / 0.78);
  const front = smooth((pose.close - 0.22) / 0.78);
  const flapRear = `M-40-8 0-28 ${mix(0, 20, rear)} ${mix(-47, -18, rear)} ${mix(-40, -20, rear)} ${mix(-27, 2, rear)}Z`;
  const flapFront = `M0 12 40-8 ${mix(43, 20, front)} ${mix(-26, -18, front)} ${mix(3, -20, front)} ${mix(-6, 2, front)}Z`;
  return <g data-object-part="packing-box">
    <defs><clipPath id={`${prefix}-packing-tape`}>
      <path d="M-40-8 0-28 40-8V27L0 47-40 27Z" />
    </clipPath></defs>
    <path d="M-40-8 0-28 40-8 0 12Z" fill={p.ink} {...stroke} />
    <path d="M-40-8 0 12V47L-40 27Z" fill={p.soft} {...stroke} />
    <path d="M0 12 40-8V27L0 47Z" fill={p.paper} {...stroke} />
    <path d="M0 12 40-8V27L0 47Z" fill={color} opacity={0.18} />
    <path d="M-30 14-15 21M-30 20-20 25" stroke={p.muted} strokeWidth={2} />
    <path d={flapRear} fill={p.soft} {...stroke} data-object-part="rear-flap" />
    <path d={flapFront} fill={p.paper} {...stroke} data-object-part="front-flap" />
    <path d={flapFront} fill={color} opacity={0.13} />
    {sketch ? <path d="M-38-6 1 13 38-6M1 13 1 45" fill="none" stroke={p.ink}
      strokeWidth={0.8} opacity={0.35} /> : null}
    <g clipPath={`url(#${prefix}-packing-tape)`} data-object-part="sealing-tape">
      <path d="M20-18-20 2V28" fill="none" stroke={color} strokeWidth={7}
        pathLength={1} strokeDasharray={`${pose.tape} 1`} opacity={pose.tape > 0 ? 0.85 : 0} />
      <path d="M20-18-20 2V28" fill="none" stroke={p.paper} strokeWidth={1}
        pathLength={1} strokeDasharray={`${pose.tape} 1`} opacity={pose.tape * 0.3} />
    </g>
    <g opacity={pose.label} transform={`translate(0 ${-6 * (1 - pose.label)})`} data-object-part="shipping-label">
      <path d="M10 14 31 4V20L10 30Z" fill={p.paper} stroke={p.ink} strokeWidth={1.2} />
      {[14, 17, 20, 24, 27].map((x, index) => <path key={x}
        d={`M${x} ${16 - (x - 10) / 2}v${index % 2 ? 7 : 9}`} stroke={p.ink} strokeWidth={index % 2 ? 1 : 1.7} />)}
    </g>
  </g>;
};

type Props = {kind: EntityKind; pose?: ObjectPerformancePose; palette: Palette; color: string; prefix: string};

/** Surface-local performance keeps the original actor, silhouette and painted order intact. */
export const ObjectDetails: React.FC<Props> = ({kind, pose, palette: p, color, prefix}) => {
  if (!pose || kind === 'person' || kind === 'planet' || kind === 'moon') return null;
  const compute = pose.compute;
  const processing = Math.max(pose.processing, compute?.opacity ?? 0);
  const phase = compute?.phase ?? pose.phase;
  const signal = pose.signal;
  const signalOpacity = signal?.opacity ?? 0;
  const pulse = (row: number) => 0.25 + 0.75 * (0.5 + 0.5 * Math.sin(phase * Math.PI * 4 - row * 1.7));
  const ink = {stroke: p.ink, strokeWidth: 1.7, fill: 'none', strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const};
  const arrow = signal ? (signal.kind === 'send' ? 1 : -1) : 1;
  const traffic = (x: number, y: number, scale = 1) => signal ?
    <g opacity={signalOpacity} transform={`translate(${x} ${y}) scale(${scale})`} data-object-part={signal.kind}>
      <path d={`M${-14 * arrow} 0H${14 * arrow}M${8 * arrow}-5 ${14 * arrow} 0 ${8 * arrow} 5`}
        fill="none" stroke={color} strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={arrow * (-12 + 24 * signal.progress)} r={3} fill={p.paper} stroke={color} strokeWidth={1.5} />
    </g> : null;
  const completed = (x: number, y: number) => pose.complete > 0 ?
    <g opacity={pose.complete} transform={`translate(${x} ${y})`} data-object-part="completed">
      <circle r={8} fill={p.paper} stroke={color} strokeWidth={1.5} />
      <path d="M-4 0-1 3 5-4" {...ink} stroke={color} strokeWidth={2} />
    </g> : null;
  let surface: React.ReactNode = null;
  switch (kind) {
    case 'server': surface = <>
      {[-28.5, -0.5, 27.5].map((y, row) => <g key={y}>
        <circle cx={-18} cy={y} r={3.6} fill={p.soft} />
        <circle cx={-18} cy={y} r={3} fill={color} opacity={0.25 + 0.75 * Math.max(processing * pulse(row), signalOpacity)} />
        <g opacity={processing} data-object-part="server-processing">
          <rect x={-9} y={y - 5} width={29} height={10} rx={1} fill={p.paper} />
          {[0, 1, 2, 3].map((column) => <rect key={column} x={-7 + column * 7} y={y - 3}
            width={4} height={6} rx={0.5} fill={color} opacity={pulse(row + column)} />)}
        </g>
      </g>)}
      {signal ? <rect x={-10} y={-8} width={31} height={15} fill={p.paper} opacity={signalOpacity} /> : null}
      {traffic(5, -0.5, 0.85)}{completed(5, -28.5)}
    </>; break;
    case 'laptop': surface = <>
      <g opacity={Math.max(processing, signalOpacity, pose.complete)}>
        <rect x={-42} y={-31} width={84} height={48} rx={1} fill={p.paper} />
        <path d="M-35-23H-17M-35-18H-25" stroke={p.muted} strokeWidth={2} strokeLinecap="round" />
        <g opacity={processing} data-object-part="screen-processing">
          {[0, 1, 2, 3, 4].map((column) => <rect key={column} x={-32 + column * 14} y={-9}
            width={9} height={17} rx={2} fill={color} opacity={pulse(column)} />)}
        </g>
      </g>
      {traffic(0, -4, 1.4)}{completed(0, -5)}
    </>; break;
    case 'cloud': surface = <>
      <g opacity={Math.max(processing, signalOpacity, pose.complete)}>
        <rect x={-22} y={-17} width={44} height={41} rx={8} fill={p.soft} />
        <g opacity={processing} data-object-part="cloud-processing">
          <path d="M-18 1H18M0-12V15" stroke={color} strokeWidth={2} opacity={0.4} />
          {[-16, 0, 16].map((x, index) => <circle key={x} cx={x} cy={1} r={4}
            fill={color} opacity={pulse(index)} />)}
        </g>
      </g>
      {traffic(0, 1, 1.2)}{completed(0, 1)}
    </>; break;
    case 'packet': surface = <>
      <g opacity={Math.max(processing, signalOpacity, pose.complete)}>
        <rect x={-19} y={-7} width={38} height={19} rx={3} fill={p.paper} stroke={p.line} strokeWidth={1} />
        <g opacity={processing} data-object-part="packet-processing">
          {[0, 1, 2, 3].map((column) => <rect key={column} x={-13 + column * 7} y={-2}
            width={4} height={8} rx={1} fill={color} opacity={pulse(column)} />)}
        </g>
      </g>
      {traffic(0, 2, 0.85)}{completed(0, 1)}
    </>; break;
    case 'box': surface = <>
      {!pose.pack ? <g opacity={processing} data-object-part="parcel-processing">
        <path d="M9 10 31-1V18L9 29Z" fill={p.paper} stroke={p.ink} strokeWidth={1.2} />
        {[0, 1, 2].map((row) => <path key={row} d={`M14 ${12 + row * 5}l12-6`}
          stroke={color} strokeWidth={2} opacity={pulse(row)} />)}
      </g> : null}
      {completed(19, 17)}
    </>; break;
    case 'workbench': surface = <g opacity={processing} data-object-part="bench-processing">
      <path d="M-35-7h26" stroke={color} strokeWidth={3} strokeLinecap="round" opacity={0.3} />
      <path d="M-35-7h26" stroke={color} strokeWidth={3} strokeLinecap="round" pathLength={1}
        strokeDasharray={`${pose.workProgress} 1`} />
    </g>; break;
    case 'coin': surface = <g opacity={Math.max(pose.change, processing) * 0.55} data-object-part="coin-highlight">
      <defs><clipPath id={`${prefix}-coin-glint`}><ellipse rx={25} ry={33} /></clipPath></defs>
      <g clipPath={`url(#${prefix}-coin-glint)`} transform={`translate(${(1 - pose.change) * 24 - 12} 0)`}>
        <path d="M-22 35 9-35H19L-12 35Z" fill={p.paper} />
      </g>
    </g>; break;
    case 'marker': surface = <g opacity={pose.arrival} data-object-part="arrival-target">
      <circle cy={-13} r={4 + pose.arrival * 6} fill="none" stroke={color} strokeWidth={2} />
      <circle cy={-13} r={3} fill={color} />
    </g>; break;
    case 'gauge': surface = <g opacity={pose.change} data-object-part="value-changing">
      <circle cy={8} r={11} fill="none" stroke={color} strokeWidth={2} />
    </g>; break;
    case 'satellite': surface = <>{traffic(0, 2, 0.7)}
      <circle cy={3} r={4} fill={color} opacity={processing * pulse(0)} />
    </>; break;
  }
  const scanShape = kind === 'box' ? 'M-40-8 0-28 40-8V27L0 47-40 27Z' : 'M-30-20H30V20H-30Z';
  const scan = pose.scan ? <g opacity={pose.scan.opacity} data-object-part="scan">
    <defs><clipPath id={`${prefix}-scan`}><path d={scanShape} /></clipPath></defs>
    <g clipPath={`url(#${prefix}-scan)`}>
      <g transform={`translate(0 ${-44 + pose.scan.progress * 92})`}>
        <rect x={-43} y={-7} width={86} height={14} fill={color} opacity={0.12} />
        <path d="M-43 0H43" stroke={color} strokeWidth={2.5} />
      </g>
    </g>
  </g> : null;
  const flameLength = 0.8 + Math.sin(pose.thrustPhase * Math.PI * 12) * 0.12;
  const plume = pose.thrust > 0 ? <g opacity={pose.thrust} data-object-part="thrust">
    {kind === 'spacecraft' ? <>
      <path d={`M-55-8Q${-55 - 8 * flameLength} -6 ${-55 - 10 * flameLength} 0Q${-55 - 8 * flameLength} 6-55 8Z`}
        fill={color} /><path d="M-55-3-61 0-55 3Z" fill={p.paper} />
    </> : kind === 'rocket' ? <>
      <path d={`M-9 43Q-10 58 0 ${45 + 28 * flameLength}Q10 58 9 43Z`} fill={color} />
      <path d={`M-4 44 0 ${47 + 17 * flameLength} 4 44Z`} fill={p.paper} />
    </> : kind === 'satellite' ? <path d={`M-5 25 0 ${27 + 18 * flameLength} 5 25Z`} fill={color} /> : <>
      <path d={`M-9 25Q-10 40 0 ${29 + 24 * flameLength}Q10 40 9 25Z`} fill={color} />
      <path d={`M-4 25 0 ${29 + 15 * flameLength} 4 25Z`} fill={p.paper} />
    </>}
  </g> : null;
  return <g data-object-performance={kind}>{surface}{scan}{plume}</g>;
};
