// Deterministic geometry/timing diagnostics; rendered video still needs semantic and visual review.
// Usage: node scripts/inspect-motion.mjs <timeline.json> <report.json>
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';

const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  const source = await fs.readFile(file, 'utf8');
  let {outputText} = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  }});
  for (const match of [...outputText.matchAll(/from (['"])(\.\/[^'"]+)\1/g)]) {
    const dependency = await moduleUrl(new URL(`${match[2]}.ts`, file));
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, displayedPaths, entityAtFrame, toStage} = await load('engine');
const {entityHalfExtents} = await load('metrics');
const {activityAtFrame} = await load('pose');
const {objectPerformanceAtFrame, OBJECT_CUE_KINDS} = await load('objectPerformance');
const {rigPictureAtFrame} = await load('rig');

const overlapping = (item, start, end) => item.from < end && item.from + item.durationInFrames > start;
const clippedRange = (item, start, end) => [Math.max(start, item.from), Math.min(end, item.from + item.durationInFrames)];
const mergedRanges = (ranges) => {
  const merged = [];
  for (const [start, end] of ranges.filter(([a, b]) => a < b).sort((a, b) => a[0] - b[0])) {
    const previous = merged.at(-1);
    if (previous && start <= previous[1]) previous[1] = Math.max(previous[1], end);
    else merged.push([start, end]);
  }
  return merged;
};

// Match rendered channels: value changes only affect gauges, and an invisible actor cannot make
// a picture busy. Visible activity progress and revealed routes do count as purposeful motion.
// Discard interpolation round-off; a no-op such as 30*(1-p)+30*p must stay visually unchanged.
const visualNumber = (value) => Number(value.toFixed(6));
const visible = (opacity) => opacity > 1e-6;
const pulse = (phase, row) => visualNumber(0.25 + 0.75 * (0.5 + 0.5 * Math.sin(phase * Math.PI * 4 - row * 1.7)));
const processingRows = {server: 6, laptop: 5, cloud: 3, packet: 4, box: 3, satellite: 1};
// Only record fields used by the drawing. A cue's clock/progress is not itself a visible change:
// compute uses LED pulses, pack keeps its sealed state, and clipped-out scans show no pixels.
const cuePicture = (pose, kind, entityKind) => {
  if (kind === 'pack') return pose.pack ? Object.values(pose.pack).map(visualNumber) : null;
  if (kind === 'scan' && pose.scan && visible(pose.scan.opacity)) {
    const y = -44 + pose.scan.progress * 92;
    const [top, bottom] = entityKind === 'box' ? [-28, 47] : [-20, 20];
    return y + 7 > top && y - 7 < bottom ? [visualNumber(pose.scan.opacity), visualNumber(y)] : null;
  }
  if (['send', 'receive'].includes(kind) && pose.signal?.kind === kind && visible(pose.signal.opacity)) {
    return [kind, visualNumber(pose.signal.opacity), visualNumber(pose.signal.progress)];
  }
  if (kind === 'compute' && pose.compute && visible(pose.compute.opacity)) {
    return [visualNumber(pose.compute.opacity),
      ...Array.from({length: processingRows[entityKind] ?? 0}, (_, row) => pulse(pose.compute.phase, row))];
  }
  if (kind === 'thrust' && visible(pose.thrust)) {
    return [visualNumber(pose.thrust), visualNumber(0.8 + Math.sin(pose.thrustPhase * Math.PI * 12) * 0.12)];
  }
  return null;
};
const objectPicture = (pose, kind) => {
  if (['person', 'planet', 'moon'].includes(kind)) return null;
  const cues = ['pack', 'scan', 'send', 'receive', 'thrust']
    .filter((cue) => OBJECT_CUE_KINDS[cue].includes(kind)).map((cue) => cuePicture(pose, cue, kind));
  // Generic service uses local details too. Box processing disappears once packing owns its surface.
  const opacity = Math.max(pose.processing, pose.compute?.opacity ?? 0);
  const processing = visible(opacity) && processingRows[kind] && !(kind === 'box' && pose.pack)
    ? [visualNumber(opacity), ...Array.from({length: processingRows[kind]},
      (_, row) => pulse(pose.compute?.phase ?? pose.phase, row))] : null;
  const complete = ['server', 'laptop', 'cloud', 'packet', 'box'].includes(kind) ? visualNumber(pose.complete) : null;
  const detail = kind === 'coin' ? [visualNumber(Math.max(pose.change, pose.processing)), visualNumber(pose.change)]
    : kind === 'marker' ? visualNumber(pose.arrival) : kind === 'gauge' ? visualNumber(pose.change) : null;
  return [cues, processing, complete, detail];
};
const pictureSignature = (program, actors, frame, showRoutes, fps, look) => JSON.stringify({
  actors: actors.filter(({state}) => state.opacity > 0.01).map(({prepared, state, objectPose}) => {
    const activity = activityAtFrame(prepared.activities, frame, fps);
    const mark = activity && (prepared.entity.kind === 'counter' || prepared.entity.kind === 'workbench' ||
      prepared.entity.kind === 'person' && look !== 'sketch' ||
      activity.kind === 'complete' && prepared.entity.kind !== 'person' &&
        !['server', 'laptop', 'cloud', 'packet', 'box'].includes(prepared.entity.kind));
    return [prepared.entity.id, ...[state.x, state.y, state.size, state.rotation % 360, state.opacity].map(visualNumber),
      prepared.entity.kind === 'gauge' ? visualNumber(state.value) : null,
      mark ? [activity.kind, visualNumber(activity.opacity), activity.kind === 'work' ? visualNumber(activity.progress) : null] : null,
      objectPicture(objectPose, prepared.entity.kind),
      prepared.rig ? rigPictureAtFrame(prepared.rig, frame) : null];
  }),
  routes: (showRoutes ? displayedPaths(program, frame) : []).filter(({geometry, from}) => geometry.length > 1e-5 && frame > from)
    .map(({key, from, progress}) => [key,
    visualNumber(Math.max(0, Math.min(1, (frame - from) / 10))), visualNumber(progress)]),
}, (_key, value) => typeof value === 'number' ? visualNumber(value) : value);

export const inspectTimeline = (timeline) => {
  if (!Number.isFinite(timeline.fps) || timeline.fps <= 0) throw new Error('Timeline fps must be positive.');
  let checkedFrames = 0;
  for (const scene of timeline.scenes.filter((item) => item.template === 'motion')) {
    if (!Number.isSafeInteger(scene.from) || scene.from < 0 || !Number.isSafeInteger(scene.durationInFrames)
      || scene.durationInFrames <= 0 || !Number.isSafeInteger(scene.from + scene.durationInFrames)
      || scene.durationInFrames > 100_000 || (checkedFrames += scene.durationInFrames) > 1_000_000) {
      throw new Error('Motion inspection needs safe whole-frame intervals within its frame budget.');
    }
  }
  const scenes = [];
  for (const scene of timeline.scenes.filter((item) => item.template === 'motion')) {
    const program = compileMotion(scene.visual);
    const collisions = new Map();
    const end = scene.from + scene.durationInFrames;
    const staticHolds = [];
    const events = [...(scene.processTrace?.events ?? [])].sort((a, b) => a.from - b.from);
    const declaredRanges = mergedRanges(events.filter((event) => event.kind === 'hold')
      .map((event) => clippedRange(event, scene.from, end)));
    const recordHoldPart = (start, finish, declaredHold) => {
      if (finish - start < 4 * timeline.fps) return;
      staticHolds.push({from: start, durationInFrames: finish - start,
        seconds: Number(((finish - start) / timeline.fps).toFixed(2)),
        narration: (scene.lines ?? []).filter((line) => overlapping(line, start, finish))
          .map((line) => ({id: line.id, text: line.text})), declaredHold});
    };
    const recordHold = (start, finish) => {
      let cursor = start;
      for (const [a, b] of declaredRanges) {
        if (b <= cursor || a >= finish) continue;
        recordHoldPart(cursor, Math.min(a, finish), false);
        recordHoldPart(Math.max(cursor, a), Math.min(b, finish), true);
        cursor = Math.min(b, finish);
      }
      recordHoldPart(cursor, finish, false);
    };
    let stillSince = scene.from;
    let previousPicture;
    const visibleCues = new Map();
    const visiblePerformances = new Map();
    // Every frame, including the last, rather than only storyboard endpoints.
    for (let frame = scene.from; frame < end; frame++) {
      const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame),
        objectPose: objectPerformanceAtFrame(prepared, frame, timeline.fps)}));
      const picture = pictureSignature(program, actors, frame, !scene.processTrace, timeline.fps, timeline.look ?? 'vector');
      for (const {prepared, state, objectPose} of actors) {
        if (state.opacity <= 0.01) continue;
        if (prepared.rig) {
          const signature = (at) => JSON.stringify(rigPictureAtFrame(prepared.rig, at),
            (_key, value) => typeof value === 'number' ? visualNumber(value) : value);
          if (signature(frame) !== signature(frame - 1)) {
            for (const performance of scene.visual.performances ?? []) {
              if (performance.entityId !== prepared.entity.id || frame < performance.from
                || frame >= performance.from + performance.durationInFrames) continue;
              // An overlapping no-op clip must not borrow visible motion from a different part.
              const without = {...prepared.rig, performances: prepared.rig.performances
                .filter((entry) => entry.performance !== performance)};
              if (signature(frame) === JSON.stringify(rigPictureAtFrame(without, frame),
                (_key, value) => typeof value === 'number' ? visualNumber(value) : value)) continue;
              if (!visiblePerformances.has(performance)) visiblePerformances.set(performance, []);
              visiblePerformances.get(performance).push(frame);
            }
          }
        }
        for (const cue of prepared.cues ?? []) {
          if (frame < cue.from || frame >= cue.from + cue.durationInFrames ||
            !OBJECT_CUE_KINDS[cue.kind]?.includes(prepared.entity.kind) ||
            cuePicture(objectPose, cue.kind, prepared.entity.kind) === null) continue;
          if (!visibleCues.has(cue)) visibleCues.set(cue, []);
          visibleCues.get(cue).push(frame);
        }
      }
      if (previousPicture !== undefined && picture !== previousPicture) {
        recordHold(stillSince, frame);
        stillSince = frame;
      }
      previousPicture = picture;
      const boxes = actors.map(({prepared, state}) => {
        const at = toStage(state);
        const half = entityHalfExtents(prepared.entity.kind, state.size, state.rotation,
          timeline.look ?? 'vector', prepared.rigExtents);
        return {id: prepared.entity.id, kind: prepared.entity.kind, state,
          left: at.x - half.x, right: at.x + half.x, top: at.y - half.y, bottom: at.y + half.y};
      }).filter(({state}) => state.opacity > 0.5);
      for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
        const a = boxes[i]; const b = boxes[j];
        const width = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const height = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        if (width <= 2 || height <= 2) continue;
        const key = JSON.stringify([a.id, b.id].sort());
        const previous = collisions.get(key) ?? {entityIds: [a.id, b.id], kinds: [a.kind, b.kind],
          firstFrame: frame, lastFrame: frame, frameCount: 0, maxArea: 0, worstFrame: frame};
        previous.lastFrame = frame; previous.frameCount++;
        if (width * height > previous.maxArea) {
          previous.maxArea = width * height; previous.worstFrame = frame;
        }
        collisions.set(key, previous);
      }
    }
    recordHold(stillSince, end);
    const eventCoverage = scene.processTrace || visibleCues.size || visiblePerformances.size ? (scene.lines ?? []).map((line) => ({
      narrationId: line.id, text: line.text,
      events: events.filter((event) => overlapping(event, line.from, line.from + line.durationInFrames)).map((event) => event.kind),
      activities: (scene.visual.activities ?? []).filter((activity) => overlapping(activity, line.from, line.from + line.durationInFrames))
        .map(({entityId, kind}) => ({entityId, kind})),
      cues: [...visibleCues].filter(([, frames]) => frames.some((frame) => frame >= line.from && frame < line.from + line.durationInFrames))
        .map(([{entityId, kind}]) => ({entityId, kind})),
      ...(scene.visual.performances?.length ? {performances: [...visiblePerformances]
        .filter(([, frames]) => frames.some((frame) => frame >= line.from && frame < line.from + line.durationInFrames))
        .map(([{entityId, clipId}]) => ({entityId, clipId}))} : {}),
    })) : [];
    const finalEvent = events.filter((event) => event.from < end).at(-1);
    const trace = scene.processTrace;
    const collisionReport = [...collisions.values()].map((collision) => ({...collision,
      maxArea: Math.round(collision.maxArea * 100) / 100}));
    const candidates = [scene.from + Math.min(30, scene.durationInFrames - 1),
      ...collisionReport.map((collision) => collision.worstFrame),
      ...staticHolds.map((hold) => hold.from + Math.floor(hold.durationInFrames / 2)),
      ...events.filter((event) => ['start', 'finish'].includes(event.kind) && overlapping(event, scene.from, end))
        .map((event) => event.movementEndFrame ?? event.from + event.durationInFrames - 1),
      ...(scene.visual.activities ?? []).filter((activity) => overlapping(activity, scene.from, end))
        .map((activity) => { const [start, finish] = clippedRange(activity, scene.from, end); return Math.floor((start + finish - 1) / 2); }),
      ...[...visibleCues.values()].flatMap((frames) => [frames[Math.floor((frames.length - 1) / 2)], frames.at(-1)]),
      ...[...visiblePerformances.values()].flatMap((frames) => [frames[0], frames[Math.floor((frames.length - 1) / 2)], frames.at(-1)]),
      end - 1];
    scenes.push({id: scene.id, title: scene.visual.title, source: scene.processTrace ? 'process' : 'motion',
      from: scene.from, durationInFrames: scene.durationInFrames,
      collisions: collisionReport, staticHolds, eventCoverage,
      finalProcessState: trace ? {queue: trace.finalQueue ?? finalEvent?.queueAfter ?? trace.initialQueue ?? [],
        service: trace.finalService ?? finalEvent?.serviceAfter ?? trace.initialService ?? [],
        completed: trace.completed ?? finalEvent?.completedAfter ?? []} : null,
      suggestedFrames: [...new Set(candidates.filter(Number.isFinite)
        .map((frame) => Math.max(scene.from, Math.min(end - 1, Math.floor(frame)))))].sort((a, b) => a - b),
    });
  }
  return {schemaVersion: '1', projectId: timeline.projectId, fps: timeline.fps, frameReference: 'absolute-video',
    status: scenes.some((scene) => scene.collisions.length || scene.staticHolds.some((hold) => !hold.declaredHold))
      ? 'needs-review' : 'geometry-and-timing-checks-passed',
    limitations: ['Conservative shape bounds can flag intentional contact.',
      'Collision checks include actor bodies above 50% opacity; labels and route intersections need visual review.',
      'Changes below 1% actor opacity do not break a static hold.',
      'A busy animation does not prove that a spoken claim is demonstrated.',
      'Inspect rendered frames and the video before accepting visual quality.'], scenes};
};

export const runCli = async ([input, output]) => {
  if (!input || !output) throw new Error('Usage: node scripts/inspect-motion.mjs <timeline.json> <report.json>');
  const timeline = JSON.parse(await fs.readFile(input, 'utf8'));
  const report = inspectTimeline(timeline);
  await fs.writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({report: path.resolve(output), status: report.status,
    motionScenes: report.scenes.length,
    collisionPairs: report.scenes.reduce((sum, scene) => sum + scene.collisions.length, 0),
    longStaticHolds: report.scenes.reduce((sum, scene) => sum + scene.staticHolds.length, 0)}));
};

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await runCli(process.argv.slice(2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
