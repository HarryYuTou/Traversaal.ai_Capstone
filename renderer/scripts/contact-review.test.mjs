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
    outputText = outputText.replace(match[0], `from '${await moduleUrl(new URL(`${match[2]}.ts`, file))}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const {compileMotion, entityAtFrame, contactAnchorAtFrame, contactPositionBounds, displayedPaths, toStage} =
  await import(await moduleUrl(new URL('../src/motion/engine.ts', import.meta.url)));
const close = (actual, expected, message = '') => assert.ok(Math.abs(actual.x - expected.x) < 1e-6
  && Math.abs(actual.y - expected.y) < 1e-6, `${message}: ${JSON.stringify(actual)} != ${JSON.stringify(expected)}`);
const entity = (id, extra = {}) => ({id, kind: 'box', x: 20, y: 50, size: 1, rotation: 0,
  opacity: 1, value: 0, color: 'accent', label: '', ...extra});
const action = (entityId, kind, from, durationInFrames, extra = {}) => ({entityId, kind, from, durationInFrames,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0, value: 0,
  easing: 'linear', ...extra});
const contact = (entityId, targetId, extra = {}) => ({entityId, targetId, partId: '', targetPartId: '',
  x: 0, y: 0, targetX: 0, targetY: 0, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
  approach: 0.2, from: 10, durationInFrames: 60, approachFrames: 12, ...extra});
const shape = {kind: 'rect', x: -5, y: -4, width: 10, height: 8, radius: 0, path: '',
  fill: 'accent', stroke: 'ink', strokeWidth: 1};
const rig = (id, parts = []) => ({id, clips: [], parts: [{id: 'root', parentId: '', x: 8, y: 3, rotation: 25,
  scaleX: 1.2, scaleY: 0.8, opacity: 1, shapes: [], ...parts[0]},
{id: 'tip', parentId: 'root', x: 30, y: -12, rotation: -35, scaleX: 0.7, scaleY: 1.4,
  opacity: 1, shapes: [shape], ...parts[1]}]});
const compile = (entities, contacts, actions = [], rigs = []) => compileMotion({title: 'Contact review',
  entities, contacts, actions, rigs, paths: []});

test('contact anchor math includes source and target nested transforms plus outer scale and rotation', () => {
  const lock = contact('source', 'target', {partId: 'tip', targetPartId: 'tip', x: 7, y: -3, targetX: -2, targetY: 8});
  const program = compile([entity('source', {kind: 'custom', rigId: 'source-rig', rotation: 30, size: 1.4}),
    entity('target', {kind: 'custom', rigId: 'target-rig', x: 70, y: 62, rotation: -18, size: 0.9})], [lock],
  [action('source', 'rotate', 0, 100, {value: 95}), action('source', 'scale', 0, 100, {value: 1.8}),
    action('target', 'move', 0, 100, {x: 84, y: 30}), action('target', 'rotate', 0, 100, {value: 40})],
  [rig('source-rig'), rig('target-rig', [{rotation: -12}, {x: -16, scaleY: 0.5}])]);
  const [source, target] = program.entities;
  for (const frame of [22, 22.5, 40, 65.7, 70]) close(
    contactAnchorAtFrame(source, 'tip', {x: 7, y: -3}, frame),
    contactAnchorAtFrame(target, 'tip', {x: -2, y: 8}, frame), `nested lock at ${frame}`);
  const sourceAtRelease = entityAtFrame(source, 70);
  close(entityAtFrame(source, 70 + 1e-8), sourceAtRelease, 'root has no release snap');
  close(entityAtFrame(source, 90), sourceAtRelease, 'translation stays released while own rotation and scale continue');
});

test('reacquisition starts from the last held release offset and reaches the next target without a position jump', () => {
  const program = compile([entity('source'), entity('first', {x: 55}), entity('second', {x: 75, y: 25})],
    [contact('source', 'first', {durationInFrames: 30, approachFrames: 6}),
      contact('source', 'second', {from: 60, durationInFrames: 30, approachFrames: 6})]);
  const [source, first, second] = program.entities;
  close(entityAtFrame(source, 10), entity('source'), 'acquisition begins at raw position');
  close(contactAnchorAtFrame(source, '', {x: 0, y: 0}, 40), toStage(entityAtFrame(first, 40)));
  close(entityAtFrame(source, 60), entityAtFrame(source, 59), 'next acquisition starts at previous held position');
  close(entityAtFrame(source, 60 + 1e-7), entityAtFrame(source, 60));
  close(contactAnchorAtFrame(source, '', {x: 0, y: 0}, 66), toStage(entityAtFrame(second, 66)));
  close(entityAtFrame(source, 90 + 1e-7), entityAtFrame(source, 90));
});

test('acyclic moving contact chains resolve deterministically at arbitrary seek order', () => {
  const entities = [entity('parcel', {x: 5}), entity('hand', {x: 40}), entity('carrier', {x: 70})];
  const locks = [contact('parcel', 'hand', {from: 0, durationInFrames: 80, approach: 0, approachFrames: 0}),
    contact('hand', 'carrier', {from: 0, durationInFrames: 80, approach: 0, approachFrames: 0, targetX: 20, targetY: 10})];
  const actions = [action('carrier', 'move', 0, 100, {x: 90, y: 15})];
  const program = compile(entities, locks, actions);
  const before = JSON.stringify(program);
  const [parcel, hand, carrier] = program.entities;
  for (const frame of [60, 20, 80, 0, 45.5, 10, 40]) {
    close(contactAnchorAtFrame(parcel, '', {x: 0, y: 0}, frame), contactAnchorAtFrame(hand, '', {x: 0, y: 0}, frame));
    close(contactAnchorAtFrame(hand, '', {x: 0, y: 0}, frame), contactAnchorAtFrame(carrier, '', {x: 20, y: 10}, frame));
    assert.deepEqual(entityAtFrame(parcel, frame), entityAtFrame(parcel, frame));
  }
  assert.equal(JSON.stringify(program), before);
});

test('contact dependencies reject cycles even when the cyclic intervals are separated in time', () => {
  assert.throws(() => compile([entity('a'), entity('b')], [contact('a', 'b', {from: 0, durationInFrames: 30}),
    contact('b', 'a', {from: 60, durationInFrames: 30})]), /cyclic contact dependency/);
});

test('contact bounds include pre-acquisition position, target-driven extrema and post-release travel', () => {
  const program = compile([entity('source', {x: 8, y: 12}), entity('target', {x: 55, y: 65})],
    [contact('source', 'target')], [action('target', 'move', 0, 90, {x: 78, y: 20}),
      action('source', 'move', 70, 40, {x: 30, y: -15})]);
  const source = program.entities[0];
  const bounds = contactPositionBounds(source);
  for (let frame = 0; frame <= 180; frame++) {
    const point = toStage(entityAtFrame(source, frame));
    assert.ok(point.x >= bounds.left - 1e-6 && point.x <= bounds.right + 1e-6
      && point.y >= bounds.top - 1e-6 && point.y <= bounds.bottom + 1e-6,
    `frame ${frame} not included: ${JSON.stringify(point)}`);
  }
});

test('released route geometry remains aligned and inside bounds even when one-frame travel skips its detour', () => {
  const source = entity('source');
  const program = compileMotion({title: 'Short route', entities: [source, entity('target', {x: 75, y: 80})],
    rigs: [], contacts: [contact('source', 'target', {from: 0, approach: 0, approachFrames: 0})],
    paths: [{id: 'detour', points: [{x: 20, y: 50}, {x: 30, y: -40}, {x: 40, y: 50}], curved: true,
      closed: false, color: 'muted'}],
    actions: [action('source', 'follow-path', 60, 1, {pathId: 'detour'})]});
  const prepared = program.entities[0];
  const bounds = contactPositionBounds(prepared);
  const route = displayedPaths(program, 61)[0].geometry;
  close(route.points[0], toStage(entityAtFrame(prepared, 60)));
  close(route.points.at(-1), toStage(entityAtFrame(prepared, 61)));
  for (const point of route.points) assert.ok(point.x >= bounds.left - 1e-6 && point.x <= bounds.right + 1e-6
    && point.y >= bounds.top - 1e-6 && point.y <= bounds.bottom + 1e-6);
});

test('contact bounds reject unsafe frame integers and excessive target-driven sample spans before scanning', () => {
  const entities = [entity('source'), entity('target', {x: 60})];
  const lock = contact('source', 'target', {from: 0, durationInFrames: 30, approach: 0, approachFrames: 0});
  assert.throws(() => {
    const unsafeContact = compile(entities, [{...lock, from: 1e20}]);
    contactPositionBounds(unsafeContact.entities[0]);
  }, /Invalid contact/);
  const unsafeTarget = compile(entities, [lock], [action('target', 'move', 1e20, 30, {x: 70})]);
  assert.throws(() => contactPositionBounds(unsafeTarget.entities[0]), /Invalid contact framing interval/);
  const excessiveTarget = compile(entities, [lock], [action('target', 'move', 0, 100_001, {x: 70})]);
  assert.throws(() => contactPositionBounds(excessiveTarget.entities[0]), /100000 frames/);
});
