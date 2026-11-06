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
    const dependency = await moduleUrl(new URL(`${match[2]}.ts`, file));
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const {motionBoundaryIsContinuous} = await import(await moduleUrl(new URL('../src/motion/continuity.ts', import.meta.url)));
const entity = (id = 'subject', values = {}) => ({id, kind: 'person', x: 20, y: 50, size: 1,
  rotation: 0, opacity: 1, value: 1, color: 'accent', label: 'Subject', ...values});
const action = (values = {}) => ({entityId: 'subject', kind: 'move', from: 0, durationInFrames: 60,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: '', x: 80, y: 50, value: 0,
  easing: 'walk', ...values});
const scene = (id, from, entities = [entity()]) => ({id, template: 'motion', chapterId: 'chapter',
  from, durationInFrames: 90, lines: [], visual: {title: id, entities, paths: [], actions: []}});
const trace = (values = {}) => ({sourceTemplate: 'process', actorIds: ['subject'], stationEntityIds: ['counter'],
  initialQueue: ['subject'], initialService: [], finalQueue: ['subject'], finalService: [], completed: [], events: [], ...values});

test('an actual continuation at the mathematical seam can cut without mutating either scene', () => {
  const before = scene('before', 0, [entity('subject', {kind: 'packet'})]);
  before.visual.actions.push(action({easing: 'linear', durationInFrames: 90}));
  const after = scene('after', 90, [entity('subject', {kind: 'packet', x: 80})]);
  const source = JSON.stringify([before, after]);
  assert.equal(motionBoundaryIsContinuous(before, after), true);
  assert.equal(JSON.stringify([before, after]), source);
  // The mathematical endpoint is used rather than the penultimate visible position at frame 89.
  after.visual.entities[0].x = 20 + 60 * 89 / 90;
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('replays, changed appearance and changed visible cast fade even when an id is shared', () => {
  const before = scene('before', 0);
  for (const changes of [{x: 80}, {y: 51}, {size: 1.1}, {rotation: 10}, {opacity: 0.5},
    {color: 'secondary'}, {label: 'New label'}, {kind: 'packet'}, {value: 2}]) {
    assert.equal(motionBoundaryIsContinuous(before, scene('after', 90, [entity('subject', changes)])), false,
      JSON.stringify(changes));
  }
  assert.equal(motionBoundaryIsContinuous(before, scene('after', 90, [entity(), entity('new')])), false);
  assert.equal(motionBoundaryIsContinuous(before, scene('after', 90, [])), false);
});

test('invisible cast changes and equivalent rotations do not manufacture a visual discontinuity', () => {
  const before = scene('before', 0);
  const after = scene('after', 90, [entity('subject', {rotation: 360}), entity('hidden', {opacity: 0, x: 99})]);
  assert.equal(motionBoundaryIsContinuous(before, after), true);
});

test('gaps, overlaps, chapters and process-layout changes cannot be continuous', () => {
  const before = scene('before', 0);
  for (const from of [89, 91]) assert.equal(motionBoundaryIsContinuous(before, scene('after', from)), false);
  const chapter = scene('after', 90); chapter.chapterId = 'next';
  assert.equal(motionBoundaryIsContinuous(before, chapter), false);
  const process = scene('after', 90); process.processTrace = trace();
  assert.equal(motionBoundaryIsContinuous(before, process), false);
});

test('a repeated human performance remains continuous, but restarting work or a held pose fades', () => {
  const before = scene('before', 0);
  before.visual.activities = [{entityId: 'subject', kind: 'work', from: 0, durationInFrames: 180}];
  const after = structuredClone(before); after.id = 'after'; after.from = 90;
  assert.equal(motionBoundaryIsContinuous(before, after, 60), true);
  after.visual.activities[0].from = 90;
  assert.equal(motionBoundaryIsContinuous(before, after), false);
  after.visual.activities = [];
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('process count and station resets fade while the same settled state can cut', () => {
  const cast = [entity(), entity('counter', {kind: 'counter', x: 75, label: 'Counter'})];
  const before = scene('before', 0, cast); before.processTrace = trace({initialOpenStationIds: ['counter']});
  const after = structuredClone(before); after.id = 'after'; after.from = 90;
  assert.equal(motionBoundaryIsContinuous(before, after), true);
  after.processTrace.initialOpenStationIds = [];
  assert.equal(motionBoundaryIsContinuous(before, after), false);
  after.processTrace.initialOpenStationIds = ['counter'];
  after.processTrace.initialQueue = [];
  after.processTrace.initialService = [{actorId: 'subject', stationId: 'counter'}];
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('changed visible routes cannot cut just because their actors stayed in place', () => {
  const before = scene('before', 0, [entity('subject', {kind: 'packet'})]);
  before.visual.paths = [{id: 'route', points: [{x: 20, y: 50}, {x: 80, y: 50}],
    curved: false, closed: false, color: 'accent'}];
  const after = structuredClone(before); after.id = 'after'; after.from = 90;
  assert.equal(motionBoundaryIsContinuous(before, after), true);
  after.visual.paths[0].points[1].y = 60;
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('overlapping actors retain their SVG paint order at a continuous boundary', () => {
  const before = scene('before', 0, [entity('a'), entity('b', {color: 'secondary'})]);
  const after = structuredClone(before); after.id = 'after'; after.from = 90;
  after.visual.entities.reverse();
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('packed object state participates in continuity instead of reopening on a direct cut', () => {
  const before = scene('before', 0, [entity('subject', {kind: 'box'})]);
  before.visual.cues = [{entityId: 'subject', kind: 'pack', from: 10, durationInFrames: 60}];
  const after = structuredClone(before); after.id = 'after'; after.from = 90;
  assert.equal(motionBoundaryIsContinuous(before, after), true);
  after.visual.cues[0].from = 90;
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('an unfinished package continues closed in the next service shot before being sealed', () => {
  const before = scene('before', 0, [entity('subject', {kind: 'box'})]);
  before.visual.cues = [{entityId: 'subject', kind: 'pack', from: 0, durationInFrames: 90, complete: false}];
  const after = scene('after', 90, [entity('subject', {kind: 'box'})]);
  after.visual.cues = [{entityId: 'subject', kind: 'pack', from: 90, durationInFrames: 60, continued: true}];
  assert.equal(motionBoundaryIsContinuous(before, after), true);
});
