import React from 'react';
import {AbsoluteFill, Easing, interpolate, useCurrentFrame} from 'remotion';
import {clamp} from './scenes/timing';
import {motion, useTheme} from './theme';

// Three soft lights drifting slowly over the gradient: x and y in percent of the frame, size in pixels,
// cycles per second. Slow, smooth motion keeps the video alive without costing much file size.
const LIGHTS = [
  {x: 16, y: 24, size: 1400, speed: 0.045, phase: 0},
  {x: 84, y: 72, size: 1250, speed: 0.033, phase: 2.1},
  {x: 58, y: 8, size: 950, speed: 0.058, phase: 4.2},
];

/** The moving background behind every card and scene. */
export const Backdrop: React.FC = () => {
  const theme = useTheme();
  const seconds = useCurrentFrame() / 30;
  return (
    <AbsoluteFill style={{overflow: 'hidden',
      background: `linear-gradient(135deg, ${theme.backdrop[0]} 0%, ${theme.backdrop[1]} 100%)`}}>
      {LIGHTS.map((light, index) => {
        const turn = 2 * Math.PI * light.speed * seconds;
        const x = light.x + 9 * Math.sin(turn + light.phase);
        const y = light.y + 7 * Math.cos(0.8 * turn + 1.3 * light.phase);
        return (
          <div key={index} style={{position: 'absolute', left: `${x}%`, top: `${y}%`, width: light.size,
            height: light.size, marginLeft: -light.size / 2, marginTop: -light.size / 2, borderRadius: '50%',
            background: `radial-gradient(circle, ${theme.glows[index]} 0%, transparent 68%)`}} />
        );
      })}
      <AbsoluteFill style={{backgroundImage: `radial-gradient(${theme.dots} 1.6px, transparent 2.2px)`,
        backgroundSize: '46px 46px', WebkitMaskImage: 'radial-gradient(ellipse at 50% 42%, black 25%, transparent 80%)'}} />
      {theme.name === 'night' ? (
        <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 45%, transparent 55%, rgba(0, 0, 0, 0.4) 100%)'}} />
      ) : null}
    </AbsoluteFill>
  );
};

/**
 * One card or scene on its way in and out. It slides in from the right while fading in; unless it is the
 * last, it keeps playing for motion.overlap frames past its own length while sliding out to the left, so
 * the next one arrives over it. The last one fades out over its final frames instead.
 */
export const Shell: React.FC<{durationInFrames: number; last: boolean; children: React.ReactNode}> = (
  {durationInFrames, last, children}) => {
  const frame = useCurrentFrame();
  const enter = interpolate(frame, [0, motion.enter], [0, 1], {...clamp, easing: Easing.out(Easing.cubic)});
  const exit = last
    ? interpolate(frame, [durationInFrames - 20, durationInFrames], [0, 1], clamp)
    : interpolate(frame, [durationInFrames, durationInFrames + motion.overlap], [0, 1],
      {...clamp, easing: Easing.in(Easing.quad)});
  const shift = last ? (1 - enter) * 110 : (1 - enter) * 110 - exit * 110;
  return (
    <AbsoluteFill style={{opacity: enter * (1 - exit), transform: `translateX(${shift}px) scale(${1 - exit * 0.015})`}}>
      {children}
    </AbsoluteFill>
  );
};
