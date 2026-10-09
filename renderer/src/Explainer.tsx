import React from 'react';
import {AbsoluteFill, Html5Audio, Sequence, staticFile} from 'remotion';
import {Captions, ProgressBar} from './Overlays';
import {ChapterCard, TitleCard} from './scenes/Cards';
import {ConceptScene} from './scenes/ConceptScene';
import {FlowScene} from './scenes/FlowScene';
import {theme} from './theme';
import type {Timeline} from './types';

const lengthText = (timeline: Timeline) => {
  const minutes = Math.round(timeline.durationInFrames / timeline.fps / 60);
  const length = minutes >= 1 ? `about ${minutes} minute${minutes === 1 ? '' : 's'}` : 'under a minute';
  const chapters = timeline.chapters.length;
  return chapters ? `${chapters} chapters · ${length}` : length;
};

/** The whole video: title card, chapter cards, scenes, captions and progress, over one narration track. */
export const Explainer: React.FC<Timeline> = (timeline) => {
  const chapters = new Map(timeline.chapters.map((chapter) => [chapter.id, chapter]));
  const lines = timeline.scenes.flatMap((scene) => scene.lines);
  return (
    <AbsoluteFill style={{background: theme.bg, color: theme.ink, fontFamily: theme.font}}>
      {timeline.audio.path ? <Html5Audio src={staticFile(timeline.audio.path)} /> : null}
      <Sequence durationInFrames={timeline.titleFrames} name="Title">
        <TitleCard title={timeline.title} subtitle={lengthText(timeline)} />
      </Sequence>
      {timeline.chapters.map((chapter) => (
        <Sequence key={chapter.id} from={chapter.from} durationInFrames={chapter.cardFrames}
          name={`Chapter ${chapter.number}`}>
          <ChapterCard chapter={chapter} total={timeline.chapters.length} />
        </Sequence>
      ))}
      {timeline.scenes.map((scene) => {
        const chapter = scene.chapterId ? chapters.get(scene.chapterId) : undefined;
        const label = chapter ? `Chapter ${chapter.number} · ${chapter.title}` : timeline.title;
        return (
          <Sequence key={scene.id} from={scene.from} durationInFrames={scene.durationInFrames} name={scene.id}>
            {scene.template === 'concept'
              ? <ConceptScene scene={scene} label={label} />
              : <FlowScene scene={scene} label={label} />}
          </Sequence>
        );
      })}
      <Captions lines={lines} />
      <ProgressBar chapters={timeline.chapters} />
    </AbsoluteFill>
  );
};
