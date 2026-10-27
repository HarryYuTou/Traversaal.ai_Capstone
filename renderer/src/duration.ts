import type {Timeline} from './types';

/** A short sample must not round up to a minute before checking the actual duration. */
export const timelineLengthText = (timeline: Pick<Timeline, 'durationInFrames' | 'fps' | 'chapters'>) => {
  const seconds = timeline.durationInFrames / timeline.fps;
  const minutes = Math.round(seconds / 60);
  const length = seconds < 60 ? 'under a minute' : `about ${minutes} minute${minutes === 1 ? '' : 's'}`;
  const chapters = timeline.chapters.length;
  return chapters ? `${chapters} chapters · ${length}` : length;
};
