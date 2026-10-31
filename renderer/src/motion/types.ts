export type MotionColor = 'ink' | 'accent' | 'secondary' | 'muted';
export type EntityKind = 'planet' | 'moon' | 'spacecraft' | 'lander' | 'lander-base' | 'lander-ascent' | 'rocket' | 'satellite'
  | 'person' | 'packet' | 'server' | 'laptop' | 'cloud' | 'coin' | 'box' | 'marker' | 'gauge' | 'counter' | 'workbench';

export type MotionEntity = {
  id: string; kind: EntityKind; x: number; y: number; size: number; rotation: number;
  opacity: number; value: number; color: MotionColor; label: string;
};
export type MotionPoint = {x: number; y: number};
export type MotionPath = {id: string; points: MotionPoint[]; curved: boolean; closed: boolean; color: MotionColor};
export type ActionKind = 'move' | 'follow-path' | 'orbit' | 'opacity' | 'scale' | 'rotate' | 'value';
/** `walk` is compiler-only: a steady pace with gentle starts and stops, used for process travel. */
export type MotionEasing = 'linear' | 'ease-in-out' | 'ease-out' | 'walk';

/** from is an absolute video frame, compiled from the line anchors by Python. */
export type MotionAction = {
  entityId: string; kind: ActionKind; startLine: number; endLine: number;
  startOffset: number; endOffset: number; pathId: string; x: number; y: number;
  value: number; easing: MotionEasing; from: number; durationInFrames: number;
};
/** Event-compiled activity intervals use absolute video frames; they do not alter entity position. */
export type MotionActivity = {
  entityId: string; kind: 'work' | 'complete'; from: number; durationInFrames: number;
};
export type MotionVisual = {
  title: string; entities: MotionEntity[]; paths: MotionPath[]; actions: MotionAction[];
  activities?: MotionActivity[];
};
