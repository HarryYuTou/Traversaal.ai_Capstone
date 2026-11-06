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
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    const dependency = match[2].startsWith('.')
      ? await moduleUrl(new URL(`${match[2]}.ts`, file)) : import.meta.resolve(match[2]);
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, entityAtFrame, toStage} = await load('engine');
const {motionEffectsAtFrame} = await load('motionEffects');
const {entityHalfExtents} = await load('metrics');
const {fitMotionViewport} = await load('camera');
const entity = (kind = 'packet', extra = {}) => ({id: 'traveler', kind, x: 15, y: 50, size: 1,
  rotation: 0, opacity: 1, value: 0, color: 'accent', label: '', ...extra});
const action = (kind = 'move', extra = {}) => ({entityId: 'traveler', kind, from: 30, durationInFrames: 150,
  pathId: '', x: 85, y: 50, value: 360, easing: 'linear', startLine: 0, endLine: 0,
  startOffset: 0, endOffset: 1, ...extra});
const compile = (actor = entity(), actions = [action()], paths = []) => compileMotion({title: 'Direction',
  entities: [actor], actions, paths});
const compare = (actual, expected) => {
  if (typeof actual === 'number') assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} != ${expected}`);
  else if (actual && typeof actual === 'object') {
    assert.deepEqual(Object.keys(actual), Object.keys(expected));
    for (const key of Object.keys(actual)) compare(actual[key], expected[key]);
  } else assert.equal(actual, expected);
};

test('horizontal traces stop outside their own object and fit inside the existing camera', () => {
  for (const direction of [-1, 1]) for (const size of [0.6, 1, 1.8]) {
    const program = compile(entity('packet', {x: direction > 0 ? 15 : 85, size}),
      [action('move', {x: direction > 0 ? 85 : 15})]);
    const {traces} = motionEffectsAtFrame(program, 110);
    assert.equal(traces.length, 1);
    const trace = traces[0];
    const state = entityAtFrame(program.entities[0], 110);
    const point = toStage(state);
    const bounds = entityHalfExtents('packet', size, state.rotation);
    assert.ok((point.x - trace.points.at(-1).x) * direction >= bounds.x + 9.999);
    const camera = fitMotionViewport(program);
    for (const item of [...trace.points, ...trace.arrow]) {
      assert.ok(item.x >= camera.x && item.x <= camera.x + camera.width);
      assert.ok(item.y >= camera.y && item.y <= camera.y + camera.height);
    }
  }
});

test('curved direction traces use actual travel samples rather than shortcuts to a destination', () => {
  const route = {id: 'route', curved: true, closed: false, color: 'muted',
    points: [{x: 15, y: 50}, {x: 30, y: 15}, {x: 58, y: 88}, {x: 85, y: 50}]};
  const program = compile(entity(), [action('follow-path', {pathId: 'route'})], [route]);
  const frame = 120;
  const trace = motionEffectsAtFrame(program, frame).traces[0];
  assert.ok(trace.points.length > 10);
  // Trimming changes only the last point; every earlier point must be an exact historical state.
  const start = frame - 150 * 0.25;
  trace.points.slice(0, -1).forEach((point, index) => {
    compare(point, toStage(entityAtFrame(program.entities[0], start + (frame - start) * index / 48)));
  });
  assert.ok(new Set(trace.points.map(({y}) => y.toFixed(2))).size > 10);
});

test('orbit guides use the physical SVG radius and never invent a zero-angle or zero-radius orbit', () => {
  const moving = compile(entity('moon', {x: 74, y: 50, size: 0.6}),
    [action('orbit', {x: 50, y: 50})]);
  assert.deepEqual(motionEffectsAtFrame(moving, 20), {traces: [], orbits: []});
  const guide = motionEffectsAtFrame(moving, 100).orbits[0];
  assert.equal(guide.radius, 288);
  assert.equal(guide.x, 600);
  assert.equal(guide.y, 250);
  const position = toStage(entityAtFrame(moving.entities[0], 100));
  assert.ok(Math.abs(Math.hypot(position.x - guide.x, position.y - guide.y) - guide.radius) < 1e-8);
  for (const program of [compile(entity('moon', {x: 74}), [action('orbit', {x: 50, value: 0})]),
    compile(entity('moon', {x: 50}), [action('orbit', {x: 50, value: 360})])]) {
    assert.deepEqual(motionEffectsAtFrame(program, 100), {traces: [], orbits: []});
  }
});

test('process scenes, people, stationary actors and invisible actors gain no direction decoration', () => {
  assert.deepEqual(motionEffectsAtFrame(compile(), 100, 30, true), {traces: [], orbits: []});
  for (const program of [compile(entity('person')), compile(entity('box')), compile(entity(), []),
    compile(entity(), [action('move', {x: 15, y: 50})]), compile(entity('packet', {opacity: 0}))]) {
    assert.deepEqual(motionEffectsAtFrame(program, 100), {traces: [], orbits: []});
  }
});

test('direction cues fade to zero at action boundaries without claiming an engine burn', () => {
  const program = compile(entity('spacecraft'));
  assert.deepEqual(motionEffectsAtFrame(program, 30), {traces: [], orbits: []});
  const during = motionEffectsAtFrame(program, 100);
  assert.equal(during.traces.length, 1);
  assert.ok(during.traces[0].opacity > 0);
  assert.deepEqual(Object.keys(during).sort(), ['orbits', 'traces']);
  const ending = motionEffectsAtFrame(program, 179.999).traces[0];
  assert.ok(ending.opacity < 1e-6);
  assert.deepEqual(motionEffectsAtFrame(program, 180), {traces: [], orbits: []});
});

test('equal physical times at 24, 30 and 60 fps produce identical traces and orbit guides', () => {
  for (const kind of ['move', 'orbit']) {
    const programs = [24, 30, 60].map((fps) => ({fps,
      program: compile(entity(kind === 'orbit' ? 'moon' : 'packet', kind === 'orbit' ? {x: 74, size: 0.6} : {}),
        [action(kind, {from: fps, durationInFrames: fps * 5, x: kind === 'orbit' ? 50 : 85})])}));
    for (const seconds of [0, 1, 1.2, 1.8, 2.5, 3.25, 5.8, 5.999, 6, 7]) {
      const expected = motionEffectsAtFrame(programs[1].program, seconds * 30, 30);
      for (const {fps, program} of programs) compare(motionEffectsAtFrame(program, seconds * fps, fps), expected);
    }
  }
});

test('random seeking preserves all authored states, path geometry and prepared programs', () => {
  const program = compile(entity('moon', {x: 74, size: 0.6}), [action('orbit', {x: 50})]);
  const before = JSON.stringify(program);
  const frames = [0, 30, 50, 95, 130.25, 179, 180, 250];
  const expected = frames.map((frame) => ({effects: motionEffectsAtFrame(program, frame),
    state: entityAtFrame(program.entities[0], frame)}));
  for (const frame of [400, 70, 0, 165.5, 25]) motionEffectsAtFrame(program, frame);
  frames.forEach((frame, index) => {
    assert.deepEqual(motionEffectsAtFrame(program, frame), expected[index].effects);
    assert.deepEqual(entityAtFrame(program.entities[0], frame), expected[index].state);
  });
  assert.equal(JSON.stringify(program), before);
});
