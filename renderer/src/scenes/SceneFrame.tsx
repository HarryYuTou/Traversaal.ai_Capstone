import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {useTheme} from '../theme';
import {ease} from './timing';

/** Text whose words rise into place one after another, starting `start` frames into the scene. */
export const RisingWords: React.FC<{text: string; start?: number; stagger?: number}> = (
  {text, start = 0, stagger = 2}) => {
  const frame = useCurrentFrame();
  return (
    <>
      {text.split(' ').map((word, index) => {
        const shown = ease(frame, start + index * stagger, 14);
        return (
          <React.Fragment key={index}>
            {index > 0 ? ' ' : null}
            <span style={{display: 'inline-block', opacity: shown, transform: `translateY(${(1 - shown) * 0.42}em)`}}>
              {word}
            </span>
          </React.Fragment>
        );
      })}
    </>
  );
};

/** The small label above a title: an accent bar that grows, then the text. */
export const Kicker: React.FC<{text: string; start?: number; color?: string}> = ({text, start = 0, color}) => {
  const theme = useTheme();
  const shown = ease(useCurrentFrame(), start, 16);
  return (
    <div style={{display: 'flex', alignItems: 'center', gap: 18, fontSize: 26, fontWeight: 650,
      letterSpacing: '0.08em', textTransform: 'uppercase', color: color ?? theme.muted, opacity: shown,
      transform: `translateX(${(1 - shown) * -24}px)`}}>
      <span style={{flex: '0 0 auto', width: 44 * shown, height: 6, borderRadius: 3, background: theme.accent}} />
      {text}
    </div>
  );
};

/** Shared slide layout: a small label, the scene title and the template's content. */
export const SceneFrame: React.FC<{label: string; title: string; children: React.ReactNode}> = (
  {label, title, children}) => (
  <AbsoluteFill style={{padding: '96px 140px 240px'}}>
    <Kicker text={label} />
    <h1 style={{margin: '22px 0 0', fontSize: 76, lineHeight: 1.12, fontWeight: 750, maxWidth: 1560}}>
      <RisingWords text={title} start={2} />
    </h1>
    {children}
  </AbsoluteFill>
);
