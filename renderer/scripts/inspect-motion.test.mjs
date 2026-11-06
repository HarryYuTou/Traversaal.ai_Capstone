import assert from 'node:assert/strict';
import {test} from 'node:test';
import {inspectTimeline} from './inspect-motion.mjs';

const entity = (id, extra = {}) => ({id, kind: 'person', x: 30, y: 50, size: 0.7, rotation: 0,
  opacity: 1, value: 0, color: 'ink', label: '', ...extra});
const action = (entityId, kind, from, durationInFrames, extra = {}) => ({entityId, kind, from,
  durationInFrames, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
  pathId: '', x: 30, y: 50, value: 0, easing: 'linear', ...extra});
const scene = (id, from, durationInFrames, visual = {}, extra = {}) => ({id, from, durationInFrames,
  template: 'motion', visual: {title: id, entities: [entity('person')], paths: [], actions: [], ...visual},
  lines: [{id: `${id}-line`, text: 'Narration', from: from + 6, durationInFrames: durationInFrames - 12}], ...extra});
const inspect = (...scenes) => inspectTimeline({projectId: 'test', fps: 30, scenes});

test('importing diagnostics does not execute its CLI', () => {
  assert.notEqual(process.exitCode, 1);
});

test('sketch diagnostics include the taller human silhouette', () => {
  const shot = scene('different silhouettes', 0, 10, {entities: [
    entity('a', {x: 50, y: 30}), entity('b', {x: 50, y: 51}),
  ]});
  const timeline = {fps: 30, scenes: [shot]};
  assert.equal(inspectTimeline({...timeline, look: 'vector'}).scenes[0].collisions.length, 0);
  assert.equal(inspectTimeline({...timeline, look: 'sketch'}).scenes[0].collisions.length, 1);
});

test('collisions, holds and suggested samples use absolute frames in every scene', () => {
  const report = inspect(scene('first', 60, 150, {entities: [entity('a'), entity('b')]}),
    scene('later', 900, 180, {entities: [entity('c'), entity('d')]}, {
      processTrace: {events: [{kind: 'start', from: 920, durationInFrames: 30, movementEndFrame: 20}]},
    }));
  for (const item of report.scenes) {
    const [collision] = item.collisions;
    assert.equal(collision.firstFrame, item.from);
    assert.equal(collision.lastFrame, item.from + item.durationInFrames - 1);
    assert.equal(collision.frameCount, item.durationInFrames);
    assert.equal(item.staticHolds[0].from, item.from);
    assert.ok(item.suggestedFrames.every((frame) => frame >= item.from && frame < item.from + item.durationInFrames));
    assert.deepEqual(item.suggestedFrames, [...item.suggestedFrames].sort((a, b) => a - b));
  }
  assert.equal(report.frameReference, 'absolute-video');
  assert.equal(report.status, 'needs-review');
});

test('no-op and invisible motions cannot conceal a long static picture', () => {
  const report = inspect(scene('quiet', 300, 180, {
    entities: [entity('person'), entity('hidden', {opacity: 0})],
    actions: [action('person', 'move', 300, 180),
      action('person', 'value', 300, 180, {value: 1}),
      action('hidden', 'move', 300, 180, {x: 90})],
    activities: [{entityId: 'hidden', kind: 'work', from: 300, durationInFrames: 180}],
  }));
  assert.deepEqual(report.scenes[0].staticHolds.map(({from, durationInFrames}) => ({from, durationInFrames})),
    [{from: 300, durationInFrames: 180}]);
});

test('visible work activity is understood without movement and contributes suggested frames and coverage', () => {
  const report = inspect(scene('work', 600, 180, {
    entities: [entity('station', {kind: 'counter'})],
    activities: [{entityId: 'station', kind: 'work', from: 600, durationInFrames: 180}],
  }, {processTrace: {events: [{kind: 'hold', from: 606, durationInFrames: 168}],
    finalQueue: [], finalService: [{actorId: 'person', stationId: 'station'}], completed: []}}));
  const item = report.scenes[0];
  assert.equal(item.staticHolds.length, 0);
  assert.ok(item.suggestedFrames.includes(689));
  assert.deepEqual(item.eventCoverage[0].activities, [{entityId: 'station', kind: 'work'}]);
  assert.equal(report.status, 'geometry-and-timing-checks-passed');
});

test('a completion badge is a visible acknowledgement, not continuous busy motion', () => {
  const report = inspect(scene('completion', 50, 180, {
    entities: [entity('station', {kind: 'counter'})],
    activities: [{entityId: 'station', kind: 'complete', from: 50, durationInFrames: 180}],
  }));
  assert.equal(report.scenes[0].staticHolds[0].from, 50);
  assert.equal(report.scenes[0].staticHolds[0].durationInFrames, 176);
});

test('adjacent declared holds combine and short scene padding does not create a false warning', () => {
  const report = inspect(scene('reading', 100, 360, {}, {processTrace: {events: [
    {kind: 'hold', from: 106, durationInFrames: 150},
    {kind: 'hold', from: 256, durationInFrames: 180},
  ]}}));
  assert.deepEqual(report.scenes[0].staticHolds.map(({from, durationInFrames, declaredHold}) => ({from, durationInFrames, declaredHold})),
    [{from: 106, durationInFrames: 330, declaredHold: true}]);
  assert.equal(report.status, 'geometry-and-timing-checks-passed');
  const partial = inspect(scene('missing-ending', 100, 480, {}, {processTrace: {
    events: [{kind: 'hold', from: 106, durationInFrames: 180}],
  }}));
  assert.ok(partial.scenes[0].staticHolds.some((hold) => !hold.declaredHold && hold.from === 286 && hold.durationInFrames === 294));
  assert.equal(partial.status, 'needs-review');
});

test('process final state comes from the trace even with no events; unsorted legacy events remain chronological', () => {
  const report = inspect(scene('no-events', 200, 150, {}, {processTrace: {
    initialQueue: ['a'], initialService: [], finalQueue: ['a'], finalService: [], completed: [], events: [],
  }}), scene('legacy', 400, 150, {}, {processTrace: {events: [
    {kind: 'finish', from: 500, durationInFrames: 30, queueAfter: [], serviceAfter: [], completedAfter: ['a']},
    {kind: 'start', from: 410, durationInFrames: 50, queueAfter: [], serviceAfter: [{actorId: 'a', stationId: 'one'}], completedAfter: []},
  ]}}));
  assert.deepEqual(report.scenes[0].finalProcessState, {queue: ['a'], service: [], completed: []});
  assert.deepEqual(report.scenes[1].finalProcessState, {queue: [], service: [], completed: ['a']});
});

test('collision worst frame is chosen using full precision, rounding only the report', () => {
  // Each later frame has a slightly smaller overlap. Rounding an intermediate maximum down
  // would wrongly move worstFrame forward, despite the first frame being the actual maximum.
  const report = inspect(scene('precision', 30, 10, {
    entities: [entity('a'), entity('b', {x: 31.000001})],
    actions: [action('b', 'move', 30, 10, {x: 31.000002})],
  }));
  assert.equal(report.scenes[0].collisions[0].worstFrame, 30);
});

test('stationary semantic packing and computing are visible operations with inspection coverage', () => {
  const report = inspect(scene('packing', 600, 180, {
    entities: [entity('parcel', {kind: 'box'})],
    cues: [{entityId: 'parcel', kind: 'pack', from: 600, durationInFrames: 180}],
  }), scene('computing', 900, 180, {
    entities: [entity('device', {kind: 'server'})],
    cues: [{entityId: 'device', kind: 'compute', from: 900, durationInFrames: 180}],
  }));
  for (const [index, kind] of ['pack', 'compute'].entries()) {
    const item = report.scenes[index];
    assert.equal(item.staticHolds.length, 0, kind);
    assert.ok(item.suggestedFrames.some((frame) => frame > item.from + 60 && frame < item.from + 120));
    assert.deepEqual(item.eventCoverage[0].cues, [{entityId: index ? 'device' : 'parcel', kind}]);
  }
  assert.equal(report.status, 'geometry-and-timing-checks-passed');
});

test('hidden, unsupported and out-of-scene cues cannot conceal a hold or create useful inspection samples', () => {
  const report = inspect(scene('quiet-cues', 300, 180, {
    entities: [entity('planet', {kind: 'planet'}), entity('hidden', {kind: 'box', opacity: 0})],
    cues: [{entityId: 'planet', kind: 'pack', from: 300, durationInFrames: 180},
      {entityId: 'hidden', kind: 'pack', from: 300, durationInFrames: 180},
      {entityId: 'planet', kind: 'compute', from: 700, durationInFrames: 180}],
  }));
  const item = report.scenes[0];
  assert.deepEqual(item.staticHolds.map(({from, durationInFrames}) => ({from, durationInFrames})),
    [{from: 300, durationInFrames: 180}]);
  assert.deepEqual(item.eventCoverage, []);
  assert.deepEqual(item.suggestedFrames, [330, 390, 479]);
});

test('a completed parcel stays sealed and static after packing; a continuing incomplete cue is not fake motion', () => {
  const report = inspect(scene('sealed', 0, 330, {
    entities: [entity('parcel', {kind: 'box'})],
    cues: [{entityId: 'parcel', kind: 'pack', from: 0, durationInFrames: 120}],
  }), scene('still-packing', 400, 180, {
    entities: [entity('parcel', {kind: 'box'})],
    cues: [{entityId: 'parcel', kind: 'pack', from: 400, durationInFrames: 180, continued: true, complete: false}],
  }));
  assert.ok(report.scenes[0].staticHolds.some((hold) => hold.from >= 110 && hold.from <= 120 && hold.durationInFrames >= 210));
  assert.deepEqual(report.scenes[1].staticHolds.map(({from, durationInFrames}) => ({from, durationInFrames})),
    [{from: 400, durationInFrames: 180}]);
});

test('cue coverage respects the frames where the actor is actually visible', () => {
  const report = inspect(scene('revealed-compute', 100, 240, {
    entities: [entity('packet', {kind: 'packet', opacity: 0})],
    actions: [action('packet', 'opacity', 220, 10, {value: 1})],
    cues: [{entityId: 'packet', kind: 'compute', from: 100, durationInFrames: 240}],
  }, {lines: [
    {id: 'hidden-line', text: 'No packet yet.', from: 100, durationInFrames: 100},
    {id: 'visible-line', text: 'The packet is being processed.', from: 230, durationInFrames: 100},
  ]}));
  const item = report.scenes[0];
  assert.deepEqual(item.eventCoverage.map((line) => line.cues), [[], [{entityId: 'packet', kind: 'compute'}]]);
  assert.ok(item.suggestedFrames.includes(280));
  assert.ok(item.staticHolds.some((hold) => hold.from === 100 && hold.durationInFrames >= 120));
});
