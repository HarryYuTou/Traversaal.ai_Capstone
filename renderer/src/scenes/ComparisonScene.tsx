import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {SlideIcon} from './SlideIcon';
import {appear, ease, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'comparison'}>; label: string};

/** Two labelled columns side by side; each appears and highlights when the narration turns to it. */
export const ComparisonScene: React.FC<Props> = ({scene, label}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const sides = ['left', 'right'] as const;
  const starts = sides.map((side, index) =>
    revealFrame(scene.lines, scene.from, (line) => line.highlightSide === side, 6 + index * 8));
  const shown = starts.map((start) => appear(frame, start, fps));
  return (
    <SceneFrame label={label} title={scene.visual.title}>
      <div style={{flex: 1, display: 'flex', alignItems: 'center', marginTop: 20}}>
        <div style={{width: '100%', display: 'flex', alignItems: 'stretch', gap: 40}}>
          {sides.map((side, index) => {
            const column = scene.visual[side];
            const level = highlightLevel(scene.lines, scene.from, frame, (line) => line.highlightSide === side);
            return (
              <React.Fragment key={side}>
                {index === 1 ? (
                  <div style={{flex: '0 0 auto', alignSelf: 'center', width: 92, height: 92, borderRadius: 46,
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 34, fontWeight: 800,
                    color: theme.muted, background: theme.card, border: `4px solid ${theme.line}`,
                    opacity: Math.max(shown[0], shown[1]), transform: `scale(${0.6 + 0.4 * Math.max(shown[0], shown[1])})`}}>
                    vs
                  </div>
                ) : null}
                <div style={{
                  flex: 1, padding: '38px 44px 44px', borderRadius: 26,
                  border: `5px solid ${interpolateColors(level, [0, 1], [theme.line, theme.accent])}`,
                  background: interpolateColors(level, [0, 1], [theme.card, theme.accentSoft]),
                  opacity: shown[index], transform: `translateY(${(1 - shown[index]) * 30 - level * 10}px)`,
                  boxShadow: `0 ${8 + level * 12}px ${20 + level * 20}px ${theme.shadow(0.07 + level * 0.06)}`,
                }}>
                  <div style={{fontSize: 46, fontWeight: 750, marginBottom: 26, display: 'flex', alignItems: 'center',
                    gap: 20, color: interpolateColors(level, [0, 1], [theme.ink, theme.accent])}}>
                    <SlideIcon name={column.icon} size={56} draw={ease(frame, starts[index], 26)}
                      color={interpolateColors(level, [0, 1], [theme.muted, theme.accent])} />
                    {column.label}
                  </div>
                  {column.points.map((point) => (
                    <div key={point} style={{display: 'flex', gap: 18, fontSize: 36, lineHeight: 1.3, marginTop: 16}}>
                      <span style={{flex: '0 0 auto', width: 14, height: 14, marginTop: 16, borderRadius: 7,
                        background: interpolateColors(level, [0, 1], [theme.muted, theme.accent])}} />
                      <span>{point}</span>
                    </div>
                  ))}
                </div>
              </React.Fragment>
            );
          })}
        </div>
      </div>
    </SceneFrame>
  );
};
