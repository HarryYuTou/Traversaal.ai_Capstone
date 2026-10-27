import React, {useMemo} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme} from '../theme';
import type {TimelineScene} from '../types';
import {compileMotion, displayedPaths, entityAtFrame, toStage} from './engine';
import {Illustration, type Palette} from './Illustration';
import {placeActorLabels} from './labels';
import {fitMotionViewport, motionStageRect} from './camera';
import {illustrationPoseAtFrame} from './pose';
import {processStageLayout, processStateAtFrame, stationStateAtFrame} from './processState';
import {processViewportAtFrame, type ProcessPresentation} from './processPresentation';

type Props = {scene: Extract<TimelineScene, {template: 'motion'}>; label: string; presentation?: ProcessPresentation};

/** A shared illustrated stage: actors perform the explanation, with only a title and small labels. */
export const MotionScene: React.FC<Props> = ({scene, label, presentation}) => {
  const theme = useTheme();
  const frame = scene.from + useCurrentFrame();
  const program = useMemo(() => compileMotion(scene.visual), [scene.visual]);
  const wideViewport = useMemo(() => presentation?.viewport ?? fitMotionViewport(program), [program, presentation]);
  const {width, height, fps} = useVideoConfig();
  const viewport = scene.processTrace && presentation
    ? processViewportAtFrame(program, scene.processTrace, wideViewport, frame, fps) : wideViewport;
  const baseStage = motionStageRect(width, height);
  const processLayout = scene.processTrace ? processStageLayout(baseStage, height) : null;
  const stage = baseStage;
  const snapshot = scene.processTrace ? processStateAtFrame(scene.processTrace, frame) : null;
  const night = theme.name === 'night';
  const palette: Palette = {paper: night ? '#111d2c' : '#fbf8f0', soft: night ? '#29394a' : '#e8e3d7',
    ink: night ? '#eee9dc' : '#293333', accent: night ? '#eabd67' : '#dc7451',
    secondary: night ? '#83b9b0' : '#548e85', muted: night ? '#9ca99e' : '#8a9488',
    line: night ? '#3a4b55' : '#d9d9cc'};
  const prefix = scene.id.replace(/[^a-zA-Z0-9_-]/g, '-');
  const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
  const title = <h1 style={{...(processLayout ? {padding: `0 ${processLayout.inset}px`, flexShrink: 0,
    fontSize: processLayout.titleFontSize, overflowWrap: 'anywhere' as const} :
    {position: 'absolute' as const, left: 110, right: 110, top: 99, fontSize: 56}),
    margin: 0, lineHeight: 1.14, fontWeight: 750, letterSpacing: '-0.025em'}}>{scene.visual.title}</h1>;
  const artwork = <svg viewBox={`${viewport.x} ${viewport.y} ${viewport.width} ${viewport.height}`}
        width={processLayout ? '100%' : stage.width} height={processLayout ? '100%' : stage.height}
        style={processLayout ? {display: 'block', overflow: 'hidden'} :
          {position: 'absolute', top: stage.y, left: stage.x, overflow: 'hidden'}}>
        {(!scene.processTrace ? displayedPaths(program, frame) : []).map(({key, path, geometry, from, progress}) => {
          const shown = Math.max(0, Math.min(1, (frame - from) / 10));
          return <g key={key} opacity={shown} fill="none" stroke={palette[path.color]} strokeLinecap="round">
            <path d={geometry.d} strokeWidth={2} strokeDasharray="3 9" opacity={0.23} />
            <path d={geometry.d} strokeWidth={2.5} pathLength={1} strokeDasharray={`${progress} 1`}
              opacity={progress > 0 ? 0.55 : 0} />
          </g>;
        })}
        {actors.map(({prepared, state}) => {
          const {entity} = prepared;
          const point = toStage(state);
          return <g key={entity.id} opacity={state.opacity} transform={`translate(${point.x} ${point.y})`}>
            <g transform={`rotate(${state.rotation % 360}) scale(${state.size})`}>
              <Illustration entity={entity} state={state} palette={palette} prefix={prefix}
                pose={illustrationPoseAtFrame(prepared, frame)}
                station={scene.processTrace ? stationStateAtFrame(scene.processTrace, entity.id, frame) : null} />
            </g>
          </g>;
        })}
        {/* Labels stay upright and keep a consistent reading size as the illustration rotates or scales. */}
        {placeActorLabels(actors, viewport).map(({actor: {prepared, state}, x, y, fontSize}) => {
          return <text key={`${prepared.entity.id}-label`} x={x} y={y}
            textAnchor="middle" fill={palette.ink} opacity={state.opacity} fontSize={fontSize} fontWeight={650}
            stroke={palette.paper} strokeWidth={7} strokeLinejoin="round" paintOrder="stroke">
            {prepared.entity.label}
          </text>;
        })}
      </svg>;
  return (
    <AbsoluteFill style={{background: palette.paper, color: palette.ink, fontFamily: theme.font}}>
      <AbsoluteFill style={{opacity: night ? 0.09 : 0.16,
        backgroundImage: `radial-gradient(${palette.muted} 0.8px, transparent 0.8px)`, backgroundSize: '9px 9px'}} />
      <div style={{position: 'absolute', left: processLayout ? processLayout.container.x + processLayout.inset : 110,
        right: processLayout ? processLayout.container.x + processLayout.inset : 110,
        top: processLayout ? height * 65 / 1080 : 65, fontSize: processLayout ? height * 22 / 1080 : 22, fontWeight: 600,
        letterSpacing: '0.06em', color: palette.muted}}>{label}</div>
      {snapshot && processLayout ? <div style={{position: 'absolute', left: processLayout.container.x,
        top: processLayout.container.y, width: processLayout.container.width, height: processLayout.container.height,
        display: 'flex', flexDirection: 'column'}}>
        {title}
        <div style={{padding: `0 ${processLayout.inset}px`, height: processLayout.strip.height, flexShrink: 0,
          marginTop: processLayout.strip.marginTop, marginBottom: processLayout.strip.marginBottom,
          fontSize: processLayout.strip.fontSize, lineHeight: 1.2, fontVariantNumeric: 'tabular-nums',
          color: palette.muted, opacity: snapshot.opacity}}>
          Waiting <span style={{color: palette.ink, fontWeight: 650}}>{snapshot.waiting}</span>
          {' · '}In service <span style={{color: palette.ink, fontWeight: 650}}>{snapshot.inService}</span>
          {' · '}Unfinished <span style={{color: palette.ink, fontWeight: 650}}>{snapshot.unfinished}</span>
        </div>
        <div style={{flex: 1, minHeight: 0}}>{artwork}</div>
      </div> : <>{title}{artwork}</>}
    </AbsoluteFill>
  );
};
