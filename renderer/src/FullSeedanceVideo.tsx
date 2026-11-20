import React from 'react';
import {AbsoluteFill, Html5Audio, OffthreadVideo, Sequence, staticFile} from 'remotion';
import {Captions} from './Overlays';
import {fullVideoScenes} from './fullVideoContract';
import {ThemeContext, themes} from './theme';
import type {Timeline} from './types';

/** Full-bleed generated imagery, with only narration, captions and optional music added locally. */
export const FullSeedanceVideo: React.FC<Timeline> = (timeline) => {
  const scenes = fullVideoScenes(timeline);
  return <ThemeContext.Provider value={themes.light}>
    <AbsoluteFill style={{fontFamily: themes.light.font}}>
      {scenes.flatMap((scene) => scene.visual.clips.map((clip) => (
        <Sequence key={`${scene.id}-${clip.path}`} from={scene.from + clip.from} durationInFrames={clip.durationInFrames}>
          <OffthreadVideo src={staticFile(clip.path)} muted
            style={{width: '100%', height: '100%', objectFit: 'cover'}} />
        </Sequence>
      )))}
      {timeline.audio.path && <Html5Audio src={staticFile(timeline.audio.path)} />}
      {timeline.music?.path && <Html5Audio src={staticFile(timeline.music.path)} />}
      {/* Keep caption typography proportional at both output sizes, without scaling the video source up. */}
      <div style={{position: 'absolute', width: 1920, height: 1080, transformOrigin: 'top left',
        transform: `scale(${timeline.width / 1920}, ${timeline.height / 1080})`}}>
        <Captions lines={scenes.flatMap((scene) => scene.lines)} />
      </div>
    </AbsoluteFill>
  </ThemeContext.Provider>;
};
