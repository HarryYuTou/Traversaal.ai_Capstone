import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

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
    // Native ESM sees this CommonJS package's exports object; match the renderer bundler's default interop.
    if (match[2] === 'react-peeps') dependency = `data:text/javascript;base64,${Buffer.from(
      `import pkg from '${dependency}'; export default pkg.default ?? pkg;`).toString('base64')}`;
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {SketchPerson, sketchLegPose, sketchView} = await import(await moduleUrl(new URL('../src/motion/sketch.tsx', import.meta.url)));
const {compileMotion, entityAtFrame, toStage} = await load('engine');
const {illustrationPoseAtFrame} = await load('pose');

const walkingProgram = (direction, size) => compileMotion({title: 'Walk', paths: [],
  entities: [{id: 'person', kind: 'person', x: direction > 0 ? 20 : 60, y: 50,
    size, rotation: 0, opacity: 1, value: 0, color: 'accent', label: ''}],
  actions: [{entityId: 'person', kind: 'move', from: 20, durationInFrames: 180,
    x: direction > 0 ? 60 : 20, y: 50, easing: 'linear', value: 0, pathId: '',
    startLine: 0, endLine: 0, startOffset: 0, endOffset: 1}],
});

test('planted sketch feet remain at one world position during full-strength horizontal travel', () => {
  for (const direction of [-1, 1]) {
    for (const size of [0.7, 1, 2]) {
      const prepared = walkingProgram(direction, size).entities[0];
      const contacts = new Map();
      for (let frame = 25; frame < 195; frame += 0.25) {
        const state = entityAtFrame(prepared, frame);
        const pose = illustrationPoseAtFrame(prepared, frame);
        // Deliberately look backwards: anticipation must not redirect the current footfall.
        pose.performance = {...pose.performance, lookX: -direction};
        const gait = sketchLegPose(pose);
        assert.equal(gait.direction, direction);
        const elapsedCycles = (frame - 20) / 180 * 480 / (44 * size);
        gait.legs.forEach((leg, index) => {
          const cycle = elapsedCycles + index * 0.5;
          const progress = cycle - Math.floor(cycle);
          if (progress >= 0.5) return;
          assert.equal(leg.ankle.y + 5, 0, 'the stance shoe sole touches local floor zero');
          assert.equal(leg.toe, 0, 'a planted shoe never rocks through the floor');
          const position = toStage(state).x + leg.ankle.x * size;
          const key = `${index}-${Math.floor(cycle)}`;
          const prior = contacts.get(key);
          if (prior !== undefined) assert.ok(Math.abs(position - prior) < 1e-6,
            `direction ${direction}, scale ${size}, frame ${frame}: planted foot slipped`);
          else contacts.set(key, position);
        });
      }
      assert.ok(contacts.size > 5, 'exercise several steps, not one frozen pose');
    }
  }
});

test('gaze changes cannot alter leg geometry on a turn or during a partial-strength start', () => {
  for (const strength of [0.1, 0.5, 1]) {
    for (const tangent of [-1, -0.4, 0, 0.6, 1]) {
      const base = {movement: {walking: true, phase: 0.2, strength, facing: tangent * strength}, activity: null};
      const left = sketchLegPose({...base, performance: {lookX: -1}});
      const right = sketchLegPose({...base, performance: {lookX: 1}});
      assert.deepEqual(left.legs, right.legs);
      if (strength === 1) assert.ok(Math.abs(left.direction - tangent) < 1e-12);
    }
  }
});

test('idle shoes retain attention while both feet stand flat and any seek reproduces the same legs', () => {
  const prepared = walkingProgram(1, 1).entities[0];
  const resting = illustrationPoseAtFrame(prepared, 230);
  const idle = sketchLegPose(resting);
  assert.equal(idle.direction, resting.performance.lookX);
  for (const leg of idle.legs) {
    assert.equal(leg.ankle.y + 5, 0);
    assert.equal(leg.knee.x, leg.hip.x);
    assert.equal(leg.ankle.x, leg.hip.x);
  }
  const expected = sketchLegPose(illustrationPoseAtFrame(prepared, 85));
  [230, 10, 115, 50, 199].forEach((frame) => sketchLegPose(illustrationPoseAtFrame(prepared, frame)));
  assert.deepEqual(sketchLegPose(illustrationPoseAtFrame(prepared, 85)), expected);
});

test('leftward travel mirrors the actual garment and head while preserving the grounded leg rig', () => {
  for (const direction of [-1, 1]) {
    const prepared = walkingProgram(direction, 1).entities[0];
    const pose = illustrationPoseAtFrame(prepared, 85);
    const facing = direction < 0 ? 'left' : 'right';
    assert.equal(sketchView(pose).facing, facing);
    const render = () => renderToStaticMarkup(React.createElement('svg', null,
      React.createElement(SketchPerson, {id: 'same-actor', fill: '#dc7451', ink: '#1d2433', paper: '#ffffff', pose})));
    const svg = render();
    assert.equal((svg.match(new RegExp(`data-character-facing="${facing}"`, 'g')) ?? []).length, 2,
      'both actual artwork layers must face the direction of travel');
    assert.equal((svg.match(new RegExp(`scale\\(${direction} 1\\)`, 'g')) ?? []).length, 2);
    assert.ok(svg.includes('data-character-part="feet"'));
    assert.equal(svg, render(), 'view changes preserve deterministic cast artwork');
  }
});

test('an anticipated reversal switches drawn view once and never collapses or crossfades the body', () => {
  const right = walkingProgram(1, 1);
  const visual = {title: 'Return', paths: [], entities: [right.entities[0].entity], actions: [
    right.entities[0].actions[0].action,
    {...right.entities[0].actions[0].action, from: 240, durationInFrames: 60, x: 20},
  ]};
  const prepared = compileMotion(visual).entities[0];
  const views = [];
  for (let frame = 232; frame <= 250; frame += 0.25) {
    const pose = illustrationPoseAtFrame(prepared, frame);
    const view = sketchView(pose);
    assert.ok(Math.abs(view.scaleX) >= 0.86 && Math.abs(view.scaleX) <= 1);
    views.push(view.facing);
  }
  assert.equal(views.filter((view, index) => index > 0 && view !== views[index - 1]).length, 1);
  assert.equal(views[0], 'right');
  assert.equal(views.at(-1), 'left');
  assert.equal(sketchView(illustrationPoseAtFrame(prepared, 325)).facing, 'left', 'view persists after arrival');
});
