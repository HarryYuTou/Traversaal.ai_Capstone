import type {TimelineScene, ProcessTrace} from '../types';
import {compileMotion, entityAtFrame, type MotionProgram} from './engine';
import {fitMotionViewport, fitProcessViewport, type StageViewport} from './camera';

type ProcessScene = Extract<TimelineScene, {template: 'motion'}>;
export type ProcessPresentation = {viewport: StageViewport};
const sharedIds = (a: string[], b: string[]) => a.some((id) => b.includes(id));

/** Consecutive shots of the same cast share an establishing frame. Authored colors stay unchanged. */
export const processPresentations = (scenes: TimelineScene[]): Map<string, ProcessPresentation> => {
  const result = new Map<string, ProcessPresentation>();
  let group: ProcessScene[] = [];
  const flush = () => {
    if (!group.length) return;
    const viewport = fitProcessViewport(group.map((scene) => compileMotion(scene.visual)));
    for (const scene of group) result.set(scene.id, {viewport});
    group = [];
  };
  for (const scene of scenes) {
    if (scene.template !== 'motion' || !scene.processTrace) {flush(); continue;}
    const previous = group.at(-1);
    if (previous && (previous.chapterId !== scene.chapterId ||
        !sharedIds(previous.processTrace!.actorIds, scene.processTrace.actorIds) ||
        !sharedIds(previous.processTrace!.stationEntityIds, scene.processTrace.stationEntityIds))) flush();
    group.push(scene);
  }
  flush();
  return result;
};

/** A detail shot can appear only in a long authored hold. Movement always has the complete wide
 * frame; both camera endpoints contain the stationary cast, so their interpolation is safe too.
 * The shot is derived solely from absolute frames and never follows a moving actor.
 */
export const processViewportAtFrame = (
  program: MotionProgram, trace: ProcessTrace, wide: StageViewport, frame: number, fps: number,
): StageViewport => {
  const hold = trace.events.find((event) => event.kind === 'hold' &&
    frame >= event.from && frame <= event.from + event.durationInFrames);
  const transition = Math.max(1, Math.round(fps * 0.8));
  const guard = Math.max(1, Math.round(fps * 0.3));
  if (!hold || hold.durationInFrames < 2 * (transition + guard) + fps) return wide;
  const middle = hold.from + hold.durationInFrames / 2;
  const still: MotionProgram = {paths: [], entities: program.entities.map((prepared) => ({
    entity: {...prepared.entity, ...entityAtFrame(prepared, middle)}, actions: [], activities: [],
  }))};
  const focus = fitMotionViewport(still, {fitContent: true, minimumWidth: wide.width / 1.45,
    minimumHeight: wide.height / 1.45});
  const entrance = (frame - hold.from - guard) / transition;
  const exit = (hold.from + hold.durationInFrames - guard - frame) / transition;
  const t = Math.max(0, Math.min(1, entrance, exit));
  const amount = t * t * (3 - 2 * t);
  return {x: wide.x + (focus.x - wide.x) * amount, y: wide.y + (focus.y - wide.y) * amount,
    width: wide.width + (focus.width - wide.width) * amount,
    height: wide.height + (focus.height - wide.height) * amount};
};
