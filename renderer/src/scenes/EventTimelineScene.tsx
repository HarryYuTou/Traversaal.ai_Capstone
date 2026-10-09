import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {SlideIcon} from './SlideIcon';
import {appear, ease, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'timeline'}>; label: string};

const WIDTH = 1640;
const AXIS = 300;

/**
 * Two to five dated events along a line. The line draws itself first; each event drops onto it when the
 * narration reaches it, and a colored stretch of the line runs forward to the newest event.
 */
export const EventTimelineScene: React.FC<Props> = ({scene, label}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {events} = scene.visual;
  const slot = WIDTH / events.length;
  const xs = events.map((_, index) => slot * (index + 0.5));
  const starts = events.map((event, index) =>
    revealFrame(scene.lines, scene.from, (line) => line.highlightEventId === event.id, 10 + index * 8));
  const shown = starts.map((start) => appear(frame, start, fps));
  const levels = events.map((event) =>
    highlightLevel(scene.lines, scene.from, frame, (line) => line.highlightEventId === event.id));
  const focus = Math.max(...levels);
  const axis = ease(frame, 4, 24);
  const axisLeft = xs[0] - 90;
  const axisRight = xs[xs.length - 1] + 90;
  let reached = xs[0];
  xs.forEach((x, index) => {
    if (index > 0) {
      reached = Math.max(reached, xs[index - 1] + (x - xs[index - 1]) * ease(frame, starts[index] - 6, 18));
    }
  });
  const labelWidth = Math.min(420, slot - 28);
  return (
    <SceneFrame label={label} title={scene.visual.title}>
      <div style={{position: 'relative', flex: 1, marginTop: 10}}>
        <div style={{position: 'absolute', left: axisLeft, top: AXIS - 4, height: 8, borderRadius: 4,
          width: (axisRight - axisLeft) * axis, background: theme.line}} />
        <div style={{position: 'absolute', left: xs[0], top: AXIS - 4, height: 8, borderRadius: 4,
          width: Math.max(0, reached - xs[0]) * shown[0], background: theme.accent}} />
        {events.map((event, index) => {
          const level = levels[index];
          const dim = 1 - 0.5 * focus * (1 - level);
          const rise = (1 - shown[index]) * 26;
          const pulse = level * (16 + 5 * Math.sin(frame / 5));
          return (
            <React.Fragment key={event.id}>
              <div style={{position: 'absolute', left: xs[index] - labelWidth / 2, width: labelWidth, bottom: `calc(100% - ${AXIS - 44}px)`,
                display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 14, textAlign: 'center',
                opacity: shown[index] * dim, transform: `translateY(${-rise}px)`}}>
                <SlideIcon name={event.icon} size={64} draw={ease(frame, starts[index], 26)}
                  color={interpolateColors(level, [0, 1], [theme.muted, theme.accent])} />
                <div style={{fontSize: 58, lineHeight: 1.05, fontWeight: 800, fontVariantNumeric: 'tabular-nums',
                  color: interpolateColors(level, [0, 1], [theme.ink, theme.accent])}}>
                  {event.date}
                </div>
              </div>
              <div style={{position: 'absolute', left: xs[index] - 18 - pulse, top: AXIS - 18 - pulse,
                width: 36 + 2 * pulse, height: 36 + 2 * pulse, borderRadius: '50%', opacity: 0.35 * level,
                background: theme.accent}} />
              <div style={{position: 'absolute', left: xs[index] - 18, top: AXIS - 18, width: 36, height: 36,
                borderRadius: '50%', background: interpolateColors(level, [0, 1], [theme.card, theme.accent]),
                border: `6px solid ${theme.accent}`, transform: `scale(${shown[index] * (1 + 0.25 * level)})`}} />
              <div style={{position: 'absolute', left: xs[index] - labelWidth / 2, width: labelWidth, top: AXIS + 46,
                textAlign: 'center', fontSize: events.length > 4 ? 30 : 34, lineHeight: 1.3, fontWeight: 550,
                color: interpolateColors(level, [0, 1], [theme.muted, theme.ink]),
                opacity: shown[index] * dim, transform: `translateY(${rise}px)`}}>
                {event.label}
              </div>
            </React.Fragment>
          );
        })}
      </div>
    </SceneFrame>
  );
};
