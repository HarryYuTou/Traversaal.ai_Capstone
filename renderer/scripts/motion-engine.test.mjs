import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';

// Exercise the actual TypeScript engine without adding a test runner or generating build files.
const urls = new Map();
const moduleUrl = async (file) => {
  if (urls.has(file.href)) return urls.get(file.href);
  const source = await readFile(file, 'utf8');
  let {outputText} = ts.transpileModule(source, {compilerOptions: {
    module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React,
  }});
  for (const match of [...outputText.matchAll(/from (['"])([^'"]+)\1/g)]) {
    const local = (extension) => new URL(`${match[2]}${extension}`, file);
    const dependency = match[2].startsWith('./')
      ? await moduleUrl(existsSync(local('.ts')) ? local('.ts') : local('.tsx')) : import.meta.resolve(match[2]);
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {compileMotion, displayedPaths, entityAtFrame, pathGeometry, pointOnPath, toStage} =
  await load('engine');
const {BASE_VIEWPORT, fitMotionViewport, fitProcessViewport, motionStageRect} = await load('camera');
const {entityHalfExtents, labelMetrics} = await load('metrics');
const {processPresentations} = await load('processPresentation');
const {placeActorLabels, planLabelSlots, PROCESS_LABEL_ORDER} = await load('labels');
const {activityAtFrame, carryAtFrame, idlePoseAtFrame, movementPoseAtFrame, illustrationPoseAtFrame, personLimbs,
  walkBob, workbenchPress, CARRY_FRAMES} = await load('pose');
const {easing} = await load('engine');
const {Illustration, mixColor} = await import(await moduleUrl(new URL('../src/motion/Illustration.tsx', import.meta.url)));

const actor = {id: 'ship', kind: 'spacecraft', x: 10, y: 40, size: 1, rotation: 0, opacity: 1,
  value: 1, color: 'accent', label: ''};
const action = (kind, from, durationInFrames, values = {}) => ({entityId: 'ship', kind, startLine: 0, endLine: 0,
  startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0, value: 0, easing: 'linear', from, durationInFrames, ...values});
const program = (actions, paths = [], entity = actor) => compileMotion({title: 'Test', entities: [entity], paths, actions});
const state = (p, frame) => entityAtFrame(p.entities[0], frame);
const near = (actual, expected, tolerance = 1e-7) => assert.ok(Math.abs(actual - expected) < tolerance, `${actual} != ${expected}`);

test('random seeking is deterministic and an ended movement holds its result', () => {
  const p = program([action('move', 100, 40, {x: 70, y: 60})]);
  const expected = state(p, 120);
  [180, 100, 150, 0, 119].forEach((frame) => state(p, frame));
  assert.deepEqual(state(p, 120), expected);
  near(state(p, 90).x, 10);
  near(state(p, 120).x, 40);
  near(state(p, 500).x, 70);
});

test('chronological actions produce the same result when storyboard array order changes', () => {
  const actions = [action('move', 0, 20, {x: 50, y: 30}), action('move', 30, 20, {x: 90, y: 70})];
  const forward = program(actions);
  const reverse = program([...actions].reverse());
  for (const frame of [0, 10, 20, 25, 30, 40, 50, 90]) assert.deepEqual(state(forward, frame), state(reverse, frame));
  near(state(forward, 40).x, 70);
});

test('position, rotation, opacity, absolute scale and value run concurrently', () => {
  const p = program([action('move', 20, 40, {x: 90, y: 80}), action('opacity', 20, 40, {value: 0}),
    action('rotate', 20, 40, {value: 180}), action('scale', 20, 40, {value: 2}), action('value', 20, 40, {value: 0.2})]);
  const middle = state(p, 40);
  near(middle.x, 50); near(middle.y, 60); near(middle.rotation, 90);
  near(middle.opacity, 0.5); near(middle.size, 1.5); near(middle.value, 0.6);
  near(state(p, 100).size, 2);
});

test('retargeting a property captures its value at the new action start', () => {
  const p = program([action('opacity', 0, 100, {value: 0}), action('opacity', 50, 50, {value: 1})]);
  near(state(p, 50).opacity, 0.5);
  near(state(p, 75).opacity, 0.75);
  near(state(p, 200).opacity, 1);
});

test('a curved route starts at the actor and the displayed geometry is exactly the movement geometry', () => {
  const path = {id: 'route', points: [{x: 30, y: 40}, {x: 50, y: 10}, {x: 85, y: 70}],
    curved: true, closed: false, color: 'muted'};
  const p = program([action('follow-path', 20, 100, {pathId: 'route'})], [path]);
  const geometry = displayedPaths(p, 70)[0].geometry;
  near(state(p, 20).x, actor.x);
  near(state(p, 20).y, actor.y);
  for (const frame of [25, 50, 70, 110, 120]) {
    const actual = toStage(state(p, frame));
    const expected = pointOnPath(geometry, (frame - 20) / 100);
    near(actual.x, expected.x); near(actual.y, expected.y);
  }
  near(state(p, 500).x, 85);
  assert.ok(geometry.points.length > 50);
});

test('path progress is proportional to travel distance, not control-point count', () => {
  const geometry = pathGeometry({id: 'uneven', points: [{x: 0, y: 0}, {x: 1, y: 0}, {x: 100, y: 0}],
    curved: false, closed: false, color: 'muted'});
  near(pointOnPath(geometry, 0.5).x, 600);
  near(pointOnPath(geometry, 0.25).x, 300);
});

test('orbit follows a physical circle on the wide stage and starts from the previous movement result', () => {
  const p = program([action('move', 0, 10, {x: 60, y: 50}), action('orbit', 10, 40, {x: 50, y: 50, value: 360})]);
  const center = toStage({x: 50, y: 50});
  for (const frame of [10, 15, 20, 25, 30, 40, 50]) {
    const at = toStage(state(p, frame));
    near(Math.hypot(at.x - center.x, at.y - center.y), 120);
  }
  near(state(p, 20).x, 50); near(state(p, 20).y, 74);
  near(state(p, 90).x, 60); near(state(p, 90).y, 50);
});

test('a following action starts from the held endpoint of a curved path', () => {
  const path = {id: 'route', points: [{x: 10, y: 40}, {x: 50, y: 10}, {x: 70, y: 60}],
    curved: true, closed: false, color: 'muted'};
  const p = program([action('follow-path', 10, 40, {pathId: 'route'}), action('move', 60, 20, {x: 90, y: 60})], [path]);
  near(state(p, 60).x, 70); near(state(p, 70).x, 80);
});

test('actors sharing a route retain their own connecting segments and reveal times', () => {
  const path = {id: 'route', points: [{x: 30, y: 40}, {x: 80, y: 40}], curved: false, closed: false, color: 'muted'};
  const p = compileMotion({title: 'Shared route', entities: [actor, {...actor, id: 'other', x: 20, y: 60}], paths: [path],
    actions: [action('follow-path', 100, 100, {pathId: 'route'}),
      action('follow-path', 120, 100, {entityId: 'other', pathId: 'route'})]});
  const routes = displayedPaths(p, 110);
  assert.equal(routes.length, 2);
  assert.equal(routes[0].from, 100); assert.equal(routes[1].from, 120);
  near(routes[0].geometry.points[0].x, 120);
  near(routes[1].geometry.points[0].x, 240);
  assert.equal(routes[1].progress, 0);
});

test('closed curved paths return to their start without a seam in the direction of travel', () => {
  const geometry = pathGeometry({id: 'loop', points: [{x: 60, y: 50}, {x: 50, y: 74}, {x: 40, y: 50}, {x: 50, y: 26}],
    curved: true, closed: true, color: 'muted'});
  const first = geometry.points[0];
  const last = geometry.points.at(-1);
  near(first.x, last.x); near(first.y, last.y);
  const next = geometry.points[1];
  const prior = geometry.points.at(-2);
  assert.ok(Math.abs(next.x - first.x) < Math.abs(next.y - first.y));
  assert.ok(Math.abs(last.x - prior.x) < Math.abs(last.y - prior.y));
});

const inside = (box, viewport) => {
  assert.ok(box.left >= viewport.x - 1e-6, `left ${box.left} outside ${viewport.x}`);
  assert.ok(box.top >= viewport.y - 1e-6, `top ${box.top} outside ${viewport.y}`);
  assert.ok(box.right <= viewport.x + viewport.width + 1e-6, 'right edge clipped');
  assert.ok(box.bottom <= viewport.y + viewport.height + 1e-6, 'bottom edge clipped');
};
const actorBox = (entity, current) => {
  const at = toStage(current);
  const half = entityHalfExtents(entity.kind, current.size, current.rotation);
  return {left: at.x - half.x, top: at.y - half.y, right: at.x + half.x, bottom: at.y + half.y};
};

test('whole-scene fitting contains an off-stage orbit, simultaneous scaling/rotation and labels', () => {
  const entity = {...actor, x: 80, y: 50, label: 'Orbiting spacecraft'};
  const p = program([action('orbit', 0, 120, {x: 50, y: 50, value: 360}),
    action('scale', 0, 120, {value: 2.5}), action('rotate', 0, 120, {value: 270})], [], entity);
  const viewport = fitMotionViewport(p);
  assert.ok(viewport.y < -110);
  assert.ok(viewport.y + viewport.height > 610);
  for (let frame = 0; frame <= 120; frame++) {
    const current = state(p, frame);
    inside(actorBox(entity, current), viewport);
    const labels = placeActorLabels([{prepared: p.entities[0], state: current}], viewport);
    for (const label of labels) {
      const {width, fontSize} = labelMetrics(entity.label);
      inside({left: label.x - width / 2, right: label.x + width / 2,
        top: label.y - fontSize, bottom: label.y + 6}, viewport);
    }
  }
  state(p, 1000); state(p, 20);
  assert.deepEqual(fitMotionViewport(p), viewport, 'camera must not follow the currently rendered frame');
});

test('fitting includes curved-route overshoot and the full moving illustration, not just control points', () => {
  const path = {id: 'edge-curve', points: [{x: 0, y: 0}, {x: 0, y: 100}, {x: 100, y: 100}, {x: 100, y: 0}],
    curved: true, closed: false, color: 'muted'};
  const entity = {...actor, x: 0, y: 0, size: 3, rotation: 45, label: 'WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW'};
  const p = program([action('follow-path', 0, 120, {pathId: path.id})], [path], entity);
  const viewport = fitMotionViewport(p);
  const geometry = displayedPaths(p, 60)[0].geometry;
  assert.ok(geometry.points.some(({x}) => x < 0));
  assert.ok(geometry.points.some(({x}) => x > 1200));
  assert.ok(geometry.points.some(({y}) => y > 500));
  for (const point of geometry.points) {
    const half = entityHalfExtents(entity.kind, 3, 45);
    inside({left: point.x - half.x, right: point.x + half.x, top: point.y - half.y, bottom: point.y + half.y}, viewport);
  }
  for (let frame = 0; frame <= 120; frame++) {
    const current = state(p, frame);
    inside(actorBox(entity, current), viewport);
    const [{x, y}] = placeActorLabels([{prepared: p.entities[0], state: current}], viewport);
    const {width, fontSize} = labelMetrics(entity.label);
    inside({left: x - width / 2, right: x + width / 2, top: y - fontSize, bottom: y + 6}, viewport);
  }
});

test('conservative authored scenes retain the original camera', () => {
  const p = program([action('move', 0, 100, {x: 60, y: 55})], [], {...actor, x: 40, y: 50, label: 'Ship'});
  assert.deepEqual(fitMotionViewport(p), BASE_VIEWPORT);
});

test('the fitted picture stays inside the physical title/caption-safe stage at full and draft sizes', () => {
  const p = program([action('orbit', 0, 120, {x: 50, y: 50, value: 360})], [], {...actor, x: 80, label: 'Cabin'});
  const viewport = fitMotionViewport(p);
  for (const [videoWidth, videoHeight] of [[1920, 1080], [960, 540]]) {
    const stage = motionStageRect(videoWidth, videoHeight);
    const scale = Math.min(stage.width / viewport.width, stage.height / viewport.height);
    const xOffset = stage.x + (stage.width - viewport.width * scale) / 2;
    const yOffset = stage.y + (stage.height - viewport.height * scale) / 2;
    for (let frame = 0; frame <= 120; frame++) {
      const box = actorBox(p.entities[0].entity, state(p, frame));
      const screen = {left: xOffset + (box.left - viewport.x) * scale, right: xOffset + (box.right - viewport.x) * scale,
        top: yOffset + (box.top - viewport.y) * scale, bottom: yOffset + (box.bottom - viewport.y) * scale};
      inside(screen, {x: stage.x, y: stage.y, width: stage.width, height: stage.height});
      assert.ok(screen.top >= videoHeight * 205 / 1080 - 1e-6, 'actor enters the title area');
      assert.ok(screen.bottom <= videoHeight * 860 / 1080 + 1e-6, 'actor enters the caption reserve');
    }
  }
});

test('large but finite orbit and rotation angles never create NaN geometry', () => {
  const p = program([action('orbit', 0, 100, {x: 50, y: 50, value: 1e308}),
    action('rotate', 0, 100, {value: 1e308})], [], {...actor, rotation: -1e308});
  for (const frame of [0, 1, 25, 50, 99, 100, 200]) {
    const current = state(p, frame);
    assert.ok(Number.isFinite(current.x) && Number.isFinite(current.y) && Number.isFinite(current.rotation));
    const extents = entityHalfExtents('spacecraft', current.size, current.rotation);
    assert.ok(Number.isFinite(extents.x) && Number.isFinite(extents.y));
  }
});

test('activity is seek-stable, work ends at completion and acknowledgement has a bounded lifetime', () => {
  const activities = [
    {entityId: 'ship', kind: 'complete', from: 140, durationInFrames: 20},
    {entityId: 'ship', kind: 'work', from: 100, durationInFrames: 40},
  ];
  assert.equal(activityAtFrame(activities, 99), null);
  assert.deepEqual(activityAtFrame(activities, 100), {kind: 'work', progress: 0, phase: 0, opacity: 1});
  near(activityAtFrame(activities, 120).progress, 0.5);
  assert.equal(activityAtFrame(activities, 139).kind, 'work');
  assert.equal(activityAtFrame(activities, 140).kind, 'complete');
  near(activityAtFrame(activities, 159).opacity, 0.2);
  assert.equal(activityAtFrame(activities, 160), null);
  const expected = activityAtFrame(activities, 123);
  [180, 90, 145, 1].forEach((frame) => activityAtFrame(activities, frame));
  assert.deepEqual(activityAtFrame([...activities].reverse(), 123), expected);
  const overlap = [...activities, {entityId: 'ship', kind: 'work', from: 145, durationInFrames: 30}];
  assert.equal(activityAtFrame(overlap, 150).kind, 'complete');
  assert.equal(activityAtFrame([...overlap].reverse(), 150).kind, 'complete');
});

test('walking depends on actual distance, stops at the endpoint and is independent of seek order', () => {
  const person = {...actor, kind: 'person', size: 0.7};
  const a = program([action('move', 100, 80, {x: 70, y: 40})], [], person).entities[0];
  const b = program([action('move', 100, 160, {x: 70, y: 40})], [], person).entities[0];
  const halfway = movementPoseAtFrame(a, 140);
  assert.equal(halfway.walking, true);
  assert.deepEqual(movementPoseAtFrame(b, 180), halfway, 'same distance produces the same articulated pose');
  for (const frame of [0, 99, 180, 1000]) assert.equal(movementPoseAtFrame(a, frame).walking, false);
  [170, 101, 220, 0].forEach((frame) => movementPoseAtFrame(a, frame));
  assert.deepEqual(movementPoseAtFrame(a, 140), halfway);
  const noTravel = program([action('move', 100, 80, {x: person.x, y: person.y})], [], person).entities[0];
  assert.equal(movementPoseAtFrame(noTravel, 140).walking, false);
  assert.equal(movementPoseAtFrame(program([action('move', 100, 80, {x: 70, y: 40})]).entities[0], 140).walking, false);
});

test('walking follows sampled curve distance rather than straight-line displacement', () => {
  const path = {id: 'loop', points: [{x: 10, y: 40}, {x: 30, y: 10}, {x: 50, y: 60}, {x: 10, y: 40}],
    curved: true, closed: false, color: 'muted'};
  const person = {...actor, kind: 'person'};
  const p = program([action('follow-path', 20, 100, {pathId: 'loop'})], [path], person).entities[0];
  const pose = movementPoseAtFrame(p, 70);
  near(pose.phase, (p.actions[0].geometry.length * 0.5 / 44) % 1);
  assert.equal(pose.walking, true);
});

test('all articulated person poses, service marks and moving bench tooling fit the declared drawing bounds', () => {
  const bounds = entityHalfExtents('person', 1, 0);
  for (let step = 0; step <= 100; step++) {
    for (const kind of [null, 'work', 'complete']) {
      const activity = kind ? {kind, progress: step / 100, phase: step / 100, opacity: 1} : null;
      for (const walking of [false, true]) {
        const pose = {movement: {walking, phase: step / 100, strength: 1}, activity};
        for (const points of Object.values(personLimbs(pose))) {
          for (const point of points) {
            assert.ok(Math.abs(point.x) + 3 <= bounds.x && Math.abs(point.y) + 3 <= bounds.y,
              'articulated limb plus round stroke escapes the fitted body');
          }
        }
      }
      const press = workbenchPress(activity);
      assert.ok(press >= 0 && press <= 7);
      inside({left: 18, right: 38, top: -45 + press, bottom: -22 + press},
        {x: -58, y: -52, width: 116, height: 104});
    }
  }
  // Completion rings are larger than the progress bar and cover its complete drawing envelope.
  for (const [kind, x, y] of [['person', 0, 15], ['counter', 24, -34], ['workbench', -13, -20]]) {
    const extent = entityHalfExtents(kind, 1, 0);
    inside({left: x - 15, right: x + 15, top: y - 13, bottom: y + 13},
      {x: -extent.x, y: -extent.y, width: 2 * extent.x, height: 2 * extent.y});
  }
});

test('new station assets render real geometry and only show event feedback inside its interval', () => {
  const palette = {paper: '#fbf8f0', soft: '#e8e3d7', ink: '#293333', accent: '#dc7451',
    secondary: '#548e85', muted: '#8a9488', line: '#d9d9cc'};
  for (const kind of ['counter', 'workbench', 'person']) {
    const entity = {...actor, kind, x: 95, y: 95, rotation: 30, label: 'Service'};
    const p = compileMotion({title: 'Service', entities: [entity], paths: [], actions: [], activities: [
      {entityId: entity.id, kind: 'work', from: 10, durationInFrames: 40},
      {entityId: entity.id, kind: 'complete', from: 50, durationInFrames: 20},
    ]});
    for (const [frame, expected] of [[0, null], [10, 'work'], [30, 'work'], [50, 'complete'], [69, 'complete'], [70, null]]) {
      const pose = illustrationPoseAtFrame(p.entities[0], frame);
      const svg = renderToStaticMarkup(React.createElement(Illustration, {entity, state: state(p, frame),
        palette, prefix: 'test', pose}));
      assert.ok(svg.includes('<path') && svg.length > 600, `${kind} must have drawn geometry`);
      assert.ok(!/NaN|Infinity/.test(svg));
      assert.ok(!svg.includes('%'), 'service progress does not imply an unsupported percentage');
      if (expected) assert.ok(svg.includes(`data-motion-activity="${expected}"`));
      else assert.ok(!svg.includes('data-motion-activity='));
      assert.equal(svg, renderToStaticMarkup(React.createElement(Illustration, {entity, state: state(p, frame),
        palette, prefix: 'test', pose: illustrationPoseAtFrame(p.entities[0], frame)})));
      inside(actorBox(entity, state(p, frame)), fitMotionViewport(p));
    }
  }
});


const processScene = (id, visual, trace, chapterId = 'chapter-1') => ({
  id, chapterId, from: 100, durationInFrames: 500, lines: [], template: 'motion', visual, processTrace: trace,
});
const cameraTrace = {sourceTemplate: 'process', actorIds: ['ship'], stationEntityIds: ['desk'],
  events: [{kind: 'hold', from: 100, durationInFrames: 200}, {kind: 'start', from: 300, durationInFrames: 100}]};
const cameraVisual = {title: 'A process', paths: [], entities: [
  {...actor, kind: 'person', x: 55, y: 50, label: 'Customer'},
  {...actor, id: 'desk', kind: 'counter', x: 79, y: 50, color: 'secondary', label: 'Counter 1'},
  {...actor, id: 'unused', x: -1000, opacity: 0},
], actions: [action('move', 300, 100, {x: 95, y: 10})]};

test('process content framing ignores never-visible cast while keeping all actual movement and labels', () => {
  const p = compileMotion(cameraVisual);
  const viewport = fitProcessViewport([p]);
  assert.ok(viewport.width < 1200, 'empty spawn points must not create empty canvas');
  for (let frame = 100; frame <= 400; frame++) {
    for (const prepared of p.entities) {
      const current = entityAtFrame(prepared, frame);
      if (current.opacity > 0.05) inside(actorBox(prepared.entity, current), viewport);
    }
  }
});

test('related process scenes share the same wide frame without mutating colors or unrelated chapters', () => {
  const a = processScene('a', cameraVisual, cameraTrace);
  const alternate = {...cameraVisual, entities: cameraVisual.entities.map((entity) => entity.id === 'ship'
    ? {...entity, x: 40, color: 'secondary'} : entity)};
  const b = processScene('b', alternate, cameraTrace);
  const c = processScene('c', cameraVisual, cameraTrace, 'chapter-2');
  const source = JSON.stringify([a, b, c]);
  const presentations = processPresentations([a, b, c]);
  assert.deepEqual(presentations.get('a').viewport, presentations.get('b').viewport);
  assert.notDeepEqual(presentations.get('b').viewport, presentations.get('c').viewport);
  assert.equal(JSON.stringify([a, b, c]), source);
  assert.equal(b.visual.entities[0].color, 'secondary', 'authored color-referenced content is preserved');
  const split = processPresentations([a, {...b, id: 'unrelated', processTrace: {...cameraTrace, actorIds: ['other']}}]);
  assert.notDeepEqual(split.get('a').viewport, split.get('unrelated').viewport);
});

test('related process shots keep one locked frame with every body and planned label inside it', () => {
  const a = processScene('a', cameraVisual, cameraTrace);
  const b = processScene('b', cameraVisual, cameraTrace);
  const presentations = processPresentations([a, b]);
  assert.equal(presentations.get('a').group, presentations.get('b').group, 'related shots share a stage');
  assert.equal(presentations.get('a').labelSlots, presentations.get('b').labelSlots, 'one label plan per stage');
  const p = compileMotion(cameraVisual);
  const viewport = presentations.get('a').viewport;
  const slots = presentations.get('a').labelSlots;
  assert.equal(slots.get('desk'), PROCESS_LABEL_ORDER[0], 'a counter label sits beside it, clear of walkers');
  const offsets = new Set();
  for (let frame = 90; frame <= 410; frame++) {
    const actors = p.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
    for (const {prepared, state: current} of actors) {
      if (current.opacity > 0.05) inside(actorBox(prepared.entity, current), viewport);
    }
    for (const label of placeActorLabels(actors, viewport, slots)) {
      const {width, fontSize} = labelMetrics(label.actor.prepared.entity.label);
      inside({left: label.x - width / 2, right: label.x + width / 2,
        top: label.y - fontSize, bottom: label.y + 6}, viewport);
      const body = toStage(label.actor.state);
      if (label.actor.prepared.entity.id === 'desk') offsets.add(`${label.x - body.x},${label.y - body.y}`);
    }
  }
  assert.equal(offsets.size, 1, 'the counter label never moves relative to the counter');
  const split = processPresentations([a, {...b, id: 'other', processTrace: {...cameraTrace, actorIds: ['someone']}}]);
  assert.notEqual(split.get('a').group, split.get('other').group);
});

test('a station label keeps its side for the whole scene while someone walks past it', () => {
  const desk = {...actor, id: 'desk', kind: 'counter', x: 50, y: 50, label: 'Counter 1', color: 'secondary'};
  const walker = {...actor, id: 'walker', kind: 'person', x: 5, y: 78, label: ''};
  const visual = {title: 'Pass', paths: [], entities: [desk, walker], actions: [action('move', 0, 120, {x: 95, y: 78, entityId: 'walker'})]};
  const p = compileMotion(visual);
  const frames = Array.from({length: 121}, (_, index) => index);
  const sideAt = (frame, slots) => {
    const actors = p.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
    const [label] = placeActorLabels(actors, BASE_VIEWPORT, slots);
    return label.y > toStage(label.actor.state).y ? 'below' : 'above';
  };
  assert.ok(new Set(frames.map((frame) => sideAt(frame))).size > 1, 'per-frame placement jumps as the walker passes');
  const slots = planLabelSlots([{program: p, frames}]);
  assert.equal(new Set(frames.map((frame) => sideAt(frame, slots))).size, 1, 'planned placement never jumps');
  assert.equal(sideAt(60, slots), 'above', 'the planned side is the one the walker never crosses');
});

test('walk easing starts and stops smoothly and keeps a steady pace in between', () => {
  assert.equal(easing(0, 'walk'), 0);
  assert.equal(easing(1, 'walk'), 1);
  let previous = 0;
  let fastest = 0;
  for (let step = 1; step <= 1000; step++) {
    const value = easing(step / 1000, 'walk');
    assert.ok(value >= previous, 'a walk never steps backwards');
    fastest = Math.max(fastest, (value - previous) * 1000);
    previous = value;
  }
  assert.ok(fastest < 1.34, `top speed ${fastest} must stay near the average pace`);
  near(easing(0.4, 'walk') - easing(0.3, 'walk'), easing(0.7, 'walk') - easing(0.6, 'walk'));
  assert.ok(easing(0.01, 'walk') < 0.001, 'a walk starts from rest');
});

test('items are raised and lowered over several frames, and idle life is subtle and repeatable', () => {
  const work = [{entityId: 'a', kind: 'work', from: 100, durationInFrames: 60}];
  assert.equal(carryAtFrame(work, 99), 0);
  assert.equal(carryAtFrame(work, 100), 0);
  assert.ok(carryAtFrame(work, 103) > 0 && carryAtFrame(work, 103) < 1);
  assert.equal(carryAtFrame(work, 100 + CARRY_FRAMES), 1);
  assert.ok(carryAtFrame(work, 163) > 0 && carryAtFrame(work, 163) < 1, 'items go down after service, not at once');
  assert.equal(carryAtFrame(work, 160 + CARRY_FRAMES), 0);
  const bounds = entityHalfExtents('person', 1, 0);
  for (const carry of [0, 0.25, 0.5, 0.75, 1]) {
    for (const points of Object.values(personLimbs({movement: {walking: false, phase: 0, strength: 0},
      activity: {kind: 'work', progress: 0.5, phase: 0.3, opacity: 1}, carry}))) {
      for (const point of points) assert.ok(Math.abs(point.x) + 3 <= bounds.x && Math.abs(point.y) + 3 <= bounds.y);
    }
  }
  for (let frame = 0; frame < 400; frame++) {
    const idle = idlePoseAtFrame('shopper-a', frame);
    assert.ok(Math.abs(idle.breath) <= 1 && idle.blink >= 0 && idle.blink <= 1);
    assert.deepEqual(idlePoseAtFrame('shopper-a', frame), idle);
  }
  assert.notDeepEqual([0, 1, 2, 3].map((frame) => idlePoseAtFrame('shopper-a', frame)),
    [0, 1, 2, 3].map((frame) => idlePoseAtFrame('shopper-b', frame)), 'actors do not breathe in lockstep');
  const bob = walkBob({movement: {walking: true, phase: 0.25, strength: 1}, activity: null});
  assert.ok(bob > 0 && bob <= 3);
  assert.equal(mixColor('#000000', '#ffffff', 0.5), '#808080');
  assert.equal(mixColor('#8d95a3', '#548e85', 1), '#548e85');
});

test('station signage uses readable vector text and open/closed states preserve authored entity data', () => {
  const entity = {...actor, kind: 'counter', color: 'accent'};
  const palette = {paper: '#fbf8f0', soft: '#e8e3d7', ink: '#293333', accent: '#dc7451',
    secondary: '#548e85', muted: '#8a9488', line: '#d9d9cc'};
  const original = JSON.stringify(entity);
  for (const [open, progress, expected] of [[false, 0, 'CLOSED'], [false, 0.5, 'OPENING'], [true, 1, 'OPEN']]) {
    const svg = renderToStaticMarkup(React.createElement(Illustration, {entity, state: entity,
      palette, prefix: 'station', station: {open, openingProgress: progress}}));
    assert.ok(svg.includes(`>${expected}</text>`));
    assert.ok(svg.includes(`data-station-state="${open ? 'open' : 'closed'}"`));
    if (progress === 0.5) assert.ok(svg.includes('stroke-dasharray="0.5 1"'));
    assert.ok(!/NaN|Infinity/.test(svg));
  }
  assert.equal(JSON.stringify(entity), original);
});

test('captions break into balanced rows of known size, so the box can ease between lines', async () => {
  const {layoutCaption} = await import(await moduleUrl(new URL('../src/captionLayout.ts', import.meta.url)));
  const measure = (text) => text.length * 20;
  const short = layoutCaption('Three shoppers are waiting.', measure);
  assert.deepEqual(short.rows, ['Three shoppers are waiting.']);
  assert.equal(short.width, 27 * 20 + 72);
  const text = 'Same shoppers, same service time, but two counters share the work, so waiting shrinks.';
  const long = layoutCaption(text, measure);
  assert.equal(long.rows.length, 2);
  assert.equal(long.rows.join(' '), text);
  assert.ok(Math.abs(long.rows[0].length - long.rows[1].length) < 12, 'rows are balanced, not greedy');
  assert.ok(long.width <= 1480 && long.height > short.height);
});

test('sketch legs stand straight at rest and keep every stride inside the person footprint', async () => {
  const {legsAt, sketchCast} = await import(await moduleUrl(new URL('../src/motion/sketch.tsx', import.meta.url)));
  for (const leg of legsAt(0.3, 0, 1)) {
    near(leg.knee.x, leg.hip.x); near(leg.ankle.x, leg.hip.x);
  }
  const extent = entityHalfExtents('person', 1, 0);
  for (let step = 0; step <= 100; step++) {
    for (const direction of [1, -1]) {
      const legs = legsAt(step / 100, 1, direction);
      // Feet are drawn 60 units below these coordinates' origin (SketchPerson translates by 60).
      for (const {ankle} of legs) assert.ok(Math.abs(ankle.x) + 12 <= extent.x && ankle.y + 60 <= extent.y);
    }
  }
  assert.deepEqual(sketchCast('shopper-a'), sketchCast('shopper-a'), 'an actor always wears the same outfit');
});
