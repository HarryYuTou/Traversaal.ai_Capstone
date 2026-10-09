import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {motion, theme} from '../theme';
import {clamp} from './timing';

/** Shared slide layout: a small label, the scene title and the template's content, with fade in and out. */
export const SceneFrame: React.FC<{
  durationInFrames: number;
  label: string;
  title: string;
  children: React.ReactNode;
}> = ({durationInFrames, label, title, children}) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame, [0, motion.enter, durationInFrames - motion.exit, durationInFrames],
    [0, 1, 1, 0], clamp);
  const rise = interpolate(frame, [0, motion.enter], [24, 0], clamp);
  return (
    <AbsoluteFill style={{padding: '96px 140px 240px', opacity, transform: `translateY(${rise}px)`}}>
      <div style={{fontSize: 26, fontWeight: 600, letterSpacing: '0.08em', textTransform: 'uppercase',
        color: theme.muted, marginBottom: 22}}>
        {label}
      </div>
      <h1 style={{margin: 0, fontSize: 76, lineHeight: 1.12, fontWeight: 750, maxWidth: 1560}}>{title}</h1>
      {children}
    </AbsoluteFill>
  );
};
