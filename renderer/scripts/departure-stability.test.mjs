import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  let {outputText} = ts.transpileModule(await readFile(file, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React,
  }});
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    const local = (extension) => new URL(`${match[2]}${extension}`, file);
    let dependency = match[2].startsWith('.')
      ? await moduleUrl(existsSync(local('.ts')) ? local('.ts') : local('.tsx')) : import.meta.resolve(match[2]);
    // Match the bundler's CommonJS default import for the sketch artwork package.
    if (match[2] === 'react-peeps') dependency = `data:text/javascript;base64,${Buffer.from(
      `import pkg from '${dependency}'; export default pkg.default ?? pkg;`).toString('base64')}`;
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, entityAtFrame} = await load('engine');
const {illustrationPoseAtFrame} = await load('pose');
const {sketchView} = await import(await moduleUrl(new URL('../src/motion/sketch.tsx', import.meta.url)));

const entity = {id: 'traveller', kind: 'person', x: 54.166666666666664, y: 50,
  size: 1, rotation: 0, opacity: 1, value: 0, color: 'accent', label: 'Traveller'};
const action = (kind, from, durationInFrames, values = {}) => ({entityId: entity.id, kind,
  from, durationInFrames, x: 0, y: 0, value: 0, pathId: '', easing: 'walk',
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, ...values});
const route = (points) => ({id: 'route', points, curved: false, closed: false, color: 'muted'});
const compile = (actions, paths = [], actor = entity, fps = 30) => compileMotion({
  title: 'Departure stability', entities: [actor], paths,
  actions: actions.map((item) => ({...item, from: item.from * fps / 30,
    durationInFrames: item.durationInFrames * fps / 30})),
}).entities[0];
const poseAt = (prepared, frame, fps) => illustrationPoseAtFrame(prepared, frame * fps / 30, fps);
const flipCount = (views) => views.filter((view, index) => index > 0 && view !== views[index - 1]).length;
const departures = [];
for (const x of [54.166666666666664, 46.666666666666664]) {
  for (const horizontal of [-1, 1]) for (const vertical of [-1, 1]) {
    departures.push({x, horizontal, vertical, path: route([
      {x, y: 50}, {x, y: 50 + vertical * 22}, {x: x + horizontal * (68.33333333333333 - x), y: 50 + vertical * 22},
    ])});
  }
}

test('fractional-coordinate vertical departures have no invented horizontal gaze or movement', () => {
  for (const fps of [24, 30, 60]) for (const departure of departures) {
    const prepared = compile([action('follow-path', 1190, 67, {pathId: 'route'})],
      [departure.path], {...entity, x: departure.x}, fps);
    for (let frame = 1183; frame <= 1205; frame += 0.25) {
      const pose = poseAt(prepared, frame, fps);
      const context = `${fps} fps, x ${departure.x}, direction ${departure.horizontal}/${departure.vertical}, frame ${frame}`;
      assert.equal(pose.performance.lookX, 0, `no horizontal attention during the vertical leg: ${context}`);
      assert.equal(pose.movement.facing, 0, `no horizontal gait during the vertical leg: ${context}`);
      assert.equal(sketchView(pose).facing, 'right', `neutral artwork must not mirror: ${context}`);
    }
  }
});

test('vertical-first routes turn only once toward a real leftward leg and never twitch on a rightward leg', () => {
  for (const fps of [24, 30, 60]) for (const departure of departures) {
    const prepared = compile([action('follow-path', 1190, 67, {pathId: 'route'})],
      [departure.path], {...entity, x: departure.x}, fps);
    const views = [];
    for (let frame = 1183; frame <= 1263; frame += 0.25) views.push(sketchView(poseAt(prepared, frame, fps)).facing);
    assert.equal(views[0], 'right');
    assert.equal(views.at(-1), departure.horizontal < 0 ? 'left' : 'right');
    assert.equal(flipCount(views), departure.horizontal < 0 ? 1 : 0,
      `${fps} fps, x ${departure.x}, direction ${departure.horizontal}/${departure.vertical}`);
  }
});

test('pure vertical travel preserves the last meaningful horizontal view from a prior action', () => {
  for (const fps of [24, 30, 60]) for (const y of [28, 72]) {
    const prepared = compile([
      action('move', 20, 60, {x: entity.x, y: 50}),
      action('move', 110, 60, {x: entity.x, y}),
    ], [], {...entity, x: 80}, fps);
    for (let frame = 81; frame <= 190; frame += 0.25) {
      const pose = poseAt(prepared, frame, fps);
      assert.equal(pose.performance.lookX, -1, `${fps} fps, y ${y}, frame ${frame}`);
      assert.equal(sketchView(pose).facing, 'left');
    }
  }
});

test('a vertical final segment retains the horizontal view established earlier within the same route', () => {
  for (const fps of [24, 30, 60]) for (const y of [28, 72]) {
    const prepared = compile([action('follow-path', 20, 90, {pathId: 'route', easing: 'linear'})],
      [route([{x: 80, y: 50}, {x: entity.x, y: 50}, {x: entity.x, y}])], {...entity, x: 80}, fps);
    for (let frame = 25; frame <= 135; frame += 0.25) {
      const pose = poseAt(prepared, frame, fps);
      assert.ok(pose.performance.lookX < 0, `${fps} fps, y ${y}, frame ${frame}`);
      assert.equal(sketchView(pose).facing, 'left');
    }
  }
});

test('subpixel tangent noise cannot select opposite sketch artwork', () => {
  for (const lookX of [-1e-12, -Number.EPSILON, 0, Number.EPSILON, 1e-12]) {
    const pose = {movement: {walking: false, phase: 0, strength: 0, facing: lookX}, activity: null,
      performance: {lookX, lean: 0, headTilt: 0, settle: 0, reach: 0, acknowledge: 0}};
    assert.equal(sketchView(pose).facing, 'right', `neutral gaze ${lookX}`);
  }
});

test('fractional random seeks reproduce poses and never change authored tracks or actor positions', () => {
  for (const fps of [24, 30, 60]) {
    const path = route([{x: entity.x, y: 50}, {x: entity.x, y: 28}, {x: 68.33333333333333, y: 28}]);
    const prepared = compile([action('follow-path', 1190, 67, {pathId: 'route'})], [path], entity, fps);
    const source = JSON.stringify(prepared);
    const frames = [1184.125, 1189.75, 1190, 1191.375, 1202.625, 1224.875, 1256.875, 1257, 1265.25];
    const states = frames.map((frame) => entityAtFrame(prepared, frame * fps / 30));
    const poses = frames.map((frame) => poseAt(prepared, frame, fps));
    for (const frame of [1257.125, 1183.625, 1260.25, 1190.375, 1215.5, 1200.75]) poseAt(prepared, frame, fps);
    frames.forEach((frame, index) => {
      assert.deepEqual(poseAt(prepared, frame, fps), poses[index]);
      assert.deepEqual(entityAtFrame(prepared, frame * fps / 30), states[index]);
    });
    assert.equal(states[0].x, entity.x, 'anticipation cannot move the authored starting point');
    assert.equal(states[0].y, entity.y);
    assert.ok(Math.abs(states.at(-1).x - 68.33333333333333) < 1e-12);
    assert.ok(Math.abs(states.at(-1).y - 28) < 1e-12);
    assert.equal(JSON.stringify(prepared), source);
  }
});
