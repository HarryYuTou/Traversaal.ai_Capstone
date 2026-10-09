import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {theme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {appear, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'flow'}>; label: string};

const Arrow: React.FC<{progress: number}> = ({progress}) => (
  <svg width={96} height={40} viewBox="0 0 96 40" style={{flex: '0 0 auto', opacity: progress}}>
    <line x1={4} y1={20} x2={4 + 74 * progress} y2={20} stroke={theme.muted} strokeWidth={5} strokeLinecap="round" />
    <path d="M 74 8 L 90 20 L 74 32" fill="none" stroke={theme.muted} strokeWidth={5} strokeLinecap="round"
      strokeLinejoin="round" opacity={progress >= 0.95 ? 1 : 0} />
  </svg>
);

/** Two to four steps from left to right; each step and its arrow appear when the narration reaches it. */
export const FlowScene: React.FC<Props> = ({scene, label}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return (
    <SceneFrame durationInFrames={scene.durationInFrames} label={label} title={scene.visual.title}>
      <div style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 18}}>
        {scene.visual.nodes.map((node, index) => {
          const matches = (line: {highlightNodeId?: string}) => line.highlightNodeId === node.id;
          const start = revealFrame(scene.lines, scene.from, matches, 6 + index * 4);
          const shown = appear(frame, start, fps);
          const level = highlightLevel(scene.lines, scene.from, frame, matches);
          return (
            <React.Fragment key={node.id}>
              {index > 0 ? <Arrow progress={appear(frame, start - 6, fps)} /> : null}
              <div style={{
                flex: '0 1 340px', minHeight: 190, display: 'flex', alignItems: 'center', justifyContent: 'center',
                textAlign: 'center', fontSize: 40, lineHeight: 1.25, fontWeight: 650, padding: '36px 30px',
                borderRadius: 26, border: `5px solid ${interpolateColors(level, [0, 1], [theme.line, theme.accent])}`,
                background: interpolateColors(level, [0, 1], [theme.card, theme.accentSoft]),
                color: interpolateColors(level, [0, 1], [theme.ink, theme.accent]),
                opacity: shown,
                transform: `translateY(${(1 - shown) * 30 - level * 12}px) scale(${1 + level * 0.04})`,
                boxShadow: `0 ${8 + level * 12}px ${20 + level * 20}px rgba(29, 36, 51, ${0.07 + level * 0.06})`,
              }}>
                {node.label}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </SceneFrame>
  );
};
