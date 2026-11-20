import React from 'react';
import {AbsoluteFill, OffthreadVideo, Sequence, staticFile} from 'remotion';
import type {TimelineScene} from '../types';

/** Footage is normalized to exact scene frames; narration and captions remain on the main timeline. */
export const GeneratedVideoScene: React.FC<{scene: Extract<TimelineScene, {template: 'generated-video'}>}> = ({scene}) => (
  <AbsoluteFill style={{background: '#111827'}}>
    {scene.visual.clips.map((clip) => (
      <Sequence key={clip.path} from={clip.from} durationInFrames={clip.durationInFrames}>
        <OffthreadVideo src={staticFile(clip.path)} muted
          style={{width: '100%', height: '100%', objectFit: 'cover'}} />
      </Sequence>
    ))}
    <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,.35), transparent 28%, transparent 60%, rgba(0,0,0,.6))'}} />
    <div style={{position: 'absolute', top: 58, left: 76, right: 76, color: 'white', fontSize: 40,
      fontWeight: 650, textShadow: '0 2px 8px rgba(0,0,0,.65)'}}>{scene.visual.title}</div>
  </AbsoluteFill>
);
