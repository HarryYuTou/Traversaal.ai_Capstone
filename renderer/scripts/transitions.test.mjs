import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/transitions.ts', import.meta.url), 'utf8');
const {outputText} = ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
}});
const {transitionBetween, transitionOpacity} =
  await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const opacity = (frame, duration, enter, exit) => transitionOpacity(frame, duration, enter, exit, 16, 14);

test('adjacent shots of one shared stage cut with no ghosted cast or brightness dip', () => {
  const before = {from: 30, durationInFrames: 90, stage: 0};
  const after = {from: 120, durationInFrames: 100, stage: 0};
  const transition = transitionBetween(before, after);
  assert.equal(transition, 'cut');
  for (let frame = 100; frame < 140; frame++) {
    const outgoing = opacity(frame - before.from, before.durationInFrames, 'fade', transition);
    const incoming = opacity(frame - after.from, after.durationInFrames, transition, 'fade');
    assert.equal(outgoing + incoming, 1, `frame ${frame} must retain exactly one complete stage`);
    assert.equal(Math.min(outgoing, incoming), 0, `frame ${frame} must not blend two casts`);
  }
});

test('unrelated scenes and chapter cards fade without overlapping titles', () => {
  const parts = [
    {from: 0, durationInFrames: 60},
    {from: 60, durationInFrames: 90, stage: 1},
    {from: 150, durationInFrames: 75, stage: 2},
    {from: 225, durationInFrames: 60},
  ];
  for (let index = 0; index < parts.length; index++) {
    assert.equal(transitionBetween(parts[index - 1], parts[index]), 'fade');
  }
  for (let frame = 0; frame < 285; frame++) {
    const alphas = parts.map((part) => opacity(frame - part.from, part.durationInFrames, 'fade', 'fade'));
    assert.ok(alphas.filter((alpha) => alpha > 0).length <= 1, `overlapping title at ${frame}`);
  }
});

test('a gap cannot accidentally keep a previous shared stage on screen', () => {
  const before = {from: 0, durationInFrames: 100, stage: 1};
  assert.equal(transitionBetween(before, {from: 105, durationInFrames: 100, stage: 1}), 'fade');
  assert.equal(opacity(100, 100, 'cut', 'cut'), 0);
  assert.equal(opacity(140, 100, 'fade', 'fade'), 0);
});

test('a shared camera does not override a discontinuous actor reset', () => {
  const before = {from: 0, durationInFrames: 100, stage: 1};
  assert.equal(transitionBetween(before, {from: 100, durationInFrames: 100, stage: 1,
    continuousFromPrevious: false}), 'fade');
  assert.equal(transitionBetween(before, {from: 100, durationInFrames: 100, stage: 1,
    continuousFromPrevious: true}), 'cut');
});

test('fades are bounded, settle monotonically and give even short cards a fully visible frame', () => {
  for (const duration of [1, 2, 3, 5, 16, 29, 30, 45, 90]) {
    const frames = Array.from({length: duration}, (_, frame) => opacity(frame, duration, 'fade', 'fade'));
    assert.ok(frames.every((alpha) => Number.isFinite(alpha) && alpha >= 0 && alpha <= 1));
    assert.ok(frames.includes(1), `no legible frame for a ${duration}-frame card`);
    const peak = frames.indexOf(1);
    assert.ok(frames.slice(0, peak).every((alpha, index) => alpha <= frames[index + 1]));
    assert.ok(frames.slice(peak).every((alpha, index) => index === 0 || alpha <= frames[peak + index - 1]));
  }
});

test('out-of-order seeks reproduce the same exact transition frame', () => {
  const frames = [0, 1, 7, 16, 28, 49, 70, 89, 90, 120, -1];
  const expected = frames.map((frame) => opacity(frame, 90, 'fade', 'fade'));
  frames.slice().reverse().forEach((frame) => opacity(frame, 90, 'fade', 'fade'));
  assert.deepEqual(frames.map((frame) => opacity(frame, 90, 'fade', 'fade')), expected);
});
