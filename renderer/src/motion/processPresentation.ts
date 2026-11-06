import type {TimelineScene} from '../types';
import {compileMotion} from './engine';
import {fitMotionViewport, fitProcessViewport, type StageViewport} from './camera';
import {planLabelSlots, PROCESS_LABEL_ORDER, sceneFrames, type LabelSlots} from './labels';
import {planProps, planRoom, type PropPlacement, type Room} from './staging';

type ProcessScene = Extract<TimelineScene, {template: 'motion'}>;
/**
 * `group` numbers each run of related motion shots; scenes in one group share a camera and label plan.
 * A shared ID and kind denote the same object. Process and authored motion use different stage layouts.
 */
export type ProcessPresentation = {viewport: StageViewport; group: number; labelSlots: LabelSlots;
  /** The room and its background props, only for a close-up (sketch) stage. */
  props: PropPlacement[]; room: Room | null};
const sharedIds = (a: string[], b: string[]) => a.some((id) => b.includes(id));

/**
 * Consecutive shots of the same cast share one locked establishing frame. Applies to authored motion
 * (spacecraft, network packets, diagrams, people, etc.) as well as compiled process scenes. The camera never zooms
 * or re-frames inside or between them, so counters, people and labels keep their size and place on
 * every frame. A `closeUp` frame holds only the places where people stand, so the cast is drawn larger
 * and departures walk out of the shot. Authored colors stay unchanged.
 */
export const processPresentations = (scenes: TimelineScene[], closeUp = false): Map<string, ProcessPresentation> => {
  const result = new Map<string, ProcessPresentation>();
  let group: ProcessScene[] = [];
  let groups = 0;
  const flush = () => {
    if (!group.length) return;
    const programs = group.map((scene) => compileMotion(scene.visual));
    const process = Boolean(group[0].processTrace);
    const look = closeUp ? 'sketch' : 'vector';
    const viewport = process ? fitProcessViewport(programs, closeUp, look) : fitMotionViewport({
      entities: programs.flatMap((program) => program.entities), paths: programs.flatMap((program) => program.paths),
    }, {look});
    const shots = group.map((scene, index) => ({program: programs[index],
      frames: sceneFrames(scene.from, scene.durationInFrames)}));
    const labelSlots = planLabelSlots(shots, process ? PROCESS_LABEL_ORDER : undefined,
      {viewport, look, fontScale: closeUp ? 1.25 : 1});
    const room = process && closeUp ? planRoom(shots, viewport) : null;
    const props = room ? planProps(shots, viewport, labelSlots, room.horizon) : [];
    for (const scene of group) result.set(scene.id, {viewport, group: groups, labelSlots, props, room});
    groups += 1;
    group = [];
  };
  for (const scene of scenes) {
    if (scene.template !== 'motion') {flush(); continue;}
    const previous = group.at(-1);
    if (previous) {
      const sameCast = previous.processTrace && scene.processTrace
        ? sharedIds(previous.processTrace.actorIds, scene.processTrace.actorIds)
          && sharedIds(previous.processTrace.stationEntityIds, scene.processTrace.stationEntityIds)
        : !previous.processTrace && !scene.processTrace && scene.visual.entities.some((entity) =>
          previous.visual.entities.some((before) => before.id === entity.id && before.kind === entity.kind));
      if (previous.chapterId !== scene.chapterId || !sameCast) flush();
    }
    group.push(scene);
  }
  flush();
  return result;
};
