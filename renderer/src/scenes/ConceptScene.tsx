import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {appear, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'concept'}>; label: string};

/** Title, one statement and up to three points; each point appears when the narration reaches it. */
export const ConceptScene: React.FC<Props> = ({scene, label}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {points} = scene.visual;
  return (
    <SceneFrame durationInFrames={scene.durationInFrames} label={label} title={scene.visual.title}>
      <p style={{margin: '30px 0 0', fontSize: 44, lineHeight: 1.35, color: theme.muted, maxWidth: 1500}}>
        {scene.visual.statement}
      </p>
      {points.length > 0 ? (
        <div style={{display: 'grid', gridTemplateColumns: `repeat(${points.length}, minmax(0, 1fr))`, gap: 32,
          marginTop: 52}}>
          {points.map((point, index) => {
            const matches = (line: {highlightPointIndex?: number}) => line.highlightPointIndex === index;
            const shown = appear(frame, revealFrame(scene.lines, scene.from, matches, 6 + index * 4), fps);
            const level = highlightLevel(scene.lines, scene.from, frame, matches);
            return (
              <div key={index} style={{
                fontSize: 36, lineHeight: 1.3, fontWeight: 550, padding: '34px 38px', borderRadius: 22,
                border: `4px solid ${interpolateColors(level, [0, 1], [theme.line, theme.accent])}`,
                background: interpolateColors(level, [0, 1], [theme.card, theme.accentSoft]),
                color: interpolateColors(level, [0, 1], [theme.ink, theme.accent]),
                opacity: shown, transform: `translateY(${(1 - shown) * 30 - level * 8}px)`,
                boxShadow: `0 ${6 + level * 10}px ${18 + level * 18}px rgba(29, 36, 51, ${0.06 + level * 0.06})`,
              }}>
                {point}
              </div>
            );
          })}
        </div>
      ) : null}
    </SceneFrame>
  );
};
