import React from 'react';
import type {Palette} from './Illustration';
import {rigPictureAtFrame, type PreparedRig} from './rig';
import type {RigColor} from './types';

/** Declarative SVG only: generated data cannot inject markup, scripts, external URLs or CSS timers. */
export const RigIllustration: React.FC<{rig: PreparedRig; frame: number; palette: Palette}> = ({rig, frame, palette}) => {
  const color = (value: RigColor) => value === 'none' || value.startsWith('#') ? value : palette[value as keyof Palette];
  return <g data-custom-rig={rig.definition.id} strokeLinecap="round" strokeLinejoin="round">
    {rigPictureAtFrame(rig, frame).map(({matrix, opacity, shape}, index) => {
      const style = {fill: color(shape.fill), stroke: color(shape.stroke), strokeWidth: shape.strokeWidth};
      return <g key={index} transform={`matrix(${matrix.join(' ')})`} opacity={opacity}>
        {shape.kind === 'ellipse' ? <ellipse cx={shape.x} cy={shape.y} rx={shape.width / 2} ry={shape.height / 2} {...style} />
          : shape.kind === 'rect' ? <rect x={shape.x} y={shape.y} width={shape.width} height={shape.height}
            rx={shape.radius} {...style} /> : <path d={shape.path} {...style} />}
      </g>;
    })}
  </g>;
};
