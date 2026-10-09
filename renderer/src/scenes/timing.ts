import {interpolate, spring} from 'remotion';
import {motion} from '../theme';
import type {TimelineLine} from '../types';

export const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;

type Match = (line: TimelineLine) => boolean;

/** Scene-relative frame at which an item first appears: the start of the first line that highlights it. */
export const revealFrame = (lines: TimelineLine[], sceneFrom: number, matches: Match, fallback: number) => {
  const first = lines.find(matches);
  return first ? first.from - sceneFrom : fallback;
};

/** 0 before `start`, easing to 1 over the reveal time. */
export const appear = (frame: number, start: number, fps: number) =>
  spring({frame: frame - start, fps, config: {damping: 200}, durationInFrames: motion.reveal});

/**
 * How strongly an item is highlighted, from 0 to 1. A highlight starts with the line that sets it
 * and lasts until a line that does not set it begins, so back-to-back lines about one item never flicker.
 */
export const highlightLevel = (lines: TimelineLine[], sceneFrom: number, frame: number, matches: Match,
                               ramp = 6) => {
  let level = 0;
  lines.forEach((line, index) => {
    if (!matches(line) || (index > 0 && matches(lines[index - 1]))) {
      return;
    }
    const start = line.from - sceneFrom;
    const next = lines.slice(index + 1).find((later) => !matches(later));
    const rise = interpolate(frame, [start, start + ramp], [0, 1], clamp);
    const fall = next ? interpolate(frame, [next.from - sceneFrom, next.from - sceneFrom + ramp], [1, 0], clamp) : 1;
    level = Math.max(level, Math.min(rise, fall));
  });
  return level;
};
