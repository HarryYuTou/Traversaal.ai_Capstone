import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {clamp} from './scenes/timing';
import {theme} from './theme';
import type {TimelineChapter, TimelineLine} from './types';

// Lines closer together than this (the 3-frame gap inside a scene) share one caption box without blinking.
const JOIN_FRAMES = 3;
const FADE_FRAMES = 4;

const end = (line: TimelineLine) => line.from + line.durationInFrames;

/** The spoken line as a caption, synced to the narration track. */
export const Captions: React.FC<{lines: TimelineLine[]}> = ({lines}) => {
  const frame = useCurrentFrame();
  let index = -1;
  lines.forEach((line, i) => {
    if (line.from <= frame) {
      index = i;
    }
  });
  if (index < 0) {
    return null;
  }
  const line = lines[index];
  const joinsPrevious = index > 0 && line.from - end(lines[index - 1]) <= JOIN_FRAMES;
  const joinsNext = index + 1 < lines.length && lines[index + 1].from - end(line) <= JOIN_FRAMES;
  if (frame >= end(line) + (joinsNext ? JOIN_FRAMES : FADE_FRAMES)) {
    return null;
  }
  const fadeIn = joinsPrevious ? 1 : interpolate(frame - line.from, [0, FADE_FRAMES], [0, 1], clamp);
  const fadeOut = joinsNext ? 1 : interpolate(frame - end(line), [0, FADE_FRAMES], [1, 0], clamp);
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 70, display: 'flex', justifyContent: 'center'}}>
      <div style={{maxWidth: 1480, padding: '16px 36px', borderRadius: 18, background: theme.caption, color: '#fff',
        fontSize: 40, lineHeight: 1.35, textAlign: 'center', textWrap: 'balance', opacity: Math.min(fadeIn, fadeOut)}}>
        {line.text}
      </div>
    </div>
  );
};

/** A thin bar along the bottom edge with a mark where each chapter starts. */
export const ProgressBar: React.FC<{chapters: TimelineChapter[]}> = ({chapters}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const share = (value: number) => `${(100 * value) / durationInFrames}%`;
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 10, background: theme.line}}>
      <div style={{width: share(frame + 1), height: '100%', background: theme.accent}} />
      {chapters.slice(1).map((chapter) => (
        <div key={chapter.id} style={{position: 'absolute', top: 0, bottom: 0, left: share(chapter.from), width: 4,
          background: theme.bg}} />
      ))}
    </div>
  );
};
