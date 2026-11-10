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
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {prepareRig, rigPoseAtFrame} = await load('rig');
const {compileMotion, entityAtFrame, contactAnchorAtFrame} = await load('engine');
const shape = {kind: 'rect', x: -8, y: -6, width: 16, height: 12, radius: 1,
  path: '', fill: 'accent', stroke: 'ink', strokeWidth: 1};
const part = (id, extra = {}) => ({id, parentId: '', x: 0, y: 0, rotation: 0,
  scaleX: 1, scaleY: 1, opacity: 1, shapes: [shape], ...extra});
const track = (entries, property = 'x', partId = 'body', easing = 'smooth') => ({partId, property,
  keyframes: entries.map(([at, value]) => ({at, value, easing}))});
const definition = (tracks, parts = [part('body')]) => ({id: 'performer', parts, clips: [{id: 'act', tracks}]});
const performance = (extra = {}) => ({entityId: 'actor', clipId: 'act', startLine: 0, endLine: 0,
  startOffset: 0, endOffset: 1, from: 0, durationInFrames: 120, repeat: 1, ...extra});
const prepare = (tracks, extra = {}) => prepareRig(definition(tracks), [performance(extra)]);
const at = (prepared, progress, property = 'x') => rigPoseAtFrame(prepared, progress * 120).body[property];
const derivativeAt = (evaluate, point, delta = 1e-6) => ({left: (evaluate(point) - evaluate(point - delta)) / delta,
  right: (evaluate(point + delta) - evaluate(point)) / delta});
const close = (a, b, epsilon = 1e-7) => assert.ok(Math.abs(a - b) <= epsilon, `${a} != ${b}`);

test('smooth tracks pass through same-direction keys with continuous nonzero velocity instead of easing to a stop', () => {
  const entries = [[0, 0], [0.3, 20], [0.65, 50], [1, 80]];
  const smooth = prepare([track(entries)]);
  const previous = prepare([track(entries, 'x', 'body', 'ease-in-out')]);
  for (const [time, value] of entries) close(at(smooth, time), value);
  for (const time of [0.3, 0.65]) {
    const velocity = derivativeAt((t) => at(smooth, t), time);
    close(velocity.left, velocity.right, 0.002);
    assert.ok(velocity.left > 50 && velocity.right > 50);
    const stopped = derivativeAt((t) => at(previous, t), time);
    assert.ok(Math.abs(stopped.left) < 0.001 && Math.abs(stopped.right) < 0.001);
  }
});

test('single smooth performances rest at their endpoints and at interior extrema or flat spans', () => {
  const monotone = prepare([track([[0, 0], [0.3, 20], [1, 80]])]);
  const start = derivativeAt((t) => at(monotone, t), 0);
  const end = derivativeAt((t) => at(monotone, t), 1);
  for (const velocity of [start.left, start.right, end.left, end.right]) assert.ok(Math.abs(velocity) < 0.005);
  const turning = prepare([track([[0, 0], [0.25, 30], [0.5, -10], [0.75, -10], [1, 0]])]);
  for (const time of [0.25, 0.5, 0.75]) {
    const velocity = derivativeAt((t) => at(turning, t), time);
    assert.ok(Math.abs(velocity.left) < 0.005 && Math.abs(velocity.right) < 0.005);
  }
  for (const time of [0.51, 0.6, 0.7, 0.74]) close(at(turning, time), -10);
});

test('smooth curves never overshoot segment endpoints despite nonuniform key times and sharp slope changes', () => {
  const entries = [[0, 0], [0.00001, 50], [0.03, 51], [0.04, -30], [0.8, -30], [1, 5]];
  const prepared = prepare([track(entries)]);
  for (let segment = 1; segment < entries.length; segment++) {
    const [from, value] = entries[segment - 1]; const [to, next] = entries[segment];
    for (let sample = 0; sample <= 200; sample++) {
      const result = at(prepared, from * (1 - sample / 200) + to * sample / 200);
      assert.ok(Number.isFinite(result));
      assert.ok(result >= Math.min(value, next) - 1e-10 && result <= Math.max(value, next) + 1e-10);
    }
  }
});

test('tiny valid key intervals cannot overflow tangents or create nonfinite geometry', () => {
  const entries = [[0, 0], [Number.MIN_VALUE, 100], [1e-300, 101], [0.2, -100], [0.9999999999999999, 0], [1, 1]];
  const prepared = prepare([track(entries)]);
  for (const time of [0, Number.MIN_VALUE, 1e-310, 5e-301, 1e-300, 0.1, 0.2, 0.7, 0.9999999999999999, 1]) {
    const result = at(prepared, time);
    assert.ok(Number.isFinite(result), `nonfinite at ${time}`);
    assert.ok(result >= -100 && result <= 101, `overshoot at ${time}: ${result}`);
  }
});

test('periodic smooth tracks share a nonzero seam tangent when the ending and starting directions match', () => {
  const prepared = prepare([track([[0, 0], [0.2, 30], [0.6, -20], [1, 0]])], {repeat: 3, durationInFrames: 360});
  const evaluate = (frame) => rigPoseAtFrame(prepared, frame).body.x;
  for (const seam of [120, 240]) {
    close(evaluate(seam), 0);
    const velocity = derivativeAt(evaluate, seam, 1e-4);
    close(velocity.left, velocity.right, 0.0001);
    assert.ok(velocity.left > 0.4 && velocity.right > 0.4);
  }
  close(evaluate(360), 0);
  close(evaluate(500), 0, 0);
  // Completion holds the neutral pose. The evaluator does not invent post-release momentum.
});

test('periodic seam extrema use a zero tangent and remain within neighboring value bounds', () => {
  const prepared = prepare([track([[0, 0], [0.3, 25], [0.7, 15], [1, 0]])], {repeat: 2, durationInFrames: 240});
  const evaluate = (frame) => rigPoseAtFrame(prepared, frame).body.x;
  const seam = derivativeAt(evaluate, 120, 1e-4);
  assert.ok(Math.abs(seam.left) < 0.0001 && Math.abs(seam.right) < 0.0001);
  for (let frame = 0; frame <= 240; frame += 0.25) assert.ok(evaluate(frame) >= 0 && evaluate(frame) <= 25);
});

test('smooth easing is an explicit whole-track choice and legacy segment curves retain exact values', () => {
  const mixed = track([[0, 0], [0.5, 20], [1, 40]]);
  mixed.keyframes[1].easing = 'linear';
  assert.throws(() => prepare([mixed]), /smooth easing must apply to the whole track/);
  const old = track([[0, 0], [0.5, 20], [1, 40]], 'x', 'body', 'linear');
  old.keyframes[1].easing = 'ease-out'; old.keyframes[2].easing = 'ease-in-out';
  const legacy = prepare([old]);
  close(at(legacy, 0.25), 17.5, 0);
  close(at(legacy, 0.5), 20, 0);
  close(at(legacy, 0.75), 30, 0);
  close(at(legacy, 1), 40, 0);
});

test('smooth scale and opacity retain validated positive and bounded property ranges', () => {
  const prepared = prepare([track([[0, 1], [0.1, 0.1], [0.4, 3], [1, 1]], 'scaleY'),
    track([[0, 0], [0.2, -1], [0.7, -0.2], [1, 0]], 'opacity')]);
  for (let frame = 0; frame <= 120; frame += 0.1) {
    const pose = rigPoseAtFrame(prepared, frame).body;
    assert.ok(pose.scaleY >= 0.1 && pose.scaleY <= 3);
    assert.ok(pose.opacity >= 0 && pose.opacity <= 1);
  }
});

test('smooth articulated anchors remain exactly locked and reproduce across random seeks and frame rates', () => {
  const source = definition([track([[0, 0], [0.25, 15], [0.6, -10], [1, 0]], 'rotation', 'tip'),
    track([[0, 0], [0.3, 8], [0.7, -5], [1, 0]], 'x', 'tip')],
  [part('body'), part('tip', {parentId: 'body', x: 20, y: -15, scaleX: 1.2, scaleY: 0.8})]);
  const entity = (id, extra = {}) => ({id, kind: 'box', x: 50, y: 50, size: 1, rotation: 0,
    opacity: 1, value: 0, color: 'accent', label: '', ...extra});
  const make = (fps) => compileMotion({title: 'Smooth contact', entities: [entity('actor', {kind: 'custom', rigId: 'performer', x: 20}),
    entity('target', {x: 65, y: 58})], paths: [], actions: [], rigs: [source],
  performances: [performance({from: fps, durationInFrames: fps * 4, repeat: 3})],
  contacts: [{entityId: 'actor', targetId: 'target', partId: 'tip', targetPartId: '', x: 5, y: 2,
    targetX: -12, targetY: 6, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
    approach: 0, from: 0, durationInFrames: fps * 6, approachFrames: 0}]}).entities;
  const reference = make(30);
  const snapshot = JSON.stringify(source);
  for (const seconds of [4.5, 1, 2.75, 0, 5.1, 1.13, 3.2, 2, 6]) {
    const refState = entityAtFrame(reference[0], seconds * 30);
    for (const fps of [24, 30, 60]) {
      const [actor, target] = make(fps);
      const frame = seconds * fps;
      const state = entityAtFrame(actor, frame);
      close(state.x, refState.x); close(state.y, refState.y);
      const actual = contactAnchorAtFrame(actor, 'tip', {x: 5, y: 2}, frame);
      const desired = contactAnchorAtFrame(target, '', {x: -12, y: 6}, frame);
      close(actual.x, desired.x); close(actual.y, desired.y);
      assert.deepEqual(rigPoseAtFrame(actor.rig, frame), rigPoseAtFrame(actor.rig, frame));
    }
  }
  assert.equal(JSON.stringify(source), snapshot);
});
