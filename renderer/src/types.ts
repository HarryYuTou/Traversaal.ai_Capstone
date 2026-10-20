// The timeline written by `python -m capstone_script timeline` (video/timeline.json), plus the render
// options `render` adds in video/props.json. All positions are whole frames at `fps`; scene and line
// `from` values are absolute.
import type {ThemeName} from './theme';
import type {MotionVisual} from './motion/types';
export type {MotionVisual, MotionEntity, MotionPath, MotionAction} from './motion/types';

export type TimelineLine = {
  id: string;
  text: string;
  from: number;
  durationInFrames: number;
  highlightPointIndex?: number;
  highlightNodeId?: string;
  highlightSide?: 'left' | 'right';
  highlightPart?: 'term' | 'definition' | 'example';
  highlightEventId?: string;
  highlightStatIndex?: number;
  highlightQuote?: boolean;
  highlightId?: string;
};

export type ConceptVisual = {title: string; statement: string; points: string[]; icon?: string};
export type FlowVisual = {title: string; nodes: {id: string; label: string; icon?: string}[]};
export type ComparisonColumn = {label: string; points: string[]; icon?: string};
export type ComparisonVisual = {title: string; left: ComparisonColumn; right: ComparisonColumn};
export type DefinitionVisual = {title: string; term: string; definition: string; example?: string; icon?: string};
export type DatedEvent = {id: string; date: string; label: string; icon?: string};
export type EventsVisual = {title: string; events: DatedEvent[]};
export type Stat = {value: number; prefix?: string; unit?: string; label: string; icon?: string};
export type StatVisual = {title: string; stats: Stat[]; note?: string};
export type QuoteVisual = {title: string; quote: string; author: string; context?: string};
export type MapArea = {id: string; label: string; countries: string[]};
export type MapPlace = {id: string; label: string; lon: number; lat: number};
export type MapVisual = {title: string; region: string; areas: MapArea[]; places: MapPlace[]; route: boolean};

export type ProcessOccupancy = {actorId: string; stationId: string};
export type ProcessPhase = {
  kind: 'arrive' | 'to-service' | 'compact-queue' | 'complete' | 'exit' | 'fade';
  actorIds: string[];
  from: number;
  durationInFrames: number;
};
export type ProcessTraceEvent = {
  kind: 'arrive' | 'start' | 'finish' | 'hold';
  from: number;
  durationInFrames: number;
  actorIds: string[];
  stationIds: string[];
  queueBefore: string[];
  queueAfter: string[];
  serviceBefore: ProcessOccupancy[];
  serviceAfter: ProcessOccupancy[];
  completedBefore: string[];
  completedAfter: string[];
  movementEndFrame: number;
  phases: ProcessPhase[];
};
export type ProcessTrace = {
  sourceTemplate: 'process';
  actorIds: string[];
  stationEntityIds: string[];
  initialQueue: string[];
  initialService: ProcessOccupancy[];
  finalQueue: string[];
  finalService: ProcessOccupancy[];
  completed: string[];
  events: ProcessTraceEvent[];
};

type SceneBase = {
  id: string;
  chapterId: string | null;
  from: number;
  durationInFrames: number;
  lines: TimelineLine[];
};

export type TimelineScene =
  | (SceneBase & {template: 'concept'; visual: ConceptVisual})
  | (SceneBase & {template: 'flow'; visual: FlowVisual})
  | (SceneBase & {template: 'comparison'; visual: ComparisonVisual})
  | (SceneBase & {template: 'definition'; visual: DefinitionVisual})
  | (SceneBase & {template: 'timeline'; visual: EventsVisual})
  | (SceneBase & {template: 'stat'; visual: StatVisual})
  | (SceneBase & {template: 'quote'; visual: QuoteVisual})
  | (SceneBase & {template: 'map'; visual: MapVisual})
  | (SceneBase & {template: 'motion'; visual: MotionVisual; processTrace?: ProcessTrace});

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
  // Render options; a bare timeline.json has neither and renders in the light theme without music.
  theme?: ThemeName;
  music?: {path: string} | null;
};
