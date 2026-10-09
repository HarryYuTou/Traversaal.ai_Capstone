import React from 'react';
import {useCurrentFrame} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {SceneFrame} from './SceneFrame';
import {ease} from './timing';

type Props = {scene: Extract<TimelineScene, {template: 'quote'}>; label: string};

/**
 * A quotation in large serif type. Its words light up in order while the line marked highlightQuote reads
 * it (or over the first second and a half when no line does); then the speaker's name appears.
 */
export const QuoteScene: React.FC<Props> = ({scene, label}) => {
  const theme = useTheme();
  const frame = useCurrentFrame();
  const {quote, author, context} = scene.visual;
  const reading = scene.lines.find((line) => line.highlightQuote);
  const start = reading ? reading.from - scene.from : 12;
  const span = reading ? reading.durationInFrames * 0.92 : 45;
  const words = quote.split(' ');
  const size = quote.length <= 80 ? 72 : quote.length <= 150 ? 60 : 52;
  const mark = ease(frame, 4, 20);
  const credit = ease(frame, start + span + 4, 16);
  return (
    <SceneFrame label={label} title={scene.visual.title}>
      <div style={{position: 'relative', flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center',
        padding: '0 60px 0 110px'}}>
        <div style={{position: 'absolute', left: 0, top: '50%', marginTop: -size * 2.6, fontFamily: theme.serif,
          fontSize: 300, lineHeight: 1, color: theme.accent, opacity: 0.35 * mark,
          transform: `translateY(${(1 - mark) * 30}px)`}}>
          {'“'}
        </div>
        <div style={{fontFamily: theme.serif, fontStyle: 'italic', fontSize: size, lineHeight: 1.32, maxWidth: 1460,
          textWrap: 'balance'}}>
          {words.map((word, index) => {
            const lit = ease(frame, start + (index / words.length) * span, 8);
            return (
              <React.Fragment key={index}>
                {index > 0 ? ' ' : null}
                <span style={{opacity: 0.16 + 0.84 * lit}}>{word}</span>
              </React.Fragment>
            );
          })}
        </div>
        <div style={{marginTop: 44, opacity: credit, transform: `translateX(${(1 - credit) * -24}px)`}}>
          <div style={{fontSize: 40, fontWeight: 700, color: theme.accent}}>{`— ${author}`}</div>
          {context ? <div style={{marginTop: 10, fontSize: 30, color: theme.muted}}>{context}</div> : null}
        </div>
      </div>
    </SceneFrame>
  );
};
