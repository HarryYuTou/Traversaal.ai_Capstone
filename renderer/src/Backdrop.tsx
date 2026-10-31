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

export type Transition = 'slide' | 'dissolve';

/** 0 to 1 across the overlap between two shots of the same stage. */
const dissolve = (frame: number) =>
  interpolate(frame, [0, motion.overlap], [0, 1], {...clamp, easing: Easing.inOut(Easing.sin)});

// In a slide, the old card is gone by this many frames into the overlap and the new one only starts to
// show after the first SLIDE_HANDOFF - 3 frames, so two cards' text is never stacked at full strength.
const SLIDE_HANDOFF = 8;

/**
 * One card or scene on its way in and out. By default it slides in from the right while fading in; unless
 * it is the last, it keeps playing for motion.overlap frames past its own length while sliding out to the
 * left, so the next one arrives over it. The last one fades out over its final frames instead.
 * Two shots of one stage `dissolve` instead: neither moves, and the new shot fades in exactly as the old
 * one fades out. Explainer isolates the shots from the backdrop, so the additive blend keeps everything the
 * two shots share (counters, labels, title row) at full strength for the whole dissolve.
 */
export const Shell: React.FC<{durationInFrames: number; last: boolean; enter?: Transition; exit?: Transition;
  children: React.ReactNode}> = ({durationInFrames, last, enter: entering = 'slide', exit: leaving = 'slide', children}) => {
  const frame = useCurrentFrame();
  const sliding = interpolate(frame, [SLIDE_HANDOFF - 3, SLIDE_HANDOFF - 3 + motion.enter], [0, 1],
    {...clamp, easing: Easing.out(Easing.cubic)});
  const shown = entering === 'dissolve' ? dissolve(frame) : sliding;
  const leavingFrame = frame - durationInFrames;
  const slideOut = !last && leaving === 'slide'
    ? interpolate(leavingFrame, [0, motion.overlap], [0, 1], {...clamp, easing: Easing.in(Easing.quad)}) : 0;
  const gone = last ? interpolate(frame, [durationInFrames - 20, durationInFrames], [0, 1], clamp)
    : leaving === 'dissolve' ? dissolve(leavingFrame)
      : interpolate(leavingFrame, [0, SLIDE_HANDOFF], [0, 1], {...clamp, easing: Easing.in(Easing.quad)});
  const slideIn = entering === 'slide' ? (1 - sliding) * 110 : 0;
  return (
    <AbsoluteFill style={{opacity: shown * (1 - gone),
      transform: `translateX(${slideIn - slideOut * 110}px) scale(${1 - slideOut * 0.015})`,
      mixBlendMode: entering === 'dissolve' && shown < 1 ? 'plus-lighter' : undefined}}>
      {children}
    </AbsoluteFill>
  );
};
