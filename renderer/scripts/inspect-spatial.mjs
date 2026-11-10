// Spatial acceptance diagnostics using the production solver and shared presentation planner.
// Usage: node scripts/inspect-spatial.mjs <timeline.json> <report.json> [--custom-contact-only]
import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';

const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  let {outputText} = ts.transpileModule(await fs.readFile(file, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React,
  }});
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    const local = (extension) => new URL(`${match[2]}${extension}`, file);
    const dependency = match[2].startsWith('.')
      ? await moduleUrl(existsSync(local('.ts')) ? local('.ts') : local('.tsx')) : import.meta.resolve(match[2]);
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, entityAtFrame, contactAnchorAtFrame, toStage} = await load('engine');
const {entityHalfExtents} = await load('metrics');
const {transformedRigBounds} = await load('rig');
const {processPresentations} = await load('processPresentation');

const LIMITS = Object.freeze({anchorGap: 1e-6, positionJump: 1e-3, viewportExcess: 1e-6,
  cameraDifference: 1e-6, epsilonFrames: 1e-6, maximumSceneFrames: 100_000, maximumTotalFrames: 1_000_000});
const distance = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);
// Compiled timings come from Python round(), whose exact halves round to the even integer.
const compiledRound = (value) => {
  const lower = Math.floor(value);
  return value - lower === 0.5 ? lower + lower % 2 : Math.round(value);
};
const finitePoint = (point, where) => {
  if (!Number.isFinite(point.x) || !Number.isFinite(point.y)) throw new Error(`${where}: nonfinite evaluated position.`);
  return point;
};
const frameInterval = (item, where, scene) => {
  if (!Number.isSafeInteger(item.from) || item.from < 0 || !Number.isSafeInteger(item.durationInFrames)
    || item.durationInFrames <= 0 || !Number.isSafeInteger(item.from + item.durationInFrames)) {
    throw new Error(`${where}: from and durationInFrames must define a finite positive whole-frame interval.`);
  }
  if (scene && (item.from < scene.from || item.from + item.durationInFrames > scene.from + scene.durationInFrames)) {
    throw new Error(`${where}: interval lies outside its scene.`);
  }
};
const validateTimeline = (timeline) => {
  if (!Number.isFinite(timeline?.fps) || timeline.fps <= 0) throw new Error('Timeline fps must be positive and finite.');
  if (!Number.isSafeInteger(timeline.durationInFrames) || timeline.durationInFrames <= 0
    || timeline.durationInFrames > LIMITS.maximumTotalFrames) throw new Error('Timeline durationInFrames is invalid or exceeds the diagnostic frame budget.');
  if (!Array.isArray(timeline.scenes) || !timeline.scenes.length) throw new Error('Timeline needs at least one scene.');
  const ids = new Set();
  let previousEnd = 0;
  let checkedFrames = 0;
  for (const scene of timeline.scenes) {
    if (typeof scene.id !== 'string' || !scene.id || ids.has(scene.id)) throw new Error('Timeline scene IDs must be present and unique.');
    ids.add(scene.id);
    frameInterval(scene, `Scene ${scene.id}`);
    const end = scene.from + scene.durationInFrames;
    if (scene.from < previousEnd || end > timeline.durationInFrames) throw new Error(`Scene ${scene.id}: overlapping, unordered, or outside the timeline.`);
    previousEnd = end;
    if (scene.template !== 'motion') continue;
    checkedFrames += scene.durationInFrames;
    if (scene.durationInFrames > LIMITS.maximumSceneFrames || checkedFrames > LIMITS.maximumTotalFrames) {
      throw new Error(`Scene ${scene.id}: spatial diagnostic frame budget exceeded.`);
    }
    if (!scene.visual || !Array.isArray(scene.visual.entities) || !Array.isArray(scene.visual.paths)
      || !Array.isArray(scene.visual.actions)) throw new Error(`Scene ${scene.id}: incomplete motion visual.`);
    const actorIds = new Set();
    for (const entity of scene.visual.entities) {
      if (actorIds.has(entity.id)) throw new Error(`Scene ${scene.id}: duplicate entity ${entity.id}.`);
      actorIds.add(entity.id);
      if (![entity.x, entity.y, entity.size, entity.rotation, entity.opacity].every(Number.isFinite)
        || entity.size < 0) throw new Error(`Scene ${scene.id}, entity ${entity.id}: invalid base transform.`);
    }
    for (const key of ['actions', 'performances', 'contacts']) {
      if (scene.visual[key] !== undefined && !Array.isArray(scene.visual[key])) throw new Error(`Scene ${scene.id}: ${key} must be an array.`);
      for (const [index, item] of (scene.visual[key] ?? []).entries()) {
        frameInterval(item, `Scene ${scene.id}, ${key}[${index}]`, scene);
        if (key === 'contacts' && (!Number.isSafeInteger(item.approachFrames)
          || item.approachFrames !== compiledRound(item.durationInFrames * item.approach))) {
          throw new Error(`Scene ${scene.id}, contacts[${index}]: acquisition frames do not match the compiled approach.`);
        }
      }
    }
  }
};

const relatedShots = (before, after) => {
  if (before?.template !== 'motion' || after?.template !== 'motion' || before.chapterId !== after.chapterId
    || Boolean(before.processTrace) !== Boolean(after.processTrace)) return false;
  if (before.processTrace) return before.processTrace.actorIds.some((id) => after.processTrace.actorIds.includes(id))
    && before.processTrace.stationEntityIds.some((id) => after.processTrace.stationEntityIds.includes(id));
  return before.visual.entities.some((a) => after.visual.entities.some((b) => a.id === b.id && a.kind === b.kind));
};
const viewportDifference = (a, b) => Math.max(...['x', 'y', 'width', 'height'].map((key) => Math.abs(a[key] - b[key])));

/** Measures geometry and position continuity; never infers physical correctness or perceptual quality. */
export const inspectSpatial = (timeline, {customContactOnly = false} = {}) => {
  validateTimeline(timeline);
  const look = timeline.look === 'sketch' ? 'sketch' : 'vector';
  const presentations = processPresentations(timeline.scenes, look === 'sketch');
  const enforcedGroups = new Set(timeline.scenes.filter((scene) => scene.template === 'motion'
    && (!customContactOnly || scene.visual.contacts?.length
      || scene.visual.entities.some((entity) => entity.kind === 'custom')))
    .map((scene) => presentations.get(scene.id)?.group));
  const scenes = [];
  const cameraTransitions = [];
  for (let index = 1; index < timeline.scenes.length; index++) {
    const before = timeline.scenes[index - 1], after = timeline.scenes[index];
    if (!relatedShots(before, after)) continue;
    const a = presentations.get(before.id), b = presentations.get(after.id);
    if (!a || !b) throw new Error('Production presentation planner omitted a motion scene.');
    const difference = viewportDifference(a.viewport, b.viewport);
    cameraTransitions.push({beforeScene: before.id, afterScene: after.id,
      beforeGroup: a.group, afterGroup: b.group, maxViewportDifference: difference,
      enforced: enforcedGroups.has(a.group) || enforcedGroups.has(b.group),
      passed: a.group === b.group && difference <= LIMITS.cameraDifference});
  }
  for (const scene of timeline.scenes.filter((item) => item.template === 'motion')) {
    const program = compileMotion(scene.visual);
    const presentation = presentations.get(scene.id);
    if (!presentation) throw new Error(`Scene ${scene.id}: no production viewport.`);
    const viewport = presentation.viewport;
    if (!Object.values(viewport).every(Number.isFinite) || viewport.width <= 0 || viewport.height <= 0) {
      throw new Error(`Scene ${scene.id}: invalid production viewport.`);
    }
    const byId = new Map(program.entities.map((actor) => [actor.entity.id, actor]));
    const end = scene.from + scene.durationInFrames;
    const contacts = (scene.visual.contacts ?? []).map((contact, index) => {
      const source = byId.get(contact.entityId), target = byId.get(contact.targetId);
      if (!source || !target) throw new Error(`Scene ${scene.id}: invalid contact entity reference.`);
      const acquired = contact.from + contact.approachFrames;
      const release = contact.from + contact.durationInFrames;
      const first = Math.max(scene.from, acquired), last = Math.min(end - 1, release);
      let maxAnchorGap = 0, worstFrame = null, lockedFramesChecked = 0;
      for (let frame = first; frame <= last; frame++) {
        const a = finitePoint(contactAnchorAtFrame(source, contact.partId, contact, frame), 'Source anchor');
        const b = finitePoint(contactAnchorAtFrame(target, contact.targetPartId,
          {x: contact.targetX, y: contact.targetY}, frame), 'Target anchor');
        const gap = distance(a, b);
        if (worstFrame === null || gap > maxAnchorGap) {maxAnchorGap = gap; worstFrame = frame;}
        lockedFramesChecked++;
      }
      const continuity = [['acquisition-start', contact.from], ['acquisition-end', acquired], ['release', release]]
        .map(([boundary, frame]) => {
          if (frame === scene.from) return {boundary, frame, status: 'not-applicable-scene-initial', passed: true,
            reason: 'There is no preceding frame of this scene; the initial lock is an initial condition.'};
          const left = frame - LIMITS.epsilonFrames, right = frame + LIMITS.epsilonFrames;
          const a = finitePoint(toStage(entityAtFrame(source, left)), 'Source position before boundary');
          const b = finitePoint(toStage(entityAtFrame(source, right)), 'Source position after boundary');
          const anchorA = finitePoint(contactAnchorAtFrame(source, contact.partId, contact, left), 'Source anchor before boundary');
          const anchorB = finitePoint(contactAnchorAtFrame(source, contact.partId, contact, right), 'Source anchor after boundary');
          const rootPositionJump = distance(a, b), anchorPositionJump = distance(anchorA, anchorB);
          return {boundary, frame, status: 'measured', rootPositionJump, anchorPositionJump,
            passed: Math.max(rootPositionJump, anchorPositionJump) <= LIMITS.positionJump};
        });
      return {index, entityId: contact.entityId, partId: contact.partId, targetId: contact.targetId,
        targetPartId: contact.targetPartId, from: contact.from, acquiredFrame: acquired, releaseFrame: release,
        lockedFramesChecked, maxAnchorGap, worstFrame, continuity,
        passed: lockedFramesChecked > 0 && maxAnchorGap <= LIMITS.anchorGap && continuity.every((item) => item.passed)};
    });
    const bounds = new Map(program.entities.map((actor) => [actor.entity.id, {
      entityId: actor.entity.id, framesChecked: 0, outsideFrameCount: 0, maxViewportExcess: 0,
      worstFrame: null, worstBounds: null,
    }]));
    for (let frame = scene.from; frame < end; frame++) {
      for (const actor of program.entities) {
        const state = entityAtFrame(actor, frame);
        if (![state.x, state.y, state.size, state.rotation, state.opacity].every(Number.isFinite) || state.size < 0) {
          throw new Error(`Scene ${scene.id}, entity ${actor.entity.id}, frame ${frame}: nonfinite or invalid evaluated transform.`);
        }
        if (state.opacity <= 1e-6) continue;
        const origin = toStage(state);
        const half = entityHalfExtents(actor.entity.kind, state.size, state.rotation, look, actor.rigExtents);
        const local = actor.entity.kind === 'custom' && actor.rig
          ? transformedRigBounds(actor.rig.bounds, [state.size, state.size], [state.rotation, state.rotation])
          : {left: -half.x, right: half.x, top: -half.y, bottom: half.y};
        if (!Object.values(local).every(Number.isFinite)) throw new Error(`Scene ${scene.id}: invalid actor envelope.`);
        const box = {left: origin.x + local.left, right: origin.x + local.right,
          top: origin.y + local.top, bottom: origin.y + local.bottom};
        const excess = Math.max(0, viewport.x - box.left, box.right - viewport.x - viewport.width,
          viewport.y - box.top, box.bottom - viewport.y - viewport.height);
        const report = bounds.get(actor.entity.id);
        report.framesChecked++;
        if (excess > LIMITS.viewportExcess) report.outsideFrameCount++;
        if (report.worstFrame === null || excess > report.maxViewportExcess) {
          report.maxViewportExcess = excess; report.worstFrame = frame; report.worstBounds = box;
        }
      }
    }
    const actors = [...bounds.values()].map((item) => ({...item, passed: item.outsideFrameCount === 0}));
    scenes.push({id: scene.id, from: scene.from, durationInFrames: scene.durationInFrames,
      cameraGroup: presentation.group, viewport: {...viewport}, contacts, actorBounds: actors,
      enforced: enforcedGroups.has(presentation.group),
      passed: contacts.every((item) => item.passed) && actors.every((item) => item.passed)});
  }
  const enforcedScenes = scenes.filter((scene) => scene.enforced);
  const advisoryScenes = scenes.filter((scene) => !scene.enforced);
  const measuredBoundaries = enforcedScenes.flatMap((scene) => scene.contacts.flatMap((contact) => contact.continuity))
    .filter((item) => item.status === 'measured');
  const passed = enforcedScenes.every((scene) => scene.passed) && cameraTransitions.every((item) => !item.enforced || item.passed);
  return {schemaVersion: '1', projectId: timeline.projectId, fps: timeline.fps,
    scope: customContactOnly ? 'custom-contact-groups' : 'all-motion',
    advisorySceneIds: advisoryScenes.filter((scene) => !scene.passed).map((scene) => scene.id),
    status: passed ? 'spatial-checks-passed' : 'needs-review', frameReference: 'absolute-video',
    units: 'Physical SVG stage units, before camera fitting.', limits: {...LIMITS},
    provenance: {method: 'Production compileMotion, entityAtFrame, contactAnchorAtFrame, entityHalfExtents, transformedRigBounds and processPresentations.',
      input: 'Compiled timeline supplied by caller; generation source is not inferred.', pixelRender: false},
    summary: {motionScenes: scenes.length, enforcedMotionScenes: enforcedScenes.length,
      contacts: scenes.reduce((n, scene) => n + scene.contacts.length, 0),
      lockedFramesChecked: scenes.reduce((n, scene) => n + scene.contacts.reduce((sum, c) => sum + c.lockedFramesChecked, 0), 0),
      maxAnchorGap: Math.max(0, ...scenes.flatMap((scene) => scene.contacts.map((c) => c.maxAnchorGap))),
      maxBoundaryPositionJump: Math.max(0, ...measuredBoundaries.flatMap((c) => [c.rootPositionJump, c.anchorPositionJump])),
      maxViewportExcess: Math.max(0, ...enforcedScenes.flatMap((scene) => scene.actorBounds.map((a) => a.maxViewportExcess))),
      advisoryMaxViewportExcess: Math.max(0, ...advisoryScenes.flatMap((scene) => scene.actorBounds.map((a) => a.maxViewportExcess))),
      relatedCameraTransitions: cameraTransitions.length},
    limitations: ['Continuity samples positions at boundary ± epsilon; this does not test velocity or acceleration continuity.',
      'Contact tests compare authored anchor points, not collision surfaces; other geometry can still intersect.',
      'Actor containment uses evaluated root transforms and conservative complete-rig envelopes, not pixel segmentation.',
      'The camera is the static viewport returned by the production shared-presentation planner.',
      'Labels, captions, paths, occlusion and pixel-level appearance are not checked here.',
      'Overlap and semantic diagnostics remain separate; intentional contact does not suppress unrelated collision warnings.',
      'In custom-contact-groups scope, unrelated legacy groups are reported as advisory and do not block rendering.',
      'Passing these numerical checks does not establish physical realism or visual quality.'], cameraTransitions, scenes};
};

export const runCli = async ([input, output, ...extra]) => {
  if (!input || !output || extra.length > 1 || extra.length === 1 && extra[0] !== '--custom-contact-only') {
    throw new Error('Usage: node scripts/inspect-spatial.mjs <timeline.json> <report.json> [--custom-contact-only]');
  }
  if (path.resolve(input) === path.resolve(output)) throw new Error('The report must not replace its input timeline.');
  const text = await fs.readFile(input, 'utf8');
  const report = inspectSpatial(JSON.parse(text), {customContactOnly: extra[0] === '--custom-contact-only'});
  report.provenance.timelinePath = path.resolve(input);
  report.provenance.timelineSha256 = createHash('sha256').update(text).digest('hex');
  await fs.writeFile(output, `${JSON.stringify(report, null, 2)}\n`);
  console.log(JSON.stringify({report: path.resolve(output), status: report.status, ...report.summary}));
  if (report.status !== 'spatial-checks-passed') process.exitCode = 1;
};

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try { await runCli(process.argv.slice(2)); }
  catch (error) { console.error(error.message); process.exitCode = 1; }
}
