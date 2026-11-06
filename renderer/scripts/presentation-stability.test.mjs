import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

// Load the production planner, including its geometry dependencies, without generating build files.
const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  const source = await readFile(file, 'utf8');
  let {outputText} = ts.transpileModule(source, {compilerOptions: {
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
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {processPresentations} = await load('processPresentation');
const {fitMotionViewport} = await load('camera');
const {compileMotion, entityAtFrame, toStage} = await load('engine');
const {entityHalfExtents} = await load('metrics');
const {placeActorLabels} = await load('labels');

const entity = (id, kind, values = {}) => ({id, kind, x: 50, y: 50, size: 1, rotation: 0,
  opacity: 1, value: 1, color: 'accent', label: '', ...values});
const action = (entityId, kind, from, values = {}) => ({entityId, kind, from, durationInFrames: 60,
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0, value: 0,
  easing: 'ease-in-out', ...values});
const scene = (id, entities, values = {}) => ({id, template: 'motion', chapterId: 'first', from: 0,
  durationInFrames: 90, lines: [], visual: {title: id, entities, paths: [], actions: []}, ...values});
const trace = {sourceTemplate: 'process', actorIds: ['person'], stationEntityIds: ['station'], events: []};
const inside = (box, viewport, message = '') => {
  const epsilon = 1e-6;
  assert.ok(box.left >= viewport.x - epsilon && box.right <= viewport.x + viewport.width + epsilon &&
    box.top >= viewport.y - epsilon && box.bottom <= viewport.y + viewport.height + epsilon,
  `${message}: ${JSON.stringify(box)} leaves ${JSON.stringify(viewport)}`);
};

test('related generic motion shares one camera and label plan across every shot', () => {
  const hub = entity('hub', 'server', {label: 'Origin'});
  const packet = entity('message', 'packet', {x: 8, y: 12, label: 'Message'});
  const first = scene('outbound', [hub, packet]);
  first.visual.actions.push(action('message', 'move', 0, {x: 95, y: -20}));
  const second = scene('inbound', [{...hub, label: 'Origin after delivery'}, {...packet, x: 95, y: -20}], {from: 90});
  second.visual.actions.push(action('message', 'move', 90, {x: 135, y: 110}));
  const source = JSON.stringify([first, second]);
  const plans = processPresentations([first, second]);
  const a = plans.get(first.id);
  const b = plans.get(second.id);
  assert.equal(a.group, b.group);
  assert.equal(a.viewport, b.viewport, 'the same camera object covers both movement envelopes');
  assert.equal(a.labelSlots, b.labelSlots, 'labels must use one shared geometry reservation');
  assert.ok(a.viewport.x + a.viewport.width > 1200, 'the later off-stage path contributes to the first shot camera');
  assert.equal(JSON.stringify([first, second]), source, 'planning must not rewrite authored positions or labels');
  const hubOffsets = new Set();
  for (const shot of [first, second]) {
    const program = compileMotion(shot.visual);
    for (let frame = shot.from; frame < shot.from + shot.durationInFrames; frame += 3) {
      const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
      for (const {prepared, state} of actors) {
        const point = toStage(state);
        const radius = entityHalfExtents(prepared.entity.kind, state.size, state.rotation);
        inside({left: point.x - radius.x, right: point.x + radius.x,
          top: point.y - radius.y, bottom: point.y + radius.y}, a.viewport, `${shot.id} actor ${prepared.entity.id}`);
      }
      for (const label of placeActorLabels(actors, a.viewport, a.labelSlots)) {
        inside(label.bounds, a.viewport, `${shot.id} label`);
        if (label.actor.prepared.entity.id === 'hub') {
          const point = toStage(label.actor.state);
          hubOffsets.add(`${label.x - point.x},${label.y - point.y}`);
        }
      }
    }
  }
  assert.equal(hubOffsets.size, 1, 'a changed label cannot move its fixed anchor between related shots');
});

test('shared object identity groups spacecraft, packets, boxes and people without a process trace', () => {
  for (const kind of ['spacecraft', 'packet', 'box', 'person']) {
    const first = scene('first', [entity('subject', kind)]);
    const second = scene('second', [entity('subject', kind, {x: 80, color: 'secondary'})], {from: 90});
    const plans = processPresentations([first, second]);
    assert.equal(plans.get('first').group, plans.get('second').group, kind);
    assert.equal(plans.get('first').viewport, plans.get('second').viewport, kind);
  }
});

test('different chapters, unrelated identities, changed kinds and non-motion interruptions split stages', () => {
  const first = scene('first', [entity('subject', 'spacecraft')]);
  const cases = [
    scene('next', [entity('subject', 'spacecraft')], {chapterId: 'second', from: 90}),
    scene('next', [entity('other', 'spacecraft')], {from: 90}),
    scene('next', [entity('subject', 'packet')], {from: 90}),
  ];
  for (const next of cases) {
    const plans = processPresentations([first, next]);
    assert.notEqual(plans.get('first').group, plans.get('next').group);
    assert.notEqual(plans.get('first').viewport, plans.get('next').viewport);
  }
  const next = scene('next', [entity('subject', 'spacecraft')], {from: 180});
  const card = {id: 'card', template: 'quote', chapterId: 'first', from: 90, durationInFrames: 90};
  const plans = processPresentations([first, card, next]);
  assert.equal(plans.has('card'), false);
  assert.notEqual(plans.get('first').group, plans.get('next').group);
});

test('process and generic scenes keep separate stage layouts even with the same cast', () => {
  const cast = [entity('person', 'person'), entity('station', 'counter', {x: 75})];
  const process = scene('compiled', cast, {processTrace: trace});
  const generic = scene('authored', cast, {from: 90});
  const resumed = scene('resumed', cast, {from: 180, processTrace: trace});
  const plans = processPresentations([process, generic, resumed], true);
  assert.equal(new Set([...plans.values()].map((plan) => plan.group)).size, 3);
  assert.ok(plans.get('compiled').room, 'compiled sketch stages keep their room');
  assert.equal(plans.get('authored').room, null, 'generic motion keeps its authored stage');
  assert.deepEqual(plans.get('authored').props, []);
});

test('sketch camera includes the complete tall human silhouette during movement, scale and rotation', () => {
  const human = entity('human', 'person', {x: 2, y: 0, label: 'Human', size: 1.4});
  const shot = scene('human motion', [human]);
  shot.visual.actions = [action('human', 'move', 0, {x: 105, y: -25}),
    action('human', 'scale', 0, {value: 2}), action('human', 'rotate', 0, {value: 120})];
  const program = compileMotion(shot.visual);
  const sketch = processPresentations([shot], true).get(shot.id);
  const vector = fitMotionViewport(program, {look: 'vector'});
  assert.ok(sketch.viewport.height > vector.height, 'sketch hair and body need a larger envelope');
  assert.equal(sketch.labelSlots.look, 'sketch');
  for (let frame = 0; frame < shot.durationInFrames; frame++) {
    const current = entityAtFrame(program.entities[0], frame);
    const origin = toStage(current);
    const radians = current.rotation * Math.PI / 180;
    // The sketch character's physical silhouette reaches 94 units vertically and 45 horizontally.
    // Transform those corners independently of the camera's extent helper, plus its 3-unit stroke.
    const corners = [-45, 45].flatMap((x) => [-94, 94].map((y) => ({
      x: origin.x + (x * Math.cos(radians) - y * Math.sin(radians)) * current.size,
      y: origin.y + (x * Math.sin(radians) + y * Math.cos(radians)) * current.size,
    })));
    const stroke = 3 * current.size;
    inside({left: Math.min(...corners.map((p) => p.x)) - stroke,
      right: Math.max(...corners.map((p) => p.x)) + stroke,
      top: Math.min(...corners.map((p) => p.y)) - stroke,
      bottom: Math.max(...corners.map((p) => p.y)) + stroke}, sketch.viewport, `human frame ${frame}`);
  }
});

test('close-up process framing also reserves sketch hair above the vector head', () => {
  const human = entity('person', 'person', {x: 10, y: 0, size: 1.6});
  const station = entity('station', 'counter', {x: 65, y: 40});
  const shot = scene('process human', [human, station], {processTrace: trace});
  const sketch = processPresentations([shot], true).get(shot.id);
  const origin = toStage(human);
  inside({left: origin.x - 48 * human.size, right: origin.x + 48 * human.size,
    top: origin.y - 97 * human.size, bottom: origin.y + 97 * human.size}, sketch.viewport);
  assert.equal(sketch.labelSlots.look, 'sketch');
  assert.ok(sketch.room);
});
