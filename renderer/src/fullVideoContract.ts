import type {Timeline, TimelineScene} from './types';

type GeneratedScene = Extract<TimelineScene, {template: 'generated-video'}>;

/** Fail before drawing if any frame would fall back to an animation, card, or empty backdrop. */
export function fullVideoScenes(timeline: Timeline): GeneratedScene[] {
  if (timeline.visualMode !== 'seedance-full' || timeline.titleFrames !== 0 || timeline.chapters.length) {
    throw new Error('Full Seedance video cannot contain title or chapter cards.');
  }
  if (!((timeline.width === 854 && timeline.height === 480) || (timeline.width === 1280 && timeline.height === 720))) {
    throw new Error('Seedance export must match the selected 480p or 720p quality.');
  }
  const scenes: GeneratedScene[] = [];
  let cursor = 0;
  for (const scene of timeline.scenes) {
    if (scene.template !== 'generated-video' || scene.from !== cursor || scene.durationInFrames <= 0) {
      throw new Error('Every frame must have generated footage.');
    }
    let end = 0;
    for (const clip of scene.visual.clips) {
      if (clip.from !== end || !Number.isInteger(clip.durationInFrames) || clip.durationInFrames <= 0 || !clip.path) {
        throw new Error('Generated clips must be contiguous and non-empty.');
      }
      end += clip.durationInFrames;
    }
    if (end !== scene.durationInFrames) throw new Error('Generated clips must cover their entire scene.');
    cursor += end;
    scenes.push(scene);
  }
  if (cursor !== timeline.durationInFrames || !scenes.length) throw new Error('Generated footage must cover the entire video.');
  return scenes;
}
