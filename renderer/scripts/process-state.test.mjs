import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/motion/processState.ts', import.meta.url), 'utf8');
const {outputText} = ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
}});
const {processStateAtFrame, processStageLayout, stationStateAtFrame} = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

const phase = (kind, actorIds, from, durationInFrames) => ({kind, actorIds, from, durationInFrames});
// Deliberately include future actors in the cast: total cast size is not current unfinished work.
const trace = {
  sourceTemplate: 'process', actorIds: ['a', 'b', 'c', 'd'], stationEntityIds: ['one', 'two'],
  initialQueue: ['a'], initialService: [{actorId: 'b', stationId: 'one'}],
  events: [
    {kind: 'arrive', from: 110, durationInFrames: 60,
      phases: [phase('arrive', ['c'], 110, 30), phase('arrive', ['d'], 140, 30)]},
    {kind: 'start', from: 200, durationInFrames: 80,
      phases: [phase('to-service', ['a'], 200, 30), phase('compact-queue', ['c', 'd'], 230, 50)]},
    {kind: 'hold', from: 280, durationInFrames: 120, phases: []},
    {kind: 'finish', from: 400, durationInFrames: 80, movementEndFrame: 468,
      phases: [phase('complete', ['b'], 400, 12), phase('exit', ['b'], 412, 56), phase('fade', ['b'], 468, 12)]},
  ],
};
const counts = (frame, data = trace) => {
  const {waiting, inService, unfinished} = processStateAtFrame(data, frame);
  return [waiting, inService, unfinished];
};

test('initial physical snapshot excludes every future arrival', () => {
  assert.deepEqual(counts(0), [1, 1, 2]);
  assert.deepEqual(counts(109), [1, 1, 2]);
  assert.equal(processStateAtFrame(trace, 0).opacity, 1);
});

test('staggered arrivals enter the queue at each actual arrival endpoint, not event start or final end', () => {
  assert.deepEqual(counts(139), [1, 1, 2]);
  assert.deepEqual(counts(140), [2, 1, 3]);
  assert.deepEqual(counts(169), [2, 1, 3]);
  assert.deepEqual(counts(170), [3, 1, 4]);
});

test('service counts change at the transfer endpoint before queue compaction ends', () => {
  assert.deepEqual(counts(200), [3, 1, 4]);
  assert.deepEqual(counts(229), [3, 1, 4]);
  assert.deepEqual(counts(230), [2, 2, 4]);
  assert.deepEqual(counts(279), [2, 2, 4]);
});

test('completion cue does not remove a person; departure does, before its final fade', () => {
  assert.deepEqual(counts(400), [2, 2, 4]);
  assert.deepEqual(counts(412), [2, 2, 4]);
  assert.deepEqual(counts(467), [2, 2, 4]);
  assert.deepEqual(counts(468), [2, 1, 3]);
  assert.deepEqual(counts(480), [2, 1, 3]);
});

test('strip fades before motion, hides through complete/exit/fade and queue compaction, and returns on holds', () => {
  assert.equal(processStateAtFrame(trace, 102).opacity, 1);
  assert.equal(processStateAtFrame(trace, 106).opacity, 0.5);
  for (const frame of [110, 139, 140, 169, 170, 200, 230, 279, 280, 400, 412, 468, 479, 480]) {
    assert.equal(processStateAtFrame(trace, frame).opacity, 0, `contradictory snapshot at ${frame}`);
  }
  assert.equal(processStateAtFrame(trace, 174).opacity, 0.5);
  assert.equal(processStateAtFrame(trace, 178).opacity, 1);
  assert.equal(processStateAtFrame(trace, 300).opacity, 1);
  assert.equal(processStateAtFrame(trace, 484).opacity, 0.5);
  assert.equal(processStateAtFrame(trace, 488).opacity, 1);
});

test('parallel starts and departures update all paired actors at the same milestone', () => {
  const parallel = {...trace, initialQueue: ['a', 'b'], initialService: [], events: [
    {kind: 'start', from: 100, durationInFrames: 60, phases: [phase('to-service', ['a', 'b'], 100, 30)]},
    {kind: 'finish', from: 200, durationInFrames: 60,
      phases: [phase('complete', ['a', 'b'], 200, 12), phase('exit', ['a', 'b'], 212, 40), phase('fade', ['a', 'b'], 252, 8)]},
  ]};
  assert.deepEqual(counts(129, parallel), [2, 0, 2]);
  assert.deepEqual(counts(130, parallel), [0, 2, 2]);
  assert.deepEqual(counts(251, parallel), [0, 2, 2]);
  assert.deepEqual(counts(252, parallel), [0, 0, 0]);
});

test('random seeking and absolute offsets do not retain state or modify trace data', () => {
  const original = JSON.stringify(trace);
  const frames = [480, 130, 0, 288, 170, 468, 230, 139, 400, 300, 140, 230];
  const expected = new Map(frames.map((frame) => [frame, processStateAtFrame(trace, frame)]));
  const shifted = {...trace, events: trace.events.map((event) => ({...event, from: event.from + 1000,
    phases: event.phases.map((part) => ({...part, from: part.from + 1000}))}))};
  for (const frame of frames.reverse()) {
    assert.deepEqual(processStateAtFrame(trace, frame), expected.get(frame));
    assert.deepEqual(processStateAtFrame(shifted, frame + 1000), expected.get(frame));
  }
  assert.equal(JSON.stringify(trace), original);
});

test('process layout reserves readable scaled type and preserves the caption-safe bottom edge', () => {
  for (const height of [1080, 720]) {
    const scale = height / 1080;
    const base = {x: 90 * scale, y: 205 * scale, width: 1740 * scale, height: 655 * scale};
    const layout = processStageLayout(base, height);
    assert.equal(layout.strip.fontSize, height === 1080 ? 30 : 20);
    assert.equal(layout.container.y + layout.container.height, 860 * scale);
    assert.ok(layout.strip.height >= layout.strip.fontSize * 1.2);
    // Flex layout gives wrapped titles their actual height before assigning the remaining stage.
    for (const titleLines of [1, 2, 3]) {
      const stageTop = layout.container.y + titleLines * layout.titleFontSize * 1.14 +
        layout.strip.marginTop + layout.strip.height + layout.strip.marginBottom;
      assert.ok(stageTop >= base.y);
      assert.ok(stageTop < layout.container.y + layout.container.height);
    }
  }
});


test('station opens only at the exact authored phase endpoint and old timelines retain their look', () => {
  const data = {...trace, initialOpenStationIds: ['one'], events: [
    {kind: 'open', stationIds: ['two'], from: 100, durationInFrames: 60,
      phases: [{kind: 'open', actorIds: [], stationIds: ['two'], from: 110, durationInFrames: 40}]},
  ]};
  assert.equal(stationStateAtFrame(trace, 'one', 200), null);
  assert.equal(stationStateAtFrame(data, 'missing', 200), null);
  assert.deepEqual(stationStateAtFrame(data, 'one', 0), {open: true, openingProgress: 0});
  assert.deepEqual(stationStateAtFrame(data, 'two', 109), {open: false, openingProgress: 0});
  assert.deepEqual(stationStateAtFrame(data, 'two', 130), {open: false, openingProgress: 0.5});
  assert.equal(stationStateAtFrame(data, 'two', 149).open, false);
  assert.deepEqual(stationStateAtFrame(data, 'two', 150), {open: true, openingProgress: 1});
  [400, 10, 140, 0].forEach((frame) => stationStateAtFrame(data, 'two', frame));
  assert.deepEqual(stationStateAtFrame(data, 'two', 130), {open: false, openingProgress: 0.5});
});
