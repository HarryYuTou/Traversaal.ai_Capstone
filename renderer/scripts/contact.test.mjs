import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';
const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  let {outputText} = ts.transpileModule(await readFile(file, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
  }});
  for (const match of [...outputText.matchAll(/from (['"])(\.\/[^'"]+)\1/g)]) {
    outputText = outputText.replace(match[0], `from '${await moduleUrl(new URL(`${match[2]}.ts`, file))}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url); return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, entityAtFrame, contactAnchorAtFrame, displayedPaths, toStage} = await load('engine');
const {fitAuthoredMotionViewport} = await load('camera');
const part = (id, extra = {}) => ({id, parentId: '', x: 0, y: 0, rotation: 0, scaleX: 1, scaleY: 1,
  opacity: 1, shapes: [{kind: 'rect', x: -10, y: -10, width: 20, height: 20, radius: 0, path: '',
    fill: 'accent', stroke: 'none', strokeWidth: 0}], ...extra});
const entity = (id, extra = {}) => ({id, kind: 'custom', rigId: 'body', x: 50, y: 50, size: 1,
  rotation: 0, opacity: 1, value: 0, color: 'accent', label: '', ...extra});
const contact = (extra = {}) => ({entityId: 'source', partId: '', x: 0, y: 10, targetId: 'target',
  targetPartId: '', targetX: 0, targetY: -10, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
  approach: 0, from: 0, durationInFrames: 60, approachFrames: 0, ...extra});
const action = (entityId, from, extra = {}) => ({entityId, kind: 'move', from, durationInFrames: 60,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: '', x: 70, y: 30,
  value: 0, easing: 'ease-in-out', ...extra});
const visual = (extra = {}) => ({title: 'Contact', entities: [entity('source', {y: 30}), entity('target', {y: 70})],
  paths: [], actions: [], rigs: [{id: 'body', parts: [part('body')], clips: []}],
  performances: [], contacts: [contact()], ...extra});
const close = (a, b, epsilon = 1e-7) => assert.ok(Math.abs(a - b) <= epsilon, `${a} != ${b}`);
const grounded = (program, frame) => {
  const [source, target] = program.entities;
  const c = source.contacts[0].contact;
  const a = contactAnchorAtFrame(source, c.partId, c, frame);
  const b = contactAnchorAtFrame(target, c.targetPartId, {x: c.targetX, y: c.targetY}, frame);
  close(a.x, b.x); close(a.y, b.y);
};

test('a planted point remains on a moving support for every frame and releases without resetting', () => {
  const program = compileMotion(visual({actions: [action('target', 0), action('source', 60)]}));
  for (let frame = 0; frame <= 60; frame++) grounded(program, frame);
  const source = program.entities[0];
  const before = toStage(entityAtFrame(source, 60 - 1e-6));
  const after = toStage(entityAtFrame(source, 60 + 1e-6));
  close(before.x, after.x, 1e-5); close(before.y, after.y, 1e-5);
  const release = toStage(entityAtFrame(source, 60));
  const end = toStage(entityAtFrame(source, 120));
  close(end.x - release.x, 240); close(end.y - release.y, 0);
});

test('acquisition is continuous and converges onto contact instead of snapping', () => {
  const program = compileMotion(visual({contacts: [contact({from: 30, startOffset: 0.2, approach: 0.25, approachFrames: 15})]}));
  const source = program.entities[0];
  close(entityAtFrame(source, 30 - 1e-6).y, entityAtFrame(source, 30 + 1e-6).y);
  const ys = Array.from({length: 16}, (_, i) => entityAtFrame(source, 30 + i).y);
  for (let i = 1; i < ys.length; i++) assert.ok(ys[i] >= ys[i - 1]);
  for (let frame = 45; frame <= 90; frame++) grounded(program, frame);
  close(entityAtFrame(source, 90).y, entityAtFrame(source, 500).y);
});

test('part anchors honor nested rotations and nonuniform scales, including animated source and target parts', () => {
  const rig = {id: 'body', parts: [part('body', {rotation: 20, scaleX: 1.5}),
    part('joint', {parentId: 'body', x: 25, y: -18, rotation: -35, scaleY: 2})],
  clips: [{id: 'turn', tracks: [{partId: 'joint', property: 'rotation',
    keyframes: [{at: 0, value: 0, easing: 'linear'}, {at: 1, value: 70, easing: 'ease-in-out'}]}]}]};
  const c = contact({partId: 'joint', targetPartId: 'joint', x: 8, y: 12, targetX: -8, targetY: -12});
  const program = compileMotion(visual({entities: [entity('source', {rotation: 50, size: 1.8}),
    entity('target', {rotation: -15, size: 0.8})], rigs: [rig], contacts: [c], performances: ['source', 'target'].map((entityId) =>
    ({entityId, clipId: 'turn', from: 0, durationInFrames: 60, repeat: 1}))}));
  for (let frame = 0; frame <= 60; frame++) grounded(program, frame);
});

test('contact chains evaluate correctly in any entity order and random seeks do not mutate the plan', () => {
  const input = visual({entities: [entity('source'), entity('target'), entity('carrier')], contacts: [
    contact(), contact({entityId: 'target', targetId: 'carrier'})], actions: [action('carrier', 0)]});
  const original = JSON.stringify(input); const program = compileMotion(input);
  const frames = [0, 45, 17, 60, 3, 120, 30];
  const positions = new Map(frames.map((f) => [f, entityAtFrame(program.entities[0], f)]));
  for (const frame of frames.reverse()) assert.deepEqual(entityAtFrame(program.entities[0], frame), positions.get(frame));
  const reordered = compileMotion({...input, entities: [...input.entities].reverse()});
  for (const frame of frames) assert.deepEqual(entityAtFrame(reordered.entities[2], frame), positions.get(frame));
  assert.equal(JSON.stringify(input), original);
});

test('contact motion is identical at 24, 30 and 60 fps', () => {
  const at = (fps, seconds) => {
    const program = compileMotion(visual({contacts: [contact({durationInFrames: fps * 2,
      from: fps, startOffset: 0.2, approach: 0.25, approachFrames: fps / 2})],
    actions: [action('target', fps, {durationInFrames: fps * 2})]}));
    return toStage(entityAtFrame(program.entities[0], seconds * fps));
  };
  for (const seconds of [0, 1, 1.2, 1.5, 2.75, 3, 7]) for (const fps of [24, 60]) {
    close(at(fps, seconds).x, at(30, seconds).x); close(at(fps, seconds).y, at(30, seconds).y);
  }
});

test('released paths and camera follow the corrected position, including later free travel', () => {
  const input = visual({entities: [entity('source', {x: 20, y: 20}), entity('target', {x: 70, y: 60})],
    actions: [action('source', 60, {kind: 'follow-path', pathId: 'departure'})],
    paths: [{id: 'departure', points: [{x: 20, y: 20}, {x: 40, y: 10}], curved: false, closed: false, color: 'muted'}]});
  const program = compileMotion(input); const source = program.entities[0];
  const route = displayedPaths(program, 90)[0].geometry;
  const start = toStage(entityAtFrame(source, 60)); const end = toStage(entityAtFrame(source, 120));
  close(route.points[0].x, start.x); close(route.points[0].y, start.y);
  close(route.points.at(-1).x, end.x); close(route.points.at(-1).y, end.y);
  const camera = fitAuthoredMotionViewport(program);
  for (let frame = 0; frame <= 120; frame++) {
    const at = toStage(entityAtFrame(source, frame));
    assert.ok(at.x - 10 >= camera.x && at.x + 10 <= camera.x + camera.width);
    assert.ok(at.y - 10 >= camera.y && at.y + 10 <= camera.y + camera.height);
  }
});

test('malformed references, cycles, conflicting travel and overlapping contacts fail before rendering', () => {
  for (const contacts of [[contact({targetId: 'missing'})], [contact({partId: 'missing'})],
    [contact({targetId: 'source'})], [contact({x: Infinity})], [contact({approach: 0.2, approachFrames: 1})],
    [contact({from: 30, startOffset: 0.2})], [contact(), contact({from: 20, approach: 0.2, approachFrames: 12})],
    [contact(), contact({entityId: 'target', targetId: 'source'})]]) {
    assert.throws(() => compileMotion(visual({contacts})), /Invalid contact/);
  }
  assert.throws(() => compileMotion(visual({actions: [action('source', 10)]})), /source travel overlaps/);
});
