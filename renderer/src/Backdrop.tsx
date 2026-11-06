import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {motion, useTheme} from './theme';
import {transitionOpacity, type Transition} from './transitions';

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
  const seconds = useCurrentFrame() / useVideoConfig().fps;
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
 * Keep related stage shots fully visible across a clean cut. Other boundaries fade through the
 * backdrop, within each shot's own time, so characters and text never acquire a second image.
 * Only opacity changes here: scene coordinates, scale and authored action timing stay untouched.
 */
export const Shell: React.FC<{durationInFrames: number; last: boolean; enter?: Transition; exit?: Transition;
  children: React.ReactNode}> = ({durationInFrames, last, enter: entering = 'fade', exit: leaving = 'fade', children}) => {
  const frame = useCurrentFrame();
  const opacity = transitionOpacity(frame, durationInFrames, entering, last ? 'fade' : leaving,
    motion.enter, last ? 20 : motion.exit);
  return (
    <AbsoluteFill style={{opacity}}>
      {children}
    </AbsoluteFill>
  );
};
