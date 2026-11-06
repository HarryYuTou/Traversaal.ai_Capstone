import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  const source = await readFile(file, 'utf8');
  let {outputText} = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  }});
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    const dependency = match[2].startsWith('./')
      ? await moduleUrl(new URL(`${match[2]}.ts`, file)) : import.meta.resolve(match[2]);
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, entityAtFrame, toStage} = await load('engine');
const {BASE_VIEWPORT} = await load('camera');
const {entityHalfExtents} = await load('metrics');
const {placeActorLabels, planLabelSlots, sceneFrames} = await load('labels');
const entity = (id, values = {}) => ({id, kind: 'packet', x: 50, y: 50, size: 1, rotation: 0,
  opacity: 1, value: 1, color: 'accent', label: id, ...values});
const action = (entityId, kind, values = {}) => ({entityId, kind, startLine: 0, endLine: 0,
  startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0, value: 0, easing: 'linear', from: 0,
  durationInFrames: 120, ...values});
const compile = (entities, actions = []) => compileMotion({title: 'Label regression', entities, actions, paths: []});
const labelsAt = (program, frame, slots, viewport = BASE_VIEWPORT) => placeActorLabels(
  program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)})), viewport, slots);
const inside = (bounds, viewport) => {
  assert.ok(bounds.left >= viewport.x && bounds.right <= viewport.x + viewport.width, JSON.stringify(bounds));
  assert.ok(bounds.top >= viewport.y && bounds.bottom <= viewport.y + viewport.height, JSON.stringify(bounds));
};
const intersects = (a, b) => a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;

test('scene sampling includes the last visible frame without importing the next shot', () => {
  assert.deepEqual(sceneFrames(90, 4), [90, 92, 93]);
  assert.deepEqual(sceneFrames(90, 5), [90, 92, 94]);
  assert.deepEqual(sceneFrames(90, 1), [90]);
  assert.deepEqual(sceneFrames(90, 0), []);
});

test('rotating and growing objects keep one label anchor relative to their translation', () => {
  for (const kind of ['spacecraft', 'server', 'box', 'person']) {
    const p = compile([entity('subject', {kind, label: 'Subject'})], [
      action('subject', 'rotate', {value: 270}), action('subject', 'scale', {value: 1.8}),
      action('subject', 'move', {x: 58, y: 52}),
    ]);
    const viewport = {x: -250, y: -150, width: 1800, height: 850};
    const slots = planLabelSlots([{program: p, frames: sceneFrames(0, 121)}], [2], {viewport});
    let first;
    for (let frame = 0; frame <= 120; frame++) {
      const [label] = labelsAt(p, frame, slots, viewport);
      const at = toStage(label.actor.state);
      const offset = [label.x - at.x, label.y - at.y];
      if (!first) first = offset;
      offset.forEach((value, index) => assert.ok(Math.abs(value - first[index]) < 1e-8, `${kind} frame ${frame}`));
      inside(label.bounds, viewport);
    }
    assert.deepEqual(labelsAt(p, 48, slots, viewport), labelsAt(p, 48, slots, viewport), 'seeking is stateless');
  }
});

test('viewport-aware planning avoids a side that clamps its label over the object', () => {
  const p = compile([entity('bottom', {kind: 'server', x: 50, y: 90, label: 'Server'})]);
  const slots = planLabelSlots([{program: p, frames: [0]}], [0, 1, 2, 3], {viewport: BASE_VIEWPORT});
  assert.equal(slots.get('bottom'), 1, 'above remains clear, whereas below is clamped into the server');
  const [label] = labelsAt(p, 0, slots);
  inside(label.bounds, BASE_VIEWPORT);
  assert.ok(label.bounds.bottom < toStage(label.actor.state).y - 63);
});

test('sketch label geometry uses its actual reading size and taller person silhouette', () => {
  const p = compile([entity('person', {kind: 'person', label: 'Participant'})]);
  const slots = planLabelSlots([{program: p, frames: [0]}], [1], {look: 'sketch', fontScale: 1.25});
  const [label] = labelsAt(p, 0, slots);
  assert.equal(label.fontSize, 27.5);
  const point = toStage(label.actor.state);
  const extents = entityHalfExtents('person', 1, 0, 'sketch');
  assert.ok(!intersects(label.bounds, {left: point.x - extents.x, right: point.x + extents.x,
    top: point.y - extents.y, bottom: point.y + extents.y}));
  inside(label.bounds, BASE_VIEWPORT);
});

test('one identity keeps its typography and anchor across shots with different text and size', () => {
  const a = compile([entity('resource', {kind: 'server', label: 'Server'})]);
  const b = compile([entity('resource', {kind: 'server', size: 1.5, label: 'Server after authentication'})]);
  const slots = planLabelSlots([{program: a, frames: [0]}, {program: b, frames: [0]}], [1]);
  const [before] = labelsAt(a, 0, slots);
  const [after] = labelsAt(b, 0, slots);
  assert.equal(before.fontSize, after.fontSize);
  assert.equal(before.x, after.x);
  assert.equal(before.y, after.y);
  assert.deepEqual(before.bounds, after.bounds);
});

test('entity serialization order cannot change the shared scene label plan', () => {
  const entities = [entity('alpha', {x: 45}), entity('beta', {x: 55})];
  const forward = compile(entities);
  const backward = compile([...entities].reverse());
  const a = planLabelSlots([{program: forward, frames: [0]}]);
  const b = planLabelSlots([{program: backward, frames: [0]}]);
  assert.deepEqual([...a], [...b]);
  assert.deepEqual(a.layouts, b.layouts);
});

test('long multilingual text stays within a narrow viewport without changing size during travel', () => {
  const p = compile([entity('labelled', {x: 5, y: 50, label: '資料處理進度與資源使用情況 Client processing status'})],
    [action('labelled', 'move', {x: 25, y: 50})]);
  const viewport = {x: 0, y: 0, width: 360, height: 500};
  const slots = planLabelSlots([{program: p, frames: sceneFrames(0, 121)}], [0, 1], {viewport, fontScale: 1.25});
  const sizes = new Set();
  for (let frame = 0; frame <= 120; frame++) {
    const [label] = labelsAt(p, frame, slots, viewport);
    inside(label.bounds, viewport);
    sizes.add(label.fontSize);
  }
  assert.equal(sizes.size, 1);
});
