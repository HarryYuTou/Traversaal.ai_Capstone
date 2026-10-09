import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../theme';
import type {TimelineChapter} from '../types';
import {appear, clamp} from './timing';

const useFade = () => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  return interpolate(frame, [0, 10, durationInFrames - 10, durationInFrames], [0, 1, 1, 0], clamp);
};

/** The opening card: the video title and its length. */
export const TitleCard: React.FC<{title: string; subtitle: string}> = ({title, subtitle}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const bar = appear(frame, 6, fps);
  return (
    <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: useFade(), padding: 160}}>
      <h1 style={{margin: 0, fontSize: 104, lineHeight: 1.1, fontWeight: 800, textAlign: 'center'}}>{title}</h1>
      <div style={{width: 220 * bar, height: 10, borderRadius: 5, background: theme.accent, margin: '44px 0 36px'}} />
      <div style={{fontSize: 36, color: theme.muted}}>{subtitle}</div>
    </AbsoluteFill>
  );
};

/** Shown before each chapter: its number, title and place among the chapters. */
export const ChapterCard: React.FC<{chapter: TimelineChapter; total: number}> = ({chapter, total}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const slide = appear(frame, 0, fps);
  return (
    <AbsoluteFill style={{justifyContent: 'center', padding: '0 180px', opacity: useFade()}}>
      <div style={{fontSize: 38, fontWeight: 700, letterSpacing: '0.12em', textTransform: 'uppercase',
        color: theme.accent, transform: `translateX(${(1 - slide) * -40}px)`}}>
        Chapter {chapter.number}
      </div>
      <h1 style={{margin: '18px 0 48px', fontSize: 88, lineHeight: 1.12, fontWeight: 800, maxWidth: 1500,
        transform: `translateX(${(1 - slide) * -60}px)`}}>
        {chapter.title}
      </h1>
      <div style={{display: 'flex', gap: 16}}>
        {Array.from({length: total}, (_, index) => (
          <div key={index} style={{width: index + 1 === chapter.number ? 64 : 22, height: 22, borderRadius: 11,
            background: index + 1 <= chapter.number ? theme.accent : theme.line}} />
        ))}
      </div>
    </AbsoluteFill>
  );
};
