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
const {illustrationPoseAtFrame, performanceAtFrame, personLimbs} = await load('pose');
const entity = {id: 'participant', kind: 'person', x: 20, y: 50, size: 1, rotation: 0,
  opacity: 1, value: 1, color: 'accent', label: 'Participant'};
const action = (kind, from, durationInFrames, values = {}) => ({entityId: entity.id, kind,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0,
  value: 0, easing: 'walk', from, durationInFrames, ...values});
const compile = (actions, activities = [], paths = [], actor = entity) =>
  compileMotion({title: 'Performance regression', entities: [actor], actions, activities, paths}).entities[0];
const actions = [action('move', 30, 60, {x: 70, y: 50}), action('move', 120, 45, {x: 30, y: 50})];
const activities = [{entityId: entity.id, kind: 'work', from: 90, durationInFrames: 30},
  {entityId: entity.id, kind: 'complete', from: 120, durationInFrames: 18}];
const compare = (actual, expected) => {
  if (typeof actual === 'number') assert.ok(Math.abs(actual - expected) < 1e-7, `${actual} != ${expected}`);
  else if (actual && typeof actual === 'object') {
    assert.deepEqual(Object.keys(actual), Object.keys(expected));
    for (const key of Object.keys(actual)) compare(actual[key], expected[key]);
  } else assert.equal(actual, expected);
};

test('gaze anticipates a departure without moving the actor and persists through a stop', () => {
  const p = compile(actions, activities);
  assert.equal(performanceAtFrame(p, 24).lookX, 0);
  assert.ok(performanceAtFrame(p, 28).lookX > 0);
  assert.equal(entityAtFrame(p, 28).x, entity.x, 'preparation cannot shift authored position');
  assert.equal(performanceAtFrame(p, 100).lookX, 1, 'attention remains on the destination');
  assert.ok(performanceAtFrame(p, 117).lookX < 1, 'the next departure turns attention before moving');
  assert.equal(performanceAtFrame(p, 180).lookX, -1);
});

test('continuous adjacent direction changes turn attention across the seam instead of snapping', () => {
  const p = compile([actions[0], action('move', 90, 60, {x: 25, y: 50})]);
  assert.ok(performanceAtFrame(p, 88).lookX < 1);
  assert.ok(Math.abs(performanceAtFrame(p, 90 - 0.001).lookX - performanceAtFrame(p, 90 + 0.001).lookX) < 0.002);
});

test('equal physical times at 24, 30 and 60 fps produce the same performance and stride', () => {
  const programs = [24, 30, 60].map((fps) => ({fps, p: compile(
    actions.map((item) => ({...item, from: item.from * fps / 30, durationInFrames: item.durationInFrames * fps / 30})),
    activities.map((item) => ({...item, from: item.from * fps / 30, durationInFrames: item.durationInFrames * fps / 30}))),
  }));
  for (const seconds of [0.3, 0.86, 0.94, 1.03, 1.4, 2.6, 2.98, 3.05, 3.13, 3.4, 4.08, 4.3, 5.52]) {
    const expected = illustrationPoseAtFrame(programs[1].p, seconds * 30, 30);
    for (const {fps, p} of programs) compare(illustrationPoseAtFrame(p, seconds * fps, fps), expected);
  }
});

test('random seeking cannot alter poses, entity states, activities or authored tracks', () => {
  const p = compile(actions, activities);
  const source = JSON.stringify(p);
  const frames = [0, 28, 33, 51, 89, 91, 101, 120, 125, 138, 165, 300];
  const poses = frames.map((frame) => illustrationPoseAtFrame(p, frame));
  const states = frames.map((frame) => entityAtFrame(p, frame));
  [140, 12, 500, 33, 0, 129, 50, 27].forEach((frame) => illustrationPoseAtFrame(p, frame));
  frames.forEach((frame, index) => {
    assert.deepEqual(illustrationPoseAtFrame(p, frame), poses[index]);
    assert.deepEqual(entityAtFrame(p, frame), states[index]);
  });
  assert.equal(JSON.stringify(p), source);
});

test('arrival settles once, reach blends in, and completion acknowledges once within its event', () => {
  const p = compile([actions[0]], activities);
  assert.equal(performanceAtFrame(p, 90).settle, 0);
  assert.ok(performanceAtFrame(p, 96).settle > 1);
  assert.equal(performanceAtFrame(p, 102).settle, 0);
  assert.equal(performanceAtFrame(p, 90).reach, 0);
  assert.ok(performanceAtFrame(p, 93).reach > 0 && performanceAtFrame(p, 93).reach < 1);
  assert.equal(performanceAtFrame(p, 97).reach, 1);
  assert.equal(performanceAtFrame(p, 127).reach, 0);
  assert.equal(performanceAtFrame(p, 120).acknowledge, 0);
  assert.equal(performanceAtFrame(p, 129).acknowledge, 1);
  assert.equal(performanceAtFrame(p, 138).acknowledge, 0);
  assert.equal(performanceAtFrame(p, 200).acknowledge, 0);
});

test('each stride keeps a supporting foot on the floor and all limbs inside the footprint', () => {
  for (const direction of [-1, 0, 1]) for (let frame = 0; frame < 200; frame++) {
    const pose = {movement: {walking: true, phase: frame / 200, strength: 1, facing: direction}, activity: null,
      carry: 0, performance: {lookX: direction, lean: 0, headTilt: 0, settle: 0, reach: 0, acknowledge: 0}};
    const limbs = personLimbs(pose);
    assert.ok([limbs.leftLeg.at(-1), limbs.rightLeg.at(-1)].some(({y}) => y === 60), 'one foot remains planted');
    for (const points of Object.values(limbs)) for (const point of points) {
      assert.ok(Math.abs(point.x) <= 38 && point.y <= 60 && Number.isFinite(point.y));
    }
  }
  const p = compile([actions[0]], activities);
  for (let frame = 0; frame <= 150; frame++) {
    for (const points of Object.values(personLimbs(illustrationPoseAtFrame(p, frame)))) for (const point of points) {
      assert.ok(Math.abs(point.x) <= 38 && point.y <= 60);
    }
  }
});

test('a planted vector shoe cancels world travel and follows the actual tangent rather than gaze', () => {
  for (const direction of [-1, 1]) for (const size of [0.7, 1, 1.4]) {
    const actor = {...entity, x: 50, size};
    const p = compile([action('move', 30, 120, {x: 50 + direction * 44, y: 50, easing: 'linear'})], [], [], actor);
    // The body has travelled 11 and 15.4 scaled units: both samples lie in the left foot's stance.
    const frames = [30 + 11 * size / 4.4, 30 + 15.4 * size / 4.4];
    // Wait for full gait strength before sampling, preserving the same stride phases.
    const cycles = Math.ceil(5 * 4.4 / (44 * size));
    const shoes = frames.map((frame) => {
      const at = frame + cycles * 44 * size / 4.4;
      const pose = illustrationPoseAtFrame(p, at);
      assert.equal(pose.movement.strength, 1);
      // Simulate attention already turning in the opposite direction; planted feet must not follow it.
      pose.performance.lookX = -direction;
      const foot = personLimbs(pose).leftLeg.at(-1);
      assert.equal(foot.y, 60);
      const state = entityAtFrame(p, at);
      return toStage(state).x + foot.x * state.size;
    });
    assert.ok(Math.abs(shoes[1] - shoes[0]) < 1e-8, `sliding shoe: ${shoes.join(' -> ')}`);
  }
});

test('curved paths and extreme finite orbits produce bounded secondary motion', () => {
  const path = {id: 'route', points: [{x: 20, y: 50}, {x: 45, y: 10}, {x: 65, y: 80}, {x: 80, y: 50}],
    curved: true, closed: false, color: 'muted'};
  const programs = [compile([action('follow-path', 30, 90, {pathId: 'route'})], [], [path]),
    compile([action('orbit', 30, 90, {x: 50, y: 50, value: 360})]),
    compile([action('orbit', 30, 90, {x: 50, y: 50, value: 1e308})])];
  for (const p of programs) for (let frame = 0; frame <= 150; frame++) {
    const pose = illustrationPoseAtFrame(p, frame);
    for (const value of Object.values(pose.performance)) assert.ok(Number.isFinite(value));
    assert.ok(Math.abs(pose.performance.lookX) <= 1);
    assert.ok(Math.abs(pose.performance.lean) <= 3.4);
    assert.ok(Math.abs(pose.performance.headTilt) <= 3.5);
    assert.ok(pose.performance.settle >= 0 && pose.performance.settle <= 1.4);
    assert.ok(pose.performance.reach >= 0 && pose.performance.reach <= 1);
  }
});

test('stationary tracks and nonhuman entities gain no invented performance', () => {
  const stationary = compile([action('move', 30, 60, {x: entity.x, y: entity.y})]);
  for (const frame of [0, 28, 35, 80, 91, 200]) {
    assert.equal(performanceAtFrame(stationary, frame).lookX, 0);
    assert.equal(performanceAtFrame(stationary, frame).lean, 0);
    assert.equal(performanceAtFrame(stationary, frame).settle, 0);
  }
  for (const kind of ['spacecraft', 'packet', 'server', 'box', 'moon']) {
    const p = compile(actions, activities, [], {...entity, kind});
    assert.equal(illustrationPoseAtFrame(p, 50).performance, undefined);
    assert.equal(illustrationPoseAtFrame(p, 50).idle, undefined);
    assert.equal(illustrationPoseAtFrame(p, 50).movement.walking, false);
  }
});
