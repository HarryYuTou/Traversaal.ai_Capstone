import type {ProcessTrace} from '../types';

export type ProcessSnapshot = {
  waiting: number;
  inService: number;
  unfinished: number;
  opacity: number;
};

const clamp = (value: number) => Math.max(0, Math.min(1, value));
const smooth = (value: number) => value * value * (3 - 2 * value);

/** Replay actual visual milestones from the initial snapshot, so arbitrary seeking is exact.
 * Future arrivals are absent from unfinished work. Departures leave the system only when they
 * reach the exit; a completed cue alone does not remove a still-present actor from the snapshot.
 */
export const processStateAtFrame = (trace: ProcessTrace, frame: number, fadeFrames = 8): ProcessSnapshot => {
  const waiting = new Set(trace.initialQueue);
  const inService = new Set(trace.initialService.map(({actorId}) => actorId));
  let opacity = 1;
  for (const event of trace.events) {
    for (const phase of event.phases) {
      if (frame < phase.from + phase.durationInFrames) continue;
      if (phase.kind === 'arrive') {
        phase.actorIds.forEach((id) => waiting.add(id));
      } else if (phase.kind === 'to-service') {
        phase.actorIds.forEach((id) => {waiting.delete(id); inService.add(id);});
      } else if (phase.kind === 'exit') {
        phase.actorIds.forEach((id) => inService.delete(id));
      }
    }
    if (event.kind === 'hold') continue;
    // A moving person is neither clearly queued nor visibly being served. Show the settled
    // snapshot on holds, fading out before a transition and back in after its final fade/compaction.
    const end = event.from + event.durationInFrames;
    const distance = frame < event.from ? event.from - frame : frame > end ? frame - end : 0;
    opacity = Math.min(opacity, smooth(fadeFrames > 0 ? clamp(distance / fadeFrames) : Number(distance > 0)));
  }
  return {waiting: waiting.size, inService: inService.size,
    unfinished: new Set([...waiting, ...inService]).size, opacity};
};

/** Reserve a dedicated line beneath the title; raw motion scenes retain their original stage. */
export const processStageLayout = <T extends {x: number; y: number; width: number; height: number}>(
  stage: T, videoHeight: number,
) => {
  const scale = videoHeight / 1080;
  const y = 99 * scale;
  return {container: {x: stage.x, y, width: stage.width, height: stage.y + stage.height - y},
    inset: 20 * scale, titleFontSize: 56 * scale,
    strip: {fontSize: 30 * scale, height: 36 * scale, marginTop: 14 * scale, marginBottom: 16 * scale}};
};

export type StationState = {open: boolean; openingProgress: number};

/** Station availability follows the same completed-phase boundary as the process compiler.
 * Older timelines without availability metadata retain their existing appearance. */
export const stationStateAtFrame = (trace: ProcessTrace, stationId: string, frame: number): StationState | null => {
  if (!trace.stationEntityIds.includes(stationId) || !trace.initialOpenStationIds) return null;
  let open = trace.initialOpenStationIds.includes(stationId);
  let openingProgress = 0;
  for (const event of trace.events) {
    if (event.kind !== 'open' || !event.stationIds.includes(stationId)) continue;
    const phase = event.phases.find((part) => part.kind === 'open' &&
      (!part.stationIds || part.stationIds.includes(stationId)));
    const start = phase?.from ?? event.from;
    const duration = phase?.durationInFrames ?? event.durationInFrames;
    if (frame >= start + duration) {open = true; openingProgress = 1;}
    else if (frame >= start) openingProgress = clamp((frame - start) / Math.max(1, duration));
  }
  return {open, openingProgress};
};
