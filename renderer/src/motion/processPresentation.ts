import type {TimelineScene} from '../types';
import {compileMotion} from './engine';
import {fitProcessViewport, type StageViewport} from './camera';
import {planLabelSlots, PROCESS_LABEL_ORDER, sceneFrames, type LabelSlots} from './labels';

type ProcessScene = Extract<TimelineScene, {template: 'motion'}>;
/**
 * `group` numbers each run of related shots; scenes in one group share the stage, put every label on
 * the same side in every shot, and dissolve into each other.
 */
export type ProcessPresentation = {viewport: StageViewport; group: number; labelSlots: LabelSlots};
const sharedIds = (a: string[], b: string[]) => a.some((id) => b.includes(id));

/**
 * Consecutive shots of the same cast share one locked establishing frame. The camera never zooms
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
    const viewport = fitProcessViewport(programs, closeUp);
    const labelSlots = planLabelSlots(group.map((scene, index) => ({program: programs[index],
      frames: sceneFrames(scene.from, scene.durationInFrames)})), PROCESS_LABEL_ORDER);
    for (const scene of group) result.set(scene.id, {viewport, group: groups, labelSlots});
    groups += 1;
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
