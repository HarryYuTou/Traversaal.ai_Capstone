import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ts from 'typescript';

const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  let {outputText} = ts.transpileModule(await readFile(file, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React,
  }});
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    const local = (extension) => new URL(`${match[2]}${extension}`, file);
    const dependency = match[2].startsWith('.')
      ? await moduleUrl(existsSync(local('.ts')) ? local('.ts') : local('.tsx')) : import.meta.resolve(match[2]);
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name, extension = '.ts') => import(await moduleUrl(new URL(`../src/motion/${name}${extension}`, import.meta.url)));
const {prepareRig, rigPoseAtFrame, rigPictureAtFrame, rigPathPoints} = await load('rig');
const {compileMotion, entityAtFrame, toStage} = await load('engine');
const {fitMotionViewport} = await load('camera');
const {entityHalfExtents} = await load('metrics');
const {placeActorLabels, planLabelSlots} = await load('labels');
const {motionBoundaryIsContinuous} = await load('continuity');
const {RigIllustration} = await load('RigIllustration', '.tsx');

const shape = (extra = {}) => ({kind: 'rect', x: -10, y: -8, width: 20, height: 16, radius: 2,
  path: '', fill: 'accent', stroke: 'ink', strokeWidth: 2, ...extra});
const part = (id, extra = {}) => ({id, parentId: '', x: 0, y: 0, rotation: 0,
  scaleX: 1, scaleY: 1, opacity: 1, shapes: [shape()], ...extra});
const track = (partId, property, values, easing = 'linear') => ({partId, property,
  keyframes: values.map((value, index) => ({at: index / (values.length - 1), value, easing}))});
const clip = (id, tracks) => ({id, tracks});
const definition = (parts = [part('body')], clips = []) => ({id: 'test-rig', parts, clips});
const performance = (clipId, from = 0, durationInFrames = 60, repeat = 1) => ({entityId: 'actor', clipId,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, from, durationInFrames, repeat});
const entity = (extra = {}) => ({id: 'actor', kind: 'custom', rigId: 'test-rig', x: 50, y: 50,
  size: 1, rotation: 0, opacity: 1, value: 0, color: 'accent', label: 'New actor', ...extra});
const visual = (rig, performances = [], extra = {}) => ({title: 'Generated actor', entities: [entity()],
  paths: [], actions: [], rigs: [rig], performances, ...extra});
const close = (a, b, epsilon = 1e-7) => {
  if (typeof a === 'number') assert.ok(Math.abs(a - b) < epsilon, `${a} != ${b}`);
  else if (Array.isArray(a)) {assert.equal(a.length, b.length); a.forEach((v, i) => close(v, b[i], epsilon));}
  else if (a && typeof a === 'object') {
    assert.deepEqual(Object.keys(a), Object.keys(b));
    Object.keys(a).forEach((key) => close(a[key], b[key], epsilon));
  } else assert.equal(a, b);
};

test('parts inherit parent translation, rotation and nonuniform scale around the authored joint', () => {
  const rig = prepareRig(definition([part('body', {x: 12, y: -8, rotation: 90, scaleX: 2, scaleY: 3, shapes: []}),
    part('arm', {parentId: 'body', x: 20, y: 5, rotation: -90})]), []);
  const picture = rigPictureAtFrame(rig, 0);
  assert.equal(picture.length, 1);
  close(picture[0].matrix, [3, 0, 0, 2, -3, 32]);
});

test('completed offsets hold and a subsequent relative clip starts without resetting the joint', () => {
  const rig = prepareRig(definition([part('body')], [clip('raise', [track('body', 'y', [0, -30])]),
    clip('lower', [track('body', 'y', [0, 10])])]), [performance('raise'), performance('lower', 90)]);
  assert.equal(rigPoseAtFrame(rig, -1).body.y, 0);
  assert.equal(rigPoseAtFrame(rig, 30).body.y, -15);
  assert.equal(rigPoseAtFrame(rig, 60).body.y, -30);
  assert.equal(rigPoseAtFrame(rig, 89).body.y, -30);
  assert.equal(rigPoseAtFrame(rig, 90).body.y, -30);
  assert.equal(rigPoseAtFrame(rig, 120).body.y, -25);
  assert.equal(rigPoseAtFrame(rig, 900).body.y, -20);
});

test('scale clips multiply the held scale and easing belongs to the arriving keyframe', () => {
  const first = track('body', 'scaleX', [1, 2], 'ease-out');
  first.keyframes[0].easing = 'linear';
  const rig = prepareRig(definition([part('body', {scaleX: 1.5})], [clip('stretch', [first]),
    clip('relax', [track('body', 'scaleX', [1, 0.5])])]), [performance('stretch'), performance('relax', 60)]);
  close(rigPoseAtFrame(rig, 30).body.scaleX, 1.5 * 1.875);
  close(rigPoseAtFrame(rig, 60).body.scaleX, 3);
  close(rigPoseAtFrame(rig, 120).body.scaleX, 1.5);
});

test('opacity clips reject accumulated out-of-range values while allowing reveal and subsequent fade', () => {
  const source = definition([part('body', {opacity: 0})], [
    clip('reveal', [track('body', 'opacity', [0, 1])]),
    clip('fade', [track('body', 'opacity', [0, -1])]),
  ]);
  const rig = prepareRig(source, [performance('reveal'), performance('fade', 90)]);
  close(rigPoseAtFrame(rig, 30).body.opacity, 0.5);
  close(rigPoseAtFrame(rig, 90).body.opacity, 1);
  close(rigPoseAtFrame(rig, 120).body.opacity, 0.5);
  close(rigPoseAtFrame(rig, 150).body.opacity, 0);
  assert.throws(() => prepareRig(source, [performance('reveal'), performance('reveal', 90)]), /accumulated opacity/);
  assert.throws(() => prepareRig(source, [performance('fade')]), /accumulated opacity/);
  const opaque = structuredClone(source);
  opaque.parts[0].opacity = 1;
  assert.throws(() => prepareRig(opaque, [performance('reveal')]), /accumulated opacity/);
});

test('looping clips close at every repeat seam and preserve their initial held pose on completion', () => {
  const rig = prepareRig(definition([part('body')], [clip('wave', [track('body', 'rotation', [0, 50, 0])])]),
    [performance('wave', 30, 180, 3)]);
  for (const frame of [30, 90, 150, 210, 900]) assert.equal(rigPoseAtFrame(rig, frame).body.rotation, 0);
  for (const frame of [60, 120, 180]) close(rigPoseAtFrame(rig, frame).body.rotation, 50);
  close(rigPoseAtFrame(rig, 90 - 1e-7).body.rotation, rigPoseAtFrame(rig, 90 + 1e-7).body.rotation, 1e-5);
});

test('repeated cycles require four frames so frame sampling cannot erase their entire movement', () => {
  const source = definition([part('body')], [clip('wave', [track('body', 'rotation', [0, 50, 0])])]);
  for (const duration of [3, 6, 11]) {
    assert.throws(() => prepareRig(source, [performance('wave', 0, duration, 3)]), /four frames per repeated cycle/);
  }
  const rig = prepareRig(source, [performance('wave', 0, 12, 3)]);
  assert.equal(rigPoseAtFrame(rig, 0).body.rotation, 0);
  assert.equal(rigPoseAtFrame(rig, 2).body.rotation, 50);
  assert.equal(rigPoseAtFrame(rig, 4).body.rotation, 0);
});

test('independent channels may perform together, but conflicting channels and nonclosing repeats are rejected', () => {
  const rig = definition([part('body')], [clip('raise', [track('body', 'y', [0, -10])]),
    clip('turn', [track('body', 'rotation', [0, 90])]), clip('lower', [track('body', 'y', [0, 10])])]);
  const prepared = prepareRig(rig, [performance('raise'), performance('turn')]);
  close(rigPoseAtFrame(prepared, 30).body.y, -5);
  close(rigPoseAtFrame(prepared, 30).body.rotation, 45);
  assert.throws(() => prepareRig(rig, [performance('raise'), performance('lower', 30)]), /same channel/);
  assert.throws(() => prepareRig(rig, [performance('turn', 0, 60, 2)]), /return every channel/);
});

test('random seeks and 24/30/60 fps timestamps return identical articulated poses without mutating source', () => {
  const source = definition([part('body'), part('head', {parentId: 'body', y: -30})],
    [clip('greet', [track('head', 'rotation', [0, -15, 10, 0], 'ease-in-out'), track('body', 'y', [0, -5, 0])])]);
  const text = JSON.stringify(source);
  const make = (fps) => prepareRig(source, [performance('greet', fps, fps * 3, 2)]);
  const prepared = make(30);
  const frames = [29, 0, 90, 120, 35, 60, 89, 91, 45, 30, 900];
  const snapshots = frames.map((frame) => rigPictureAtFrame(prepared, frame));
  for (const frame of [...frames].reverse()) close(rigPictureAtFrame(prepared, frame), snapshots[frames.indexOf(frame)]);
  for (const seconds of [0, 1, 1.25, 2.5, 3.75, 4, 20]) {
    const reference = rigPoseAtFrame(make(30), seconds * 30);
    for (const fps of [24, 60]) close(rigPoseAtFrame(make(fps), seconds * fps), reference);
  }
  assert.equal(JSON.stringify(source), text);
});

test('complete bounds contain every articulated part under rotations, nested scales and sequential held translations', () => {
  const path = shape({kind: 'path', x: 0, y: 0, width: 0, height: 0, radius: 0,
    path: 'M -12 -8 C -40 -36 30 -24 20 16 Q 8 40 -12 -8 Z'});
  const source = definition([part('body', {shapes: []}), part('arm', {parentId: 'body', x: 20, rotation: -20}),
    part('hand', {parentId: 'arm', x: 35, shapes: [path]})], [
    clip('reach', [track('arm', 'rotation', [0, 70, -35]), track('body', 'scaleY', [1, 1.2]),
      track('hand', 'scaleX', [1, 1.5]), track('body', 'x', [0, 15])]),
    clip('finish', [track('body', 'x', [0, 20]), track('hand', 'rotation', [0, 120])]),
  ]);
  const rig = prepareRig(source, [performance('reach'), performance('finish', 60)]);
  for (let frame = 0; frame <= 150; frame++) for (const {matrix, shape: drawing} of rigPictureAtFrame(rig, frame)) {
    const points = drawing.kind === 'path' ? rigPathPoints(drawing.path)
      : [{x: drawing.x, y: drawing.y}, {x: drawing.x + drawing.width, y: drawing.y + drawing.height}];
    for (const {x, y} of points) {
      const px = matrix[0] * x + matrix[2] * y + matrix[4];
      const py = matrix[1] * x + matrix[3] * y + matrix[5];
      assert.ok(Math.abs(px) <= rig.extents[0] + 1e-6, `x at ${frame}`);
      assert.ok(Math.abs(py) <= rig.extents[1] + 1e-6, `y at ${frame}`);
    }
  }
});

test('custom geometry determines fixed camera and label envelopes, including future poses', () => {
  const source = definition([part('body')], [clip('stretch', [track('body', 'x', [0, 150])])]);
  const program = compileMotion(visual(source, [performance('stretch')], {entities: [entity({x: 96, size: 2})]}));
  const prepared = program.entities[0];
  assert.ok(prepared.rigExtents[0] >= 161);
  const viewport = fitMotionViewport(program);
  const end = toStage(entityAtFrame(prepared, 60));
  assert.ok(viewport.x + viewport.width >= end.x + prepared.rigExtents[0] * 2);
  const slots = planLabelSlots([{program, frames: [0, 30, 60]}], undefined, {viewport});
  const first = placeActorLabels([{prepared, state: entityAtFrame(prepared, 0)}], viewport, slots)[0];
  const last = placeActorLabels([{prepared, state: entityAtFrame(prepared, 60)}], viewport, slots)[0];
  assert.equal(first.x, last.x);
  assert.equal(first.y, last.y);
  assert.ok(entityHalfExtents('custom', 2, 90, 'sketch', prepared.rigExtents).y >= 322);
});

test('visible picture excludes unused definitions, hidden descendants and unpainted geometry', () => {
  const source = definition([part('body'), part('hidden', {opacity: 0}),
    part('child', {parentId: 'hidden'}), part('empty', {shapes: []}),
    part('unpainted', {shapes: [shape({fill: 'none', stroke: 'none'})]})],
  [clip('hidden-motion', [track('hidden', 'x', [0, 40]), track('empty', 'rotation', [0, 90])])]);
  const rig = prepareRig(source, [performance('hidden-motion')]);
  assert.equal(rigPictureAtFrame(rig, 0).length, 1);
  assert.deepEqual(rigPictureAtFrame(rig, 0), rigPictureAtFrame(rig, 60));
});

test('scene continuity compares current rendered rig geometry and pose, not the clip definitions', () => {
  const source = definition([part('body')], [clip('raise', [track('body', 'y', [0, -20])])]);
  const scene = (from, drawing) => ({id: `scene-${from}`, template: 'motion', chapterId: 'chapter',
    from, durationInFrames: 60, lines: [], visual: drawing});
  const before = scene(0, visual(source, [performance('raise')]));
  const after = scene(60, visual(definition([part('body', {y: -20})], [])));
  assert.equal(motionBoundaryIsContinuous(before, after), true);
  after.visual.rigs[0].clips.push(clip('future', [track('body', 'rotation', [0, 90])]));
  assert.equal(motionBoundaryIsContinuous(before, after), true);
  after.visual.rigs[0].parts[0].shapes[0].fill = 'secondary';
  assert.equal(motionBoundaryIsContinuous(before, after), false);
  after.visual.rigs[0].parts[0].shapes[0].fill = 'accent';
  after.visual.rigs[0].parts[0].y = 0;
  assert.equal(motionBoundaryIsContinuous(before, after), false);
});

test('invalid hierarchy, references, keyframes, paths, colors and excessive transformed geometry are rejected', () => {
  const malformed = [
    definition([part('a', {parentId: 'b'}), part('b', {parentId: 'a'})]),
    definition([part('body', {parentId: 'missing'})]),
    definition([part('body'), part('body')]),
    definition([part('body', {shapes: [shape({fill: 'url(https://bad.example/a)'})]})]),
    definition([part('body', {shapes: [shape({kind: 'path', path: '<script>alert(1)</script>'})]})]),
    definition([part('body', {scaleX: 4, shapes: [shape({x: 256, width: 512})]})]),
    definition([part('body')], [clip('bad', [track('missing', 'x', [0, 10])])]),
    definition([part('body')], [clip('bad', [track('body', 'x', [5, 10])])]),
    definition([part('body')], [clip('bad', [track('body', 'x', [0, 10]), track('body', 'x', [0, 10])])]),
  ];
  for (const source of malformed) assert.throws(() => prepareRig(source, []), /Invalid custom rig/);
  for (const path of ['m 0 0 l 1 1', 'M 0 0 A 1 1 0 0 1 2 2', 'M 0 0 L 400 0', 'M 0 0 1 1', 'M 0 0 Q 4 4']) {
    assert.throws(() => rigPathPoints(path), /Invalid custom rig/);
  }
  const duplicateAt = definition([part('body')], [clip('bad', [track('body', 'x', [0, 10, 0])])]);
  duplicateAt.clips[0].tracks[0].keyframes[1].at = 0;
  assert.throws(() => prepareRig(duplicateAt, []), /keyframe/);
  assert.throws(() => compileMotion({...visual(definition()), rigs: []}), /missing rig/);
});

test('SVG renderer uses generated shape geometry and actual joint matrices without markup execution', () => {
  const source = definition([part('body'), part('head', {parentId: 'body', y: -25,
    shapes: [shape({kind: 'ellipse', x: 0, y: 0, radius: 0, fill: '#dd8844'})]})],
  [clip('nod', [track('head', 'rotation', [0, 30])])]);
  const rig = prepareRig(source, [performance('nod')]);
  const palette = {ink: '#182c3c', accent: '#dd8452', secondary: '#77a194', muted: '#737b81',
    paper: '#fffaf0', soft: '#ece6db', line: '#ced0cd'};
  const render = (frame) => renderToStaticMarkup(React.createElement('svg', null,
    React.createElement(RigIllustration, {rig, frame, palette})));
  assert.match(render(0), /data-custom-rig="test-rig"/);
  assert.match(render(0), /<ellipse cx="0" cy="0" rx="10" ry="8"/);
  assert.match(render(0), /fill="#dd8844"/);
  assert.notEqual(render(0), render(30));
  assert.equal(render(30), render(30));
  assert.doesNotMatch(render(30), /<script|onload|foreignObject|href|<animate|@keyframes/);
});
