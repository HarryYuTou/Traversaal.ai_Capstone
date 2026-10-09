import React from 'react';
import {interpolateColors, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {SlideIcon} from './SlideIcon';
import {appear, ease, highlightLevel, revealFrame} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'stat'}>; label: string};

const SIZES = [230, 172, 136];
const COUNT_FRAMES = 42;

// As many decimals as the plan wrote, so 2.5 counts up as 0.0 ... 2.5 and 70 as whole numbers.
const decimalsOf = (value: number) => {
  const text = String(value);
  return text.includes('.') ? Math.min(2, text.split('.')[1].length) : 0;
};

const format = (value: number, decimals: number) =>
  value.toLocaleString('en-US', {minimumFractionDigits: decimals, maximumFractionDigits: decimals});

/** One to three large numbers; each counts up from zero when the narration reaches it. */
export const StatScene: React.FC<Props> = ({scene, label}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const {stats, note} = scene.visual;
  const size = SIZES[stats.length - 1];
  const noteShown = ease(frame, 30, 20);
  return (
    <SceneFrame label={label} title={scene.visual.title}>
      <div style={{flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'space-around', gap: 40}}>
        {stats.map((stat, index) => {
          const matches = (line: {highlightStatIndex?: number}) => line.highlightStatIndex === index;
          const start = revealFrame(scene.lines, scene.from, matches, 10 + index * 14);
          const shown = appear(frame, start, fps);
          const count = ease(frame, start, COUNT_FRAMES);
          const level = highlightLevel(scene.lines, scene.from, frame, matches);
          const color = interpolateColors(level, [0, 1], [theme.ink, theme.accent]);
          return (
            <div key={index} style={{flex: '1 1 0', display: 'flex', flexDirection: 'column', alignItems: 'center',
              textAlign: 'center', opacity: shown, transform: `translateY(${(1 - shown) * 30}px) scale(${1 + 0.04 * level})`}}>
              <SlideIcon name={stat.icon} size={Math.round(size * 0.42)} draw={ease(frame, start, 28)}
                color={interpolateColors(level, [0, 1], [theme.muted, theme.accent])} />
              <div style={{display: 'flex', alignItems: 'baseline', justifyContent: 'center', gap: size * 0.06,
                marginTop: stat.icon ? 18 : 0, color, fontWeight: 800, lineHeight: 1, whiteSpace: 'nowrap'}}>
                {stat.prefix ? <span style={{fontSize: size * 0.62}}>{stat.prefix}</span> : null}
                <span style={{fontSize: size, fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em'}}>
                  {format(stat.value * count, decimalsOf(stat.value))}
                </span>
                {stat.unit ? <span style={{fontSize: size * 0.36, fontWeight: 700}}>{stat.unit}</span> : null}
              </div>
              <div style={{width: 120 + 120 * level, height: 8, borderRadius: 4, margin: '26px 0 22px',
                background: interpolateColors(level, [0, 1], [theme.line, theme.accent])}} />
              <div style={{fontSize: stats.length > 2 ? 32 : 38, lineHeight: 1.3, fontWeight: 550, color: theme.muted,
                maxWidth: 520}}>
                {stat.label}
              </div>
            </div>
          );
        })}
      </div>
      {note ? (
        <div style={{fontSize: 30, lineHeight: 1.35, fontStyle: 'italic', color: theme.muted, textAlign: 'center',
          opacity: noteShown}}>
          {note}
        </div>
      ) : null}
    </SceneFrame>
  );
};
