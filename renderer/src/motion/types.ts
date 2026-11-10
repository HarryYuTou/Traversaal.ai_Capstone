export type MotionColor = 'ink' | 'accent' | 'secondary' | 'muted';
export type EntityKind = 'planet' | 'moon' | 'spacecraft' | 'lander' | 'lander-base' | 'lander-ascent' | 'rocket' | 'satellite'
  | 'person' | 'packet' | 'server' | 'laptop' | 'cloud' | 'coin' | 'box' | 'marker' | 'gauge' | 'counter' | 'workbench' | 'custom';

export type MotionEntity = {
  id: string; kind: EntityKind; x: number; y: number; size: number; rotation: number;
  opacity: number; value: number; color: MotionColor; label: string;
  /** Compiler-owned initial appearance keeps waiting parcels consistent across service shots. */
  packingState?: 'open' | 'prepared' | 'sealed';
  /** References a scene-owned, model-authored articulated SVG asset. */
  rigId?: string;
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
/** Semantic drawing instructions, separate from position and from process completion counts. */
export type MotionCueKind = 'pack' | 'scan' | 'send' | 'receive' | 'thrust' | 'compute';
export type MotionCue = {
  entityId: string; kind: MotionCueKind; from: number; durationInFrames: number;
  startLine?: number; endLine?: number; startOffset?: number; endOffset?: number;
  /** An unfinished process may prepare a package but cannot show its finished seal. */
  complete?: boolean;
  /** The actor was already in service when this shot began; retain its prepared package. */
  continued?: boolean;
};
export type MotionVisual = {
  title: string; entities: MotionEntity[]; paths: MotionPath[]; actions: MotionAction[];
  activities?: MotionActivity[];
  cues?: MotionCue[];
  rigs?: CustomRig[];
  performances?: RigPerformance[];
  contacts?: MotionContact[];
};

/** A local source point is translated onto a target point, then retains its offset at release. */
export type MotionContact = {
  entityId: string; partId: string; x: number; y: number;
  targetId: string; targetPartId: string; targetX: number; targetY: number;
  startLine: number; endLine: number; startOffset: number; endOffset: number;
  approach: number; from: number; durationInFrames: number; approachFrames: number;
};

export type RigColor = MotionColor | 'paper' | 'soft' | 'line' | 'none' | `#${string}`;
export type RigShape = {
  kind: 'ellipse' | 'rect' | 'path'; x: number; y: number; width: number; height: number;
  radius: number; path: string; fill: RigColor; stroke: RigColor; strokeWidth: number;
};
export type RigTransform = {x: number; y: number; rotation: number; scaleX: number; scaleY: number; opacity: number};
export type RigPart = RigTransform & {id: string; parentId: string; shapes: RigShape[]};
export type RigProperty = keyof RigTransform;
export type RigKeyframe = {at: number; value: number; easing: 'linear' | 'ease-in-out' | 'ease-out' | 'smooth'};
/** Translation/rotation/opacity tracks are offsets; scale tracks are multipliers. */
export type RigTrack = {partId: string; property: RigProperty; keyframes: RigKeyframe[]};
export type RigClip = {id: string; tracks: RigTrack[]};
export type CustomRig = {id: string; parts: RigPart[]; clips: RigClip[]};
export type RigPerformance = {
  entityId: string; clipId: string; startLine: number; endLine: number;
  startOffset: number; endOffset: number; repeat: number; from: number; durationInFrames: number;
};
