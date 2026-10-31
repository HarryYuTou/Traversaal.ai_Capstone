import React, {useMemo} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {useTheme, type Theme} from '../theme';
import type {ProcessTrace, TimelineScene} from '../types';
import {compileMotion, displayedPaths, entityAtFrame, toStage} from './engine';
import {Illustration, mixColor, type Palette} from './Illustration';
import {placeActorLabels, planLabelSlots, sceneFrames} from './labels';
import {fitMotionViewport, motionStageRect} from './camera';
import {illustrationPoseAtFrame} from './pose';
import {processStageLayout, processStateAtFrame, stationStateAtFrame, type ProcessSnapshot} from './processState';
import type {ProcessPresentation} from './processPresentation';
import {LookContext} from './sketch';

type Props = {scene: Extract<TimelineScene, {template: 'motion'}>; label: string; presentation?: ProcessPresentation};

// Frames for a changed count to roll from its old value to the new one.
const ROLL_FRAMES = 9;
const smooth = (value: number) => {
  const t = Math.max(0, Math.min(1, value));
  return t * t * (3 - 2 * t);
};

/** Illustration materials on the theme's own backdrop, so motion scenes and cards share one look. */
const paletteFor = (theme: Theme): Palette => theme.name === 'night'
  ? {paper: '#111d2c', soft: '#29394a', ink: '#eee9dc', accent: '#eabd67', secondary: '#83b9b0',
    muted: '#9ca99e', line: '#3a4b55'}
  : {paper: '#ffffff', soft: '#e4e8ef', ink: theme.ink, accent: '#dc7451', secondary: '#548e85',
    muted: '#8d95a3', line: theme.line};

/** A count that rolls to its new value, the old one sliding up and out, instead of the strip blinking. */
const RollingCount: React.FC<{count: (frame: number) => number; frame: number; ink: string; accent: string}> = (
  {count, frame, ink, accent}) => {
  const now = count(frame);
  let changed = frame;
  while (changed > frame - ROLL_FRAMES && count(changed - 1) === now) changed--;
  const rolling = changed > frame - ROLL_FRAMES;
  const t = rolling ? smooth((frame - changed + 1) / ROLL_FRAMES) : 1;
  return <span style={{display: 'inline-block', position: 'relative', overflow: 'hidden', verticalAlign: 'top',
    height: '1.2em', minWidth: '0.62em', textAlign: 'center', color: mixColor(accent, ink, t), fontWeight: 650}}>
    {rolling ? <span style={{position: 'absolute', left: 0, right: 0, opacity: 1 - t,
      transform: `translateY(${-t * 100}%)`, color: ink}}>{count(changed - 1)}</span> : null}
    <span style={{display: 'inline-block', opacity: t, transform: `translateY(${(1 - t) * 100}%)`}}>{now}</span>
  </span>;
};

const ProcessCounts: React.FC<{trace: ProcessTrace; frame: number; ink: string; accent: string}> = (
  {trace, frame, ink, accent}) => {
  const counter = (pick: (snapshot: ProcessSnapshot) => number) =>
    (at: number) => pick(processStateAtFrame(trace, at));
  return <>
    Waiting <RollingCount count={counter((s) => s.waiting)} frame={frame} ink={ink} accent={accent} />
    {' · '}In service <RollingCount count={counter((s) => s.inService)} frame={frame} ink={ink} accent={accent} />
    {' · '}Unfinished <RollingCount count={counter((s) => s.unfinished)} frame={frame} ink={ink} accent={accent} />
  </>;
};

/** A shared illustrated stage: actors perform the explanation, with only a title and small labels. */
export const MotionScene: React.FC<Props> = ({scene, label, presentation}) => {
  const theme = useTheme();
  const look = React.useContext(LookContext);
  const frame = scene.from + useCurrentFrame();
  const program = useMemo(() => compileMotion(scene.visual), [scene.visual]);
  // One camera for the whole scene (and for every related process shot): nothing re-frames mid-scene.
  const viewport = useMemo(() => presentation?.viewport ?? fitMotionViewport(program), [program, presentation]);
  // Each label keeps one side for the whole scene (process shots: for the whole run of related shots).
  const slots = useMemo(() => presentation?.labelSlots
    ?? planLabelSlots([{program, frames: sceneFrames(scene.from, scene.durationInFrames)}]),
  [program, presentation, scene.from, scene.durationInFrames]);
  const {width, height} = useVideoConfig();
  const baseStage = motionStageRect(width, height);
  const processLayout = scene.processTrace ? processStageLayout(baseStage, height) : null;
  const stage = baseStage;
  const palette = paletteFor(theme);
  const prefix = scene.id.replace(/[^a-zA-Z0-9_-]/g, '-');
  const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
  const title = <h1 style={{...(processLayout ? {padding: `0 ${processLayout.inset}px`, flexShrink: 0,
    fontSize: processLayout.titleFontSize, overflowWrap: 'anywhere' as const} :
    {position: 'absolute' as const, left: 110, right: 110, top: 99, fontSize: 56}),
    margin: 0, lineHeight: 1.14, fontWeight: 750, letterSpacing: '-0.025em'}}>{scene.visual.title}</h1>;
  const artwork = <svg viewBox={`${viewport.x} ${viewport.y} ${viewport.width} ${viewport.height}`}
        width={processLayout ? '100%' : stage.width} height={processLayout ? '100%' : stage.height}
        // A close-up sketch stage lets departing people walk past its edge before they fade.
        style={processLayout ? {display: 'block', overflow: look === 'sketch' ? 'visible' : 'hidden'} :
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
              <Illustration entity={entity} state={state} palette={palette} prefix={prefix} look={look}
                pose={illustrationPoseAtFrame(prepared, frame)}
                station={scene.processTrace ? stationStateAtFrame(scene.processTrace, entity.id, frame) : null} />
            </g>
          </g>;
        })}
        {/* Labels stay upright and keep a consistent reading size as the illustration rotates or scales. */}
        {placeActorLabels(actors, viewport, slots).map(({actor: {prepared, state}, x, y, fontSize}) => {
          return <text key={`${prepared.entity.id}-label`} x={x} y={y}
            textAnchor="middle" fill={palette.ink} opacity={state.opacity} fontSize={fontSize} fontWeight={650}
            stroke={palette.paper} strokeWidth={7} strokeLinejoin="round" paintOrder="stroke">
            {prepared.entity.label}
          </text>;
        })}
      </svg>;
  // No backdrop of its own: the video's shared moving backdrop shows through, as it does behind every card.
  return (
    <AbsoluteFill style={{color: theme.ink, fontFamily: theme.font}}>
      <div style={{position: 'absolute', left: processLayout ? processLayout.container.x + processLayout.inset : 110,
        right: processLayout ? processLayout.container.x + processLayout.inset : 110,
        top: processLayout ? height * 65 / 1080 : 65, fontSize: processLayout ? height * 22 / 1080 : 22, fontWeight: 600,
        letterSpacing: '0.06em', color: theme.muted}}>{label}</div>
      {scene.processTrace && processLayout ? <div style={{position: 'absolute', left: processLayout.container.x,
        top: processLayout.container.y, width: processLayout.container.width, height: processLayout.container.height,
        display: 'flex', flexDirection: 'column'}}>
        {title}
        {/* The counts stay on screen and roll to each new value, rather than the strip fading out and in. */}
        <div style={{padding: `0 ${processLayout.inset}px`, height: processLayout.strip.height, flexShrink: 0,
          marginTop: processLayout.strip.marginTop, marginBottom: processLayout.strip.marginBottom,
          fontSize: processLayout.strip.fontSize, lineHeight: 1.2, fontVariantNumeric: 'tabular-nums',
          color: theme.muted, whiteSpace: 'nowrap'}}>
          <ProcessCounts trace={scene.processTrace} frame={frame} ink={theme.ink} accent={palette.accent} />
        </div>
        <div style={{flex: 1, minHeight: 0}}>{artwork}</div>
      </div> : <>{title}{artwork}</>}
    </AbsoluteFill>
  );
};
