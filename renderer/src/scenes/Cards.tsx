import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineChapter} from '../types';
import {RisingWords} from './SceneFrame';
import {ease} from './timing';

/** The opening card: the video title and its length. */
export const TitleCard: React.FC<{title: string; subtitle: string}> = ({title, subtitle}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const bar = ease(frame, 12, 22);
  const below = ease(frame, 20, 18);
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', padding: 160}}>
      <h1 style={{margin: 0, fontSize: 108, lineHeight: 1.08, fontWeight: 800, textAlign: 'center', maxWidth: 1600,
        textWrap: 'balance'}}>
        <RisingWords text={title} start={2} stagger={3} />
      </h1>
      <div style={{width: 260 * bar, height: 10, borderRadius: 5, background: theme.accent, margin: '46px 0 36px'}} />
      <div style={{fontSize: 32, fontWeight: 600, letterSpacing: '0.14em', textTransform: 'uppercase',
        color: theme.muted, opacity: below, transform: `translateY(${(1 - below) * 16}px)`}}>
        {subtitle}
      </div>
    </AbsoluteFill>
  );
};

/** Shown before each chapter: its number, title and place among the chapters. */
export const ChapterCard: React.FC<{chapter: TimelineChapter; total: number}> = ({chapter, total}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const kicker = ease(frame, 0, 14);
  const dots = ease(frame, 10, 16);
  // The large outlined number drifts slowly to the left for the whole card.
  const drift = interpolate(frame, [0, chapter.cardFrames + 20], [30, -30]);
  return (
    <AbsoluteFill style={{justifyContent: 'center', padding: '0 180px'}}>
      <div style={{position: 'absolute', right: 110, top: '50%', fontSize: 600, fontWeight: 900, lineHeight: 1,
        color: 'transparent', WebkitTextStroke: `5px ${theme.accent}`, opacity: 0.2 * kicker,
        transform: `translate(${drift}px, -52%)`, fontVariantNumeric: 'tabular-nums'}}>
        {String(chapter.number).padStart(2, '0')}
      </div>
      <div style={{fontSize: 36, fontWeight: 700, letterSpacing: '0.14em', textTransform: 'uppercase',
        color: theme.accent, opacity: kicker, transform: `translateX(${(1 - kicker) * -40}px)`}}>
        Chapter {chapter.number}
      </div>
      <h1 style={{margin: '18px 0 48px', fontSize: 92, lineHeight: 1.1, fontWeight: 800, maxWidth: 1250}}>
        <RisingWords text={chapter.title} start={3} stagger={3} />
      </h1>
      <div style={{display: 'flex', gap: 16, opacity: dots}}>
        {Array.from({length: total}, (_, index) => (
          <div key={index} style={{width: index + 1 === chapter.number ? 64 * dots : 22, height: 22, borderRadius: 11,
            background: index + 1 <= chapter.number ? theme.accent : theme.line}} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
