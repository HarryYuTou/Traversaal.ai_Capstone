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
const {compileMotion, entityAtFrame} = await load('engine');
const {objectPerformanceAtFrame, OBJECT_CUE_KINDS} = await load('objectPerformance');
const {ENTITY_EXTENTS} = await load('metrics');
const entity = (kind = 'box', id = 'item') => ({id, kind, x: 20, y: 50, size: 1.4, rotation: 0,
  opacity: 1, value: 0, color: 'accent', label: ''});
const cue = (kind, from = 30, durationInFrames = 90, extra = {}) => ({entityId: 'item', kind,
  from, durationInFrames, ...extra});
const action = (kind, from = 10, durationInFrames = 90, extra = {}) => ({entityId: 'item', kind,
  from, durationInFrames, pathId: '', x: 70, y: 50, value: 1, easing: 'linear',
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, ...extra});
const compile = (kind, cues = [], actions = [], activities = []) => compileMotion({title: 'Object behavior',
  entities: [entity(kind)], paths: [], actions, activities, cues}).entities[0];
const close = (actual, expected, path = 'pose') => {
  if (typeof actual === 'number') {
    // A periodic work phase at 0 and 1 describes the same rendered pose across float rounding.
    const delta = Math.abs(actual - expected);
    const periodic = path === 'pose.phase' || path === 'pose.activity.phase';
    assert.ok((periodic ? Math.min(delta, Math.abs(1 - delta)) : delta) < 1e-7, `${path}: ${actual} != ${expected}`);
  }
  else if (actual && typeof actual === 'object') {
    assert.deepEqual(Object.keys(actual), Object.keys(expected));
    for (const key of Object.keys(actual)) close(actual[key], expected[key], `${path}.${key}`);
  } else assert.equal(actual, expected, path);
};
const finite = (value, path = 'pose') => {
  if (typeof value === 'number') assert.ok(Number.isFinite(value), `${path} must be finite`);
  else if (value && typeof value === 'object') Object.entries(value).forEach(([key, item]) => finite(item, `${path}.${key}`));
};

test('packing visibly progresses from open flaps to tape and label, then persists during departure', () => {
  const prepared = compile('box', [cue('pack')], [action('move', 135, 60)]);
  assert.deepEqual(objectPerformanceAtFrame(prepared, 0).pack, {close: 0, tape: 0, label: 0});
  const early = objectPerformanceAtFrame(prepared, 53).pack;
  assert.ok(early.close > 0 && early.close < 1);
  assert.equal(early.tape, 0);
  const sealing = objectPerformanceAtFrame(prepared, 90).pack;
  assert.equal(sealing.close, 1);
  assert.ok(sealing.tape > 0 && sealing.tape < 1);
  assert.equal(sealing.label, 0);
  for (const frame of [120, 160, 300]) {
    assert.deepEqual(objectPerformanceAtFrame(prepared, frame).pack, {close: 1, tape: 1, label: 1});
  }
  assert.notEqual(entityAtFrame(prepared, 160).x, entityAtFrame(prepared, 120).x,
    'the completed package stays sealed while actually leaving');
});

test('unfinished packing and generic service cannot invent a shipping-ready parcel', () => {
  const unfinished = compile('box', [cue('pack', 30, 90, {complete: false})]);
  assert.deepEqual(objectPerformanceAtFrame(unfinished, 200).pack, {close: 1, tape: 0, label: 0});
  const service = compile('box', [], [], [{entityId: 'item', kind: 'work', from: 30, durationInFrames: 90}]);
  assert.ok(objectPerformanceAtFrame(service, 70).processing > 0);
  assert.equal(objectPerformanceAtFrame(service, 70).pack, null);
  assert.equal(objectPerformanceAtFrame(service, 200).pack, null);
  assert.equal(objectPerformanceAtFrame(service, 200).complete, 0);
});

test('a completed package never reopens because a later packing cue is encountered', () => {
  const prepared = compile('box', [cue('pack', 30, 60), cue('pack', 150, 60)]);
  for (const frame of [100, 150, 180, 220]) {
    assert.deepEqual(objectPerformanceAtFrame(prepared, frame).pack, {close: 1, tape: 1, label: 1});
  }
});

test('continued packing preserves the closed flaps at a scene boundary before finishing the seal', () => {
  const before = compile('box', [cue('pack', 30, 60, {complete: false})]);
  const after = compile('box', [cue('pack', 90, 90, {continued: true})]);
  assert.deepEqual(objectPerformanceAtFrame(before, 90).pack, objectPerformanceAtFrame(after, 90).pack);
  assert.deepEqual(objectPerformanceAtFrame(after, 90).pack, {close: 1, tape: 0, label: 0});
  const later = objectPerformanceAtFrame(after, 145).pack;
  assert.equal(later.close, 1);
  assert.equal(later.tape, 1);
  assert.ok(later.label > 0 && later.label < 1);
  assert.deepEqual(objectPerformanceAtFrame(after, 180).pack, {close: 1, tape: 1, label: 1});
});

test('explicit receive and compute stay local to their intervals and never claim completion', () => {
  const prepared = compile('server', [cue('receive', 30, 30), cue('compute', 65, 70)]);
  assert.equal(objectPerformanceAtFrame(prepared, 29).signal, null);
  assert.equal(objectPerformanceAtFrame(prepared, 45).signal.kind, 'receive');
  assert.ok(objectPerformanceAtFrame(prepared, 45).signal.opacity > 0);
  assert.equal(objectPerformanceAtFrame(prepared, 60).signal, null);
  assert.ok(objectPerformanceAtFrame(prepared, 90).compute.opacity > 0);
  for (const frame of [0, 45, 90, 140, 300]) assert.equal(objectPerformanceAtFrame(prepared, frame).complete, 0);
  assert.equal(objectPerformanceAtFrame(prepared, 140).compute, null);
});

test('nearby packet movement does not make a receiver signal, process, or succeed without a cue', () => {
  const program = compileMotion({title: 'Unconfirmed transfer', paths: [],
    entities: [entity('packet', 'packet'), {...entity('server', 'receiver'), x: 70}],
    actions: [action('move', 10, 90, {entityId: 'packet'})],
    cues: [cue('send', 10, 30, {entityId: 'packet'})]});
  const receiver = program.entities.find(({entity: item}) => item.id === 'receiver');
  for (const frame of [0, 30, 99, 100, 110, 200]) {
    const pose = objectPerformanceAtFrame(receiver, frame);
    assert.equal(pose.signal, null);
    assert.equal(pose.compute, null);
    assert.equal(pose.processing, 0);
    assert.equal(pose.complete, 0);
  }
});

test('coasting spacecraft never gain thrust from translation and a burn fades at both boundaries', () => {
  const travel = [action('move', 10, 150)];
  const coast = compile('spacecraft', [], travel);
  const burn = compile('spacecraft', [cue('thrust', 30, 60)], travel);
  for (const frame of [10, 40, 80, 120, 170]) assert.equal(objectPerformanceAtFrame(coast, frame).thrust, 0);
  assert.equal(objectPerformanceAtFrame(burn, 30).thrust, 0);
  assert.ok(objectPerformanceAtFrame(burn, 35).thrust > 0);
  assert.equal(objectPerformanceAtFrame(burn, 60).thrust, 1);
  assert.equal(objectPerformanceAtFrame(burn, 90).thrust, 0);
  assert.equal(objectPerformanceAtFrame(burn, 120).thrust, 0);
  for (const frame of [10, 40, 80, 120, 170]) {
    assert.deepEqual(entityAtFrame(burn, frame), entityAtFrame(coast, frame));
  }
});

test('all 19 entity kinds remain finite and ignore capabilities they do not support', () => {
  assert.equal(Object.keys(ENTITY_EXTENTS).length, 19);
  for (const kind of Object.keys(ENTITY_EXTENTS)) {
    for (const cueKind of Object.keys(OBJECT_CUE_KINDS)) {
      const prepared = compile(kind, [cue(cueKind)]);
      for (const frame of [0, 30, 31.5, 75, 119.9, 120, 300]) finite(objectPerformanceAtFrame(prepared, frame));
      if (OBJECT_CUE_KINDS[cueKind].includes(kind)) continue;
      const pose = objectPerformanceAtFrame(prepared, 75);
      assert.equal(pose.pack, null, `${kind} cannot pack`);
      assert.equal(pose.scan, null, `${kind} cannot scan`);
      assert.equal(pose.signal, null, `${kind} cannot signal`);
      assert.equal(pose.compute, null, `${kind} cannot compute`);
      assert.equal(pose.thrust, 0, `${kind} cannot thrust`);
    }
  }
});

test('equivalent physical times at 24, 30, and 60 fps give the same acting', () => {
  for (const [kind, cueKinds] of [['box', ['pack', 'scan']], ['server', ['send', 'receive', 'compute']],
    ['spacecraft', ['thrust']], ['gauge', []]]) {
    const sourceCues = cueKinds.map((name, index) => cue(name, 30 + index * 110, 90));
    const sourceActions = [action('move', 15, 120), action('value', 150, 90, {value: 0.8})];
    const sourceActivities = [{entityId: 'item', kind: 'work', from: 30, durationInFrames: 90},
      {entityId: 'item', kind: 'complete', from: 120, durationInFrames: 18}];
    const atRate = (items, fps) => items.map((item) => ({...item, from: item.from * fps / 30,
      durationInFrames: item.durationInFrames * fps / 30}));
    const programs = [24, 30, 60].map((fps) => ({fps, prepared: compile(kind,
      atRate(sourceCues, fps), atRate(sourceActions, fps), atRate(sourceActivities, fps))}));
    for (const seconds of [0, 0.8, 1, 1.06, 1.4, 2.8, 3.8, 4.12, 4.6, 5.3, 6.4, 8.8, 11.8]) {
      const expected = objectPerformanceAtFrame(programs[1].prepared, seconds * 30, 30);
      for (const {fps, prepared} of programs) close(objectPerformanceAtFrame(prepared, seconds * fps, fps), expected);
    }
  }
});

test('random seeking leaves prepared cues and every authored state unchanged', () => {
  const source = {title: 'Deterministic packing', entities: [entity()], paths: [],
    actions: [action('move'), action('rotate', 110, 60, {value: 45})],
    cues: [cue('scan', 125, 45), cue('pack', 20, 90)], activities: []};
  const sourceSnapshot = JSON.stringify(source);
  const prepared = compileMotion(source).entities[0];
  const preparedSnapshot = JSON.stringify(prepared);
  const frames = [0, 20, 28.5, 50, 90, 100, 130, 160, 180, 300];
  const expected = frames.map((frame) => ({pose: objectPerformanceAtFrame(prepared, frame),
    state: entityAtFrame(prepared, frame)}));
  for (const frame of [500, 75, -15, 125, 7, 99.25, 0]) objectPerformanceAtFrame(prepared, frame);
  frames.forEach((frame, index) => {
    assert.deepEqual(objectPerformanceAtFrame(prepared, frame), expected[index].pose);
    assert.deepEqual(entityAtFrame(prepared, frame), expected[index].state);
  });
  assert.equal(JSON.stringify(source), sourceSnapshot);
  assert.equal(JSON.stringify(prepared), preparedSnapshot);
});

test('stationary position and unchanged value actions do not invent arrivals or changes', () => {
  const prepared = compile('marker', [], [action('move', 10, 60, {x: 20, y: 50}),
    action('value', 20, 60, {value: 0}), action('rotate', 20, 60, {value: 0})]);
  for (const frame of [0, 30, 65, 70, 75, 84, 90]) {
    const pose = objectPerformanceAtFrame(prepared, frame);
    assert.equal(pose.arrival, 0);
    assert.equal(pose.change, 0);
  }
});
