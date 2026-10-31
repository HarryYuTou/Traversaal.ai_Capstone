import React from 'react';
import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {clamp} from './scenes/timing';
import {useTheme} from './theme';
import type {TimelineChapter, TimelineLine} from './types';
import {layoutCaption, type CaptionLayout} from './captionLayout';

// Lines closer together than this (the 3-frame gap inside a scene) share one caption box without blinking.
const JOIN_FRAMES = 3;
const FADE_FRAMES = 4;
// When a joined line follows, over MORPH_FRAMES the old words fade out, then the box eases to the new
// line's size, then the new words fade in, so text never spills over a box that is changing size.
const MORPH_FRAMES = 10;
const FONT_SIZE = 40;

const end = (line: TimelineLine) => line.from + line.durationInFrames;
const smooth = (t: number) => {
  const p = Math.max(0, Math.min(1, t));
  return p * p * (3 - 2 * p);
};
/** 0 to 1 across the part [from, to] of a morph that itself runs 0 to 1. */
const stage = (morph: number, from: number, to: number) => smooth((morph - from) / (to - from));

// Measured with the same font the caption is drawn in; each text is laid out once per render process.
const layouts = new Map<string, CaptionLayout>();
let context: CanvasRenderingContext2D | null = null;
const captionLayout = (text: string, font: string): CaptionLayout => {
  const key = `${font}\n${text}`;
  const known = layouts.get(key);
  if (known) return known;
  context ??= document.createElement('canvas').getContext('2d');
  // Without a canvas, a rough per-character estimate keeps the caption readable.
  const measure = context ? (value: string) => {
    context!.font = `400 ${FONT_SIZE}px ${font}`;
    return context!.measureText(value).width;
  } : (value: string) => value.length * FONT_SIZE * 0.52;
  const layout = layoutCaption(text, measure);
  layouts.set(key, layout);
  return layout;
};

const Rows: React.FC<{layout: CaptionLayout; opacity: number}> = ({layout, opacity}) => (
  <div style={{position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', justifyContent: 'center',
    alignItems: 'center', opacity}}>
    {layout.rows.map((row, index) => <div key={index} style={{whiteSpace: 'nowrap'}}>{row}</div>)}
  </div>
);

/** The spoken line as a caption, synced to the narration track. */
export const Captions: React.FC<{lines: TimelineLine[]}> = ({lines: all}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  // A line that reads a quotation aloud is already on screen word by word, so it gets no caption.
  const lines = all.filter((line) => !line.highlightQuote);
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
  const layout = captionLayout(line.text, theme.font);
  const previous = joinsPrevious ? captionLayout(lines[index - 1].text, theme.font) : undefined;
  const morph = previous ? Math.min(1, (frame - line.from) / MORPH_FRAMES) : 1;
  const resize = stage(morph, 0.25, 0.75);
  const size = (key: 'width' | 'height') => previous ? previous[key] + (layout[key] - previous[key]) * resize : layout[key];
  return (
    <div style={{position: 'absolute', left: 0, right: 0, bottom: 70, display: 'flex', justifyContent: 'center'}}>
      <div style={{position: 'relative', width: size('width'), height: size('height'), borderRadius: 18,
        background: theme.caption, color: '#fff', fontSize: FONT_SIZE, lineHeight: 1.35,
        opacity: Math.min(fadeIn, fadeOut)}}>
        {previous && morph < 0.35 ? <Rows layout={previous} opacity={1 - stage(morph, 0, 0.35)} /> : null}
        <Rows layout={layout} opacity={previous ? stage(morph, 0.65, 1) : 1} />
      </div>
    </div>
  );
};

/** A thin bar along the bottom edge with a mark where each chapter starts. */
export const ProgressBar: React.FC<{chapters: TimelineChapter[]}> = ({chapters}) => {
  const theme = useTheme();
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
