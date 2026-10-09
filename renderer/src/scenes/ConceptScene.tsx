import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {SlideIcon} from './SlideIcon';
import {appear, ease, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'concept'}>; label: string};

/** Title, one statement and up to three points; each point appears when the narration reaches it. */
export const ConceptScene: React.FC<Props> = ({scene, label}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {points} = scene.visual;
  const lone = points.length === 0;
  const statement = ease(frame, 8, 16);
  return (
    <SceneFrame label={label} title={scene.visual.title}>
      {/* The content sits in the middle of the space below the title; without points, the statement and
          icon grow instead of leaving the slide half empty. */}
      <div style={{flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingBottom: 30}}>
        <div style={{display: 'flex', alignItems: 'center', gap: lone ? 52 : 36}}>
          {scene.visual.icon ? (
            <div style={{flex: '0 0 auto', width: lone ? 210 : 132, height: lone ? 210 : 132, borderRadius: lone ? 48 : 32,
              background: theme.accentSoft, display: 'flex', alignItems: 'center', justifyContent: 'center',
              transform: `scale(${0.85 + 0.15 * statement})`}}>
              <SlideIcon name={scene.visual.icon} size={lone ? 120 : 76} color={theme.accent} draw={ease(frame, 6, 30)} />
            </div>
          ) : null}
          <p style={{margin: 0, fontSize: lone ? 56 : 44, lineHeight: 1.35, color: lone ? theme.ink : theme.muted,
            maxWidth: 1400, opacity: statement, transform: `translateY(${(1 - statement) * 18}px)`}}>
            {scene.visual.statement}
          </p>
        </div>
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
                  boxShadow: `0 ${6 + level * 10}px ${18 + level * 18}px ${theme.shadow(0.06 + level * 0.06)}`,
                }}>
                  {point}
                </div>
              );
            })}
          </div>
        ) : null}
      </div>
    </SceneFrame>
  );
};
