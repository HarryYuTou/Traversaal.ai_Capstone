import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {test} from 'node:test';
import {inspectSpatial, runCli} from './inspect-spatial.mjs';

const fixture = JSON.parse(await fs.readFile(new URL('../../fixtures/scene-plan.spatial-quality.json', import.meta.url), 'utf8'));

// A fixed test clock isolates the JS diagnostics from Python/TTS availability. The acceptance
// CLI separately audits actual production-compiled timelines, without this test adapter.
const fixtureTimeline = () => {
  const plan = structuredClone(fixture);
  let cursor = 60;
  const scenes = plan.scenes.map((scene, index) => {
    const from = cursor;
    const lines = scene.narration.map((line, i) => ({...line, from: from + 6 + i * 93, durationInFrames: 90}));
    const contentEnd = lines.at(-1).from + 90 + 6;
    cursor = contentEnd;
    const compile = (item, contact = false) => {
      const round = (value) => value - Math.floor(value) === 0.5
        ? Math.floor(value) + Math.floor(value) % 2 : Math.round(value);
      let start = lines[item.startLine].from + round(item.startOffset * 90);
      const end = lines[item.endLine].from + round(item.endOffset * 90);
      if (contact && item.approach === 0 && item.startLine === 0 && item.startOffset === 0) start = from;
      return {...item, from: start, durationInFrames: end - start,
        ...(contact ? {approachFrames: round((end - start) * item.approach)} : {})};
    };
    return {id: scene.id, template: 'motion', chapterId: null, from,
      durationInFrames: contentEnd - from + (index === plan.scenes.length - 1 ? 30 : 0), lines,
      visual: {...scene.visual, actions: scene.visual.actions.map((a) => compile(a)),
        performances: scene.visual.performances.map((p) => compile(p)),
        contacts: scene.visual.contacts.map((c) => compile(c, true))}};
  });
  return {schemaVersion: '1', projectId: plan.projectId, fps: 30, width: 1920, height: 1080,
    durationInFrames: cursor + 30, look: 'vector', scenes};
};
const actor = (id, extra = {}) => ({id, kind: 'person', x: 30, y: 50, size: 1, rotation: 0,
  opacity: 1, value: 0, color: 'accent', label: '', ...extra});
const action = (entityId, kind, from, durationInFrames, extra = {}) => ({entityId, kind, from, durationInFrames,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: '', x: 30, y: 50, value: 0,
  easing: 'linear', ...extra});
const shot = (id, from, extra = {}) => ({id, template: 'motion', chapterId: null, from, durationInFrames: 90,
  lines: [], visual: {title: id, entities: [actor('shared')], paths: [], actions: []}, ...extra});
const tinyRig = () => ({id: 'generated', clips: [], parts: [{id: 'body', parentId: '', x: 0, y: 0,
  rotation: 0, scaleX: 1, scaleY: 1, opacity: 1, shapes: [{kind: 'rect', x: -10, y: -10, width: 20,
    height: 20, radius: 0, path: '', fill: 'accent', stroke: 'none', strokeWidth: 0}]}]});
const customShot = (from = 90) => {
  const s = shot('custom', from);
  s.visual.entities = [actor('generated', {kind: 'custom', rigId: 'generated', x: 50})];
  s.visual.rigs = [tinyRig()];
  return s;
};
const departingProcess = () => {
  const s = shot('departure', 0, {processTrace: {actorIds: ['actor'], stationEntityIds: ['station']}});
  s.visual.entities = [actor('actor', {x: 20}), actor('station', {kind: 'counter', x: 35})];
  s.visual.actions = [action('actor', 'move', 20, 40, {x: 200}), action('actor', 'opacity', 40, 20, {value: 0})];
  return s;
};

test('known spatial acceptance fixture passes every locked frame and records explicit quantitative limits', () => {
  const report = inspectSpatial(fixtureTimeline());
  assert.equal(report.status, 'spatial-checks-passed');
  assert.equal(report.summary.motionScenes, 3);
  assert.equal(report.summary.contacts, 3);
  assert.equal(report.summary.lockedFramesChecked, 519);
  assert.ok(report.summary.maxAnchorGap < 1e-10);
  assert.ok(report.summary.maxBoundaryPositionJump <= report.limits.positionJump);
  assert.equal(report.summary.maxViewportExcess, 0);
  assert.equal(report.provenance.pixelRender, false);
  for (const scene of report.scenes) {
    assert.ok(scene.actorBounds.every((actor) => actor.framesChecked === scene.durationInFrames));
    for (const contact of scene.contacts) assert.deepEqual(contact.continuity.map((c) => c.boundary),
      ['acquisition-start', 'acquisition-end', 'release']);
  }
  assert.equal(report.scenes[0].contacts[0].continuity[0].status, 'not-applicable-scene-initial');
  assert.equal(report.scenes[1].contacts[0].continuity[0].status, 'measured');
  assert.ok(report.limitations.some((line) => line.includes('not collision surfaces')));
});

test('related shots use exactly the shared production camera even when positions differ', () => {
  const first = shot('first', 0), second = shot('second', 90);
  second.visual.entities[0].x = 92;
  const report = inspectSpatial({fps: 30, durationInFrames: 180, scenes: [first, second]});
  assert.equal(report.status, 'spatial-checks-passed');
  assert.equal(report.cameraTransitions.length, 1);
  assert.equal(report.cameraTransitions[0].passed, true);
  assert.equal(report.cameraTransitions[0].maxViewportDifference, 0);
  assert.deepEqual(report.scenes[0].viewport, report.scenes[1].viewport);
});

test('off-frame process departures remain reportable rather than being silently exempted', () => {
  const s = departingProcess();
  const report = inspectSpatial({fps: 30, durationInFrames: 90, look: 'sketch', scenes: [s]});
  assert.equal(report.status, 'needs-review');
  assert.ok(report.scenes[0].actorBounds.find((a) => a.entityId === 'actor').outsideFrameCount > 0);
  assert.ok(report.summary.maxViewportExcess > report.limits.viewportExcess);
});

test('production scope leaves unrelated legacy process departures advisory without changing their camera', () => {
  const timeline = {fps: 30, durationInFrames: 180, look: 'sketch', scenes: [departingProcess(), customShot()]};
  const full = inspectSpatial(timeline);
  assert.equal(full.status, 'needs-review');
  assert.equal(full.scope, 'all-motion');
  const scoped = inspectSpatial(timeline, {customContactOnly: true});
  assert.equal(scoped.status, 'spatial-checks-passed');
  assert.equal(scoped.scope, 'custom-contact-groups');
  assert.deepEqual(scoped.advisorySceneIds, ['departure']);
  assert.equal(scoped.scenes[0].enforced, false);
  assert.equal(scoped.scenes[0].passed, false, 'the legacy finding remains visible in the report');
  assert.equal(scoped.scenes[1].enforced, true);
  assert.equal(scoped.summary.enforcedMotionScenes, 1);
  assert.equal(scoped.summary.maxViewportExcess, 0);
  assert.ok(scoped.summary.advisoryMaxViewportExcess > 0);
  assert.deepEqual(scoped.scenes[0].viewport, full.scenes[0].viewport);
});

test('production scope enforces all related shots and still blocks containment failures in a custom group', () => {
  const generated = customShot(0);
  generated.visual.entities.push(actor('shared'));
  const continuation = shot('continuation', 90);
  const shared = inspectSpatial({fps: 30, durationInFrames: 180, scenes: [generated, continuation]}, {customContactOnly: true});
  assert.equal(shared.scenes[0].enforced, true);
  assert.equal(shared.scenes[1].enforced, true, 'later stock-only shot shares the custom camera group');
  assert.equal(shared.cameraTransitions[0].enforced, true);
  const customProcess = departingProcess();
  customProcess.visual.entities.push(actor('generated', {kind: 'custom', rigId: 'generated', x: 50}));
  customProcess.visual.rigs = [tinyRig()];
  const failure = inspectSpatial({fps: 30, durationInFrames: 90, look: 'sketch', scenes: [customProcess]},
    {customContactOnly: true});
  assert.equal(failure.scenes[0].enforced, true);
  assert.equal(failure.status, 'needs-review');
  assert.ok(failure.summary.maxViewportExcess > 0);
  assert.deepEqual(failure.advisorySceneIds, []);
});

test('faint custom objects are framed using the same visibility threshold as spatial containment', () => {
  const s = customShot(0);
  s.visual.entities.push(actor('faint', {kind: 'custom', rigId: 'generated', x: 0, opacity: 0.04}));
  const report = inspectSpatial({fps: 30, durationInFrames: 90, scenes: [s]}, {customContactOnly: true});
  assert.equal(report.status, 'spatial-checks-passed');
  assert.equal(report.scenes[0].actorBounds.find((a) => a.entityId === 'faint').framesChecked, 90);
  assert.equal(report.summary.maxViewportExcess, 0);
});

test('asymmetric custom containment uses actual directional bounds rather than a mirrored body', () => {
  const s = customShot(0);
  Object.assign(s.visual.entities[0], {y: 25, size: 1.8, label: 'Arm'});
  Object.assign(s.visual.rigs[0].parts[0].shapes[0], {y: 0, height: 240});
  s.visual.actions = [action('generated', 'move', 10, 60, {x: 50, y: 65})];
  const report = inspectSpatial({fps: 30, durationInFrames: 90, scenes: [s]}, {customContactOnly: true});
  assert.equal(report.status, 'spatial-checks-passed');
  assert.equal(report.summary.maxViewportExcess, 0);
  assert.ok(report.scenes[0].viewport.height < 850, 'the absent upper half does not inflate the camera');
  assert.ok(report.scenes[0].actorBounds[0].worstBounds.top > 100,
    'the inspector checks the drawn lower rod instead of inventing a mirrored upper rod');
  assert.equal(report.scenes[0].actorBounds[0].framesChecked, 90);
});

test('invalid and unbounded frame intervals fail explicitly before frame iteration', () => {
  const cases = [
    (t) => {t.fps = NaN;},
    (t) => {t.durationInFrames = Infinity;},
    (t) => {t.scenes[0].from = -1;},
    (t) => {t.scenes[0].from = NaN;},
    (t) => {t.scenes[0].durationInFrames = 1.5;},
    (t) => {t.durationInFrames = 1_000_001;},
    (t) => {t.scenes[0].durationInFrames = 100_001; t.durationInFrames = 200_000;},
    (t) => {t.scenes[1].from = t.scenes[0].from;},
    (t) => {t.scenes[1].id = t.scenes[0].id;},
    (t) => {t.scenes[0].visual.contacts[0].durationInFrames = 0;},
    (t) => {t.scenes[0].visual.contacts[0].durationInFrames = Infinity;},
    (t) => {t.scenes[0].visual.contacts[0].from -= 1;},
    (t) => {t.scenes[0].visual.contacts[0].approachFrames = 1;},
    (t) => {t.scenes[0].visual.entities[0].x = NaN;},
    (t) => {t.scenes[0].visual.performances[0].from = Infinity;},
  ];
  for (const mutate of cases) {
    const timeline = fixtureTimeline(); mutate(timeline);
    assert.throws(() => inspectSpatial(timeline), Error);
  }
});

test('missing anchors and illegal travel during a contact are rejected by the production solver', () => {
  const missing = fixtureTimeline();
  missing.scenes[0].visual.contacts[0].targetPartId = 'missing';
  assert.throws(() => inspectSpatial(missing), /missing part anchor/);
  const conflict = fixtureTimeline();
  conflict.scenes[0].visual.actions.push(action('presenter', 'move', 90, 30, {x: 70}));
  assert.throws(() => inspectSpatial(conflict), /source travel overlaps contact/);
});

test('compiled approach-frame checks match Python ties-to-even rounding', () => {
  const scene = shot('half-frame', 0);
  scene.visual.entities = [actor('source', {x: 20}), actor('target', {x: 30})];
  scene.visual.contacts = [{entityId: 'source', partId: '', x: 0, y: 0,
    targetId: 'target', targetPartId: '', targetX: 0, targetY: 0,
    startLine: 0, endLine: 0, startOffset: 0.3, endOffset: 0.5,
    from: 30, durationInFrames: 5, approach: 0.5, approachFrames: 2}];
  const report = inspectSpatial({fps: 30, durationInFrames: 90, scenes: [scene]});
  assert.equal(report.status, 'spatial-checks-passed');
  assert.equal(report.scenes[0].contacts[0].acquiredFrame, 32);
  assert.equal(report.scenes[0].contacts[0].lockedFramesChecked, 4);
  scene.visual.contacts[0].approachFrames = 3;
  assert.throws(() => inspectSpatial({fps: 30, durationInFrames: 90, scenes: [scene]}), /compiled approach/);
});

test('CLI reads the supplied timeline and writes a report without rendering media', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'capstone-spatial-inspection-'));
  try {
    const input = path.join(directory, 'timeline.json'), output = path.join(directory, 'report.json');
    await fs.writeFile(input, JSON.stringify(fixtureTimeline()));
    await runCli([input, output]);
    const report = JSON.parse(await fs.readFile(output, 'utf8'));
    assert.equal(report.status, 'spatial-checks-passed');
    assert.equal(report.summary.lockedFramesChecked, 519);
    assert.deepEqual((await fs.readdir(directory)).sort(), ['report.json', 'timeline.json']);
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
  }
});

test('CLI accepts explicit custom-contact-only production scope and rejects unknown flags', async () => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), 'capstone-spatial-scope-'));
  try {
    const input = path.join(directory, 'timeline.json'), output = path.join(directory, 'report.json');
    const timeline = {fps: 30, durationInFrames: 180, look: 'sketch', scenes: [departingProcess(), customShot()]};
    await fs.writeFile(input, JSON.stringify(timeline));
    await runCli([input, output, '--custom-contact-only']);
    const report = JSON.parse(await fs.readFile(output, 'utf8'));
    assert.equal(report.scope, 'custom-contact-groups');
    assert.equal(report.status, 'spatial-checks-passed');
    assert.deepEqual(report.advisorySceneIds, ['departure']);
    await assert.rejects(() => runCli([input, output, '--unknown']), /Usage:/);
  } finally {
    await fs.rm(directory, {recursive: true, force: true});
  }
});
