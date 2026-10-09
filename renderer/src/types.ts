// The timeline written by `python -m capstone_script timeline` (video/timeline.json).
// All positions are whole frames at `fps`; scene and line `from` values are absolute.

export type TimelineLine = {
  id: string;
  text: string;
  from: number;
  durationInFrames: number;
  highlightPointIndex?: number;
  highlightNodeId?: string;
};

export type ConceptVisual = {title: string; statement: string; points: string[]};
export type FlowVisual = {title: string; nodes: {id: string; label: string}[]};

type SceneBase = {
  id: string;
  chapterId: string | null;
  from: number;
  durationInFrames: number;
  lines: TimelineLine[];
};

export type TimelineScene =
  | (SceneBase & {template: 'concept'; visual: ConceptVisual})
  | (SceneBase & {template: 'flow'; visual: FlowVisual});

export type TimelineChapter = {
  id: string;
  number: number;
  title: string;
  from: number;
  cardFrames: number;
  durationInFrames: number;
};

export type Timeline = {
  schemaVersion: string;
  projectId: string;
  title: string;
  fps: number;
  width: number;
  height: number;
  durationInFrames: number;
  titleFrames: number;
  audio: {path: string; sampleRate: number; channels: number};
  chapters: TimelineChapter[];
  scenes: TimelineScene[];
};
