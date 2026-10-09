import React from 'react';
import {CalculateMetadataFunction, Composition} from 'remotion';
import {demo} from './demo';
import {Explainer} from './Explainer';
import type {Timeline} from './types';

// Size and length come from the timeline passed with --props; the demo is only for Remotion Studio.
const fromTimeline: CalculateMetadataFunction<Timeline> = ({props}) => ({
  durationInFrames: props.durationInFrames,
  fps: props.fps,
  width: props.width,
  height: props.height,
});

export const RemotionRoot: React.FC = () => (
  <Composition
    id="Explainer"
    component={Explainer}
    defaultProps={demo}
    calculateMetadata={fromTimeline}
    durationInFrames={demo.durationInFrames}
    fps={demo.fps}
    width={demo.width}
    height={demo.height}
  />
);
