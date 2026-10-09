import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {appear, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'definition'}>; label: string};
type Part = 'term' | 'definition' | 'example';

/** A key term with its definition; the example, if any, appears when the narration reaches it. */
export const DefinitionScene: React.FC<Props> = ({scene, label}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const level = (part: Part) => highlightLevel(scene.lines, scene.from, frame, (line) => line.highlightPart === part);
  const box = (part: Part) => ({
    borderRadius: 22, padding: '22px 34px', border: `4px solid ${interpolateColors(level(part), [0, 1],
      ['rgba(0, 0, 0, 0)', theme.accent])}`,
    background: interpolateColors(level(part), [0, 1], ['rgba(255, 255, 255, 0)', theme.accentSoft]),
  });
  const {example} = scene.visual;
  const exampleShown = appear(frame,
    revealFrame(scene.lines, scene.from, (line) => line.highlightPart === 'example', 14), fps);
  return (
    <SceneFrame durationInFrames={scene.durationInFrames} label={label} title={scene.visual.title}>
      <div style={{marginTop: 40, display: 'flex', flexDirection: 'column', gap: 22, maxWidth: 1560}}>
        <div style={{...box('term'), alignSelf: 'flex-start', marginLeft: -34}}>
          <span style={{fontSize: 92, lineHeight: 1.05, fontWeight: 800, color: theme.accent}}>
            {scene.visual.term}
          </span>
        </div>
        <div style={{...box('definition'), marginLeft: -34, fontSize: 46, lineHeight: 1.35}}>
          {scene.visual.definition}
        </div>
        {example ? (
          <div style={{...box('example'), marginLeft: -34, opacity: exampleShown,
            transform: `translateY(${(1 - exampleShown) * 24}px)`}}>
            <div style={{fontSize: 26, fontWeight: 700, letterSpacing: '0.1em', textTransform: 'uppercase',
              color: theme.muted, marginBottom: 8}}>
              For example
            </div>
            <div style={{fontSize: 38, lineHeight: 1.35, color: theme.ink}}>{example}</div>
          </div>
        ) : null}
      </div>
    </SceneFrame>
  );
};
