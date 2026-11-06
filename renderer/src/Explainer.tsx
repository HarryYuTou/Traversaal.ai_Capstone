import React from 'react';
import {AbsoluteFill, Html5Audio, Sequence, staticFile} from 'remotion';
import {Backdrop, Shell} from './Backdrop';
import {Captions, ProgressBar} from './Overlays';
import {ChapterCard, TitleCard} from './scenes/Cards';
import {ComparisonScene} from './scenes/ComparisonScene';
import {ConceptScene} from './scenes/ConceptScene';
import {DefinitionScene} from './scenes/DefinitionScene';
import {EventTimelineScene} from './scenes/EventTimelineScene';
import {FlowScene} from './scenes/FlowScene';
import {MapScene} from './scenes/MapScene';
import {QuoteScene} from './scenes/QuoteScene';
import {StatScene} from './scenes/StatScene';
import {MotionScene} from './motion/MotionScene';
import {LookContext, loadSketchFont} from './motion/sketch';
import {processPresentations, type ProcessPresentation} from './motion/processPresentation';
import {motionBoundaryIsContinuous} from './motion/continuity';
import {ThemeContext, themes} from './theme';
import {transitionBetween} from './transitions';
import type {Timeline, TimelineScene} from './types';

const SceneView: React.FC<{scene: TimelineScene; label: string; presentation?: ProcessPresentation}> = ({scene, label, presentation}) => {
  switch (scene.template) {
    case 'concept':
      return <ConceptScene scene={scene} label={label} />;
    case 'flow':
      return <FlowScene scene={scene} label={label} />;
    case 'comparison':
      return <ComparisonScene scene={scene} label={label} />;
    case 'definition':
      return <DefinitionScene scene={scene} label={label} />;
    case 'timeline':
      return <EventTimelineScene scene={scene} label={label} />;
    case 'stat':
      return <StatScene scene={scene} label={label} />;
    case 'quote':
      return <QuoteScene scene={scene} label={label} />;
    case 'map':
      return <MapScene scene={scene} label={label} />;
    case 'motion':
      return <MotionScene scene={scene} label={label} presentation={presentation} />;
  }
};


type Part = {key: string; from: number; durationInFrames: number; content: React.ReactNode; stage?: number;
  continuousFromPrevious?: boolean};

/** The whole video: title card, chapter cards and scenes over a moving backdrop, with captions and progress. */
export const Explainer: React.FC<Timeline> = (timeline) => {
  const theme = themes[timeline.theme ?? 'light'] ?? themes.light;
  const chapters = new Map(timeline.chapters.map((chapter) => [chapter.id, chapter]));
  const lines = timeline.scenes.flatMap((scene) => scene.lines);
  // Only the sketch look needs its hand-lettered font, so other renders never fetch it.
  React.useMemo(() => timeline.look === 'sketch' && loadSketchFont(), [timeline.look]);
  // Hand-drawn figures carry fine linework, so the sketch look frames process stages closer.
  const presentations = React.useMemo(() => processPresentations(timeline.scenes, timeline.look === 'sketch'),
    [timeline.scenes, timeline.look]);
  const continuities = React.useMemo(() => timeline.scenes.map((scene, index) => {
    const previous = timeline.scenes[index - 1];
    return previous?.template === 'motion' && scene.template === 'motion'
      && motionBoundaryIsContinuous(previous, scene, timeline.fps);
  }), [timeline.scenes, timeline.fps]);
  const parts: Part[] = [
    {key: 'Title', from: 0, durationInFrames: timeline.titleFrames,
      content: <TitleCard title={timeline.title}
        subtitle={timeline.chapters.length ? `${timeline.chapters.length} chapters` : undefined} />},
    ...timeline.chapters.map((chapter) => ({
      key: `Chapter ${chapter.number}`, from: chapter.from, durationInFrames: chapter.cardFrames,
      content: <ChapterCard chapter={chapter} total={timeline.chapters.length} />,
    })),
    ...timeline.scenes.map((scene, index) => {
      const chapter = scene.chapterId ? chapters.get(scene.chapterId) : undefined;
      const label = chapter ? `Chapter ${chapter.number} · ${chapter.title}` : timeline.title;
      return {key: scene.id, from: scene.from, durationInFrames: scene.durationInFrames,
        stage: presentations.get(scene.id)?.group,
        continuousFromPrevious: continuities[index],
        content: <SceneView scene={scene} label={label} presentation={presentations.get(scene.id)} />};
    }),
  ].sort((a, b) => a.from - b.from);
  return (
    <ThemeContext.Provider value={theme}>
      <LookContext.Provider value={timeline.look ?? 'vector'}>
        <AbsoluteFill style={{background: theme.bg, color: theme.ink, fontFamily: theme.font}}>
          <Backdrop />
          {timeline.audio.path ? <Html5Audio src={staticFile(timeline.audio.path)} /> : null}
          {timeline.music?.path ? <Html5Audio src={staticFile(timeline.music.path)} /> : null}
          <AbsoluteFill>
            {parts.map((part, index) => {
              const last = index === parts.length - 1;
              const enter = transitionBetween(parts[index - 1], part);
              const exit = transitionBetween(part, parts[index + 1]);
              return (
                <Sequence key={part.key} name={part.key} from={part.from}
                  durationInFrames={part.durationInFrames}>
                  <Shell durationInFrames={part.durationInFrames} last={last} enter={enter} exit={exit}>
                    {part.content}
                  </Shell>
                </Sequence>
              );
            })}
          </AbsoluteFill>
          <Captions lines={lines} />
          <ProgressBar chapters={timeline.chapters} />
        </AbsoluteFill>
      </LookContext.Provider>
    </ThemeContext.Provider>
  );
};
