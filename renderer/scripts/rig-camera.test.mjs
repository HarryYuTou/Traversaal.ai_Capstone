import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
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
const load = async (name) => import(await moduleUrl(new URL(`../src/motion/${name}.ts`, import.meta.url)));
const {prepareRig, rigPictureAtFrame, rotatedRigExtents, transformedRigBounds} = await load('rig');
const {compileMotion, entityAtFrame, toStage} = await load('engine');
const {fitMotionViewport, fitAuthoredMotionViewport, fitProcessViewport} = await load('camera');
const {processPresentations} = await load('processPresentation');
const {entityHalfExtents} = await load('metrics');
const {placeActorLabels, planLabelSlots} = await load('labels');

const rect = (extra = {}) => ({kind: 'rect', x: 0, y: -5, width: 130, height: 10, radius: 0,
  path: '', fill: 'secondary', stroke: 'none', strokeWidth: 0, ...extra});
const part = (id, extra = {}) => ({id, parentId: '', x: 0, y: 0, rotation: 0,
  scaleX: 1, scaleY: 1, opacity: 1, shapes: [rect()], ...extra});
const track = (partId, property, values) => ({partId, property,
  keyframes: values.map((value, index) => ({at: index / (values.length - 1), value, easing: 'ease-in-out'}))});
const rig = (parts, tracks) => ({id: 'plant', parts, clips: [{id: 'sway', tracks}]});
const performance = (from = 0, durationInFrames = 120) => ({entityId: 'plant', clipId: 'sway',
  startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, from, durationInFrames, repeat: 1});
const entity = (extra = {}) => ({id: 'plant', kind: 'custom', rigId: 'plant', x: 50, y: 65,
  size: 1, rotation: 0, opacity: 1, value: 0, color: 'secondary', label: '', ...extra});
const visual = (definition, extra = {}) => ({title: 'Small living object', entities: [entity()],
  paths: [], actions: [], rigs: [definition], performances: [performance()], ...extra});
const scene = (id, from, drawing, extra = {}) => ({id, from, template: 'motion', chapterId: 'demo',
  durationInFrames: 120, lines: [], visual: drawing, ...extra});
const inside = (box, view, why = '') => assert.ok(box.left >= view.x - 1e-6 && box.top >= view.y - 1e-6
  && box.right <= view.x + view.width + 1e-6 && box.bottom <= view.y + view.height + 1e-6,
`${why}: ${JSON.stringify(box)} leaves ${JSON.stringify(view)}`);

test('a small leaf sway reserves its actual angular interval instead of a full circular footprint', () => {
  const prepared = prepareRig(rig([part('stem', {x: -70, y: 6, shapes: []}),
    part('blade', {parentId: 'stem'})], [track('blade', 'rotation', [0, 5, -2, 0])]), [performance()]);
  assert.ok(prepared.extents[0] < 71, `leaf width was inflated: ${prepared.extents}`);
  assert.ok(prepared.extents[1] < 23, `leaf height was inflated: ${prepared.extents}`);
  assert.ok(prepared.extents[1] > 22, 'small-angle tip excursion remains included');
});

test('analytic bounds include a turning-point maximum between keyframes and across angle wraparound', () => {
  const source = rig([part('blade', {rotation: -10, shapes: [rect({x: 0, y: 0, width: 200, height: 10})]})],
    [track('blade', 'rotation', [0, 60])]);
  const prepared = prepareRig(source, [performance()]);
  // The widest x occurs at -atan(10/200), not at either endpoint or the midpoint.
  assert.ok(Math.abs(prepared.extents[0] - Math.hypot(200, 10)) < 1e-9);
  assert.ok(Math.abs(prepared.extents[1] - (200 * Math.sin(50 * Math.PI / 180) + 10 * Math.cos(50 * Math.PI / 180))) < 1e-9);
  source.parts[0].rotation = 350;
  source.clips[0].tracks[0] = track('blade', 'rotation', [0, 20]);
  const wrap = prepareRig(source, [performance()]);
  assert.ok(Math.abs(wrap.extents[0] - Math.hypot(200, 10)) < 1e-9);
  assert.ok(wrap.extents[1] < 45);
  source.parts[0].rotation = -370;
  const negative = prepareRig(source, [performance()]);
  assert.ok(Math.abs(wrap.extents[0] - negative.extents[0]) < 1e-9);
  assert.ok(Math.abs(wrap.extents[1] - negative.extents[1]) < 1e-9);
});

test('one or more complete rotations retain the full swept radius', () => {
  for (const degrees of [360, 720, -360, -720]) {
    const prepared = prepareRig(rig([part('blade', {shapes: [rect({x: 0, y: 0, width: 200, height: 10})]})],
      [track('blade', 'rotation', [0, degrees])]), [performance()]);
    for (const extent of prepared.extents) assert.ok(Math.abs(extent - Math.hypot(200, 10)) < 1e-9);
  }
});

test('nested scale, translation and joint rotation envelopes contain every visible part at all poses', () => {
  const prepared = prepareRig(rig([part('base', {shapes: [], x: 12, y: -6, rotation: 25}),
    part('branch', {parentId: 'base', x: 18, y: 9, rotation: -30, scaleX: 1.3, shapes: []}),
    part('blade', {parentId: 'branch', x: 40, y: -5, rotation: 8,
      shapes: [rect({x: -12, y: -5, width: 75, height: 18, stroke: 'ink', strokeWidth: 4})]})],
  [track('base', 'rotation', [0, 8, -4, 0]), track('base', 'scaleY', [1, 1.2, 1]),
    track('branch', 'rotation', [0, -12, 15, 0]), track('branch', 'x', [0, 10]),
    track('blade', 'scaleX', [1, 1.4, 0.8])]), [performance()]);
  // Fractional frames also verify continuous poses between rendered samples.
  for (let frame = 0; frame <= 120; frame += 0.25) for (const {matrix, shape} of rigPictureAtFrame(prepared, frame)) {
    const stroke = shape.strokeWidth / 2;
    for (const x of [shape.x - stroke, shape.x + shape.width + stroke]) {
      for (const y of [shape.y - stroke, shape.y + shape.height + stroke]) {
        assert.ok(Math.abs(matrix[0] * x + matrix[2] * y + matrix[4]) <= prepared.extents[0] + 1e-7);
        assert.ok(Math.abs(matrix[1] * x + matrix[3] * y + matrix[5]) <= prepared.extents[1] + 1e-7);
        const px = matrix[0] * x + matrix[2] * y + matrix[4];
        const py = matrix[1] * x + matrix[3] * y + matrix[5];
        assert.ok(px >= prepared.bounds.left - 1e-7 && px <= prepared.bounds.right + 1e-7);
        assert.ok(py >= prepared.bounds.top - 1e-7 && py <= prepared.bounds.bottom + 1e-7);
      }
    }
  }
});

test('tighter framing cannot bypass the original conservative size validation', () => {
  const source = rig([part('blade', {x: 256, shapes: [rect({x: 0, y: 0, width: 512, height: 512})]})],
    [track('blade', 'rotation', [0, 1])]);
  // Actual x/y remain below 800, but the original full-circle safety envelope exceeds 800.
  assert.throws(() => prepareRig(source, [performance()]), /envelope exceeds 800/);
});

test('custom framing fits the whole shared trajectory once and retains safe label and drawing margins', () => {
  const definition = rig([part('blade', {shapes: [rect({x: -30, y: -10, width: 60, height: 20})]})],
    [track('blade', 'rotation', [0, 12, -5, 0])]);
  const first = scene('rest', 0, visual(definition, {entities: [entity({x: 40, y: 60, label: 'Subject'})]}));
  const second = scene('depart', 120, visual(definition, {entities: [entity({x: 40, y: 60, label: 'Subject'})],
    performances: [performance(120)], paths: [{id: 'flight', points: [{x: 40, y: 60}, {x: 60, y: 40}, {x: 82, y: 15}],
      curved: true, closed: false, color: 'muted'}], actions: [{entityId: 'plant', kind: 'follow-path',
      startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, pathId: 'flight', x: 0, y: 0, value: 0,
      easing: 'ease-in-out', from: 120, durationInFrames: 120}]}));
  const original = JSON.stringify([first, second]);
  for (const sketch of [false, true]) {
    const plans = processPresentations([first, second], sketch);
    const plan = plans.get('rest');
    assert.equal(plan.viewport, plans.get('depart').viewport);
    assert.equal(plan.labelSlots, plans.get('depart').labelSlots);
    assert.ok(plan.viewport.width < 1200, 'blank authored margins are removed');
    assert.ok(plan.viewport.width >= 720 && plan.viewport.height >= 320, 'minimum view prevents excessive zoom');
    for (const shot of [first, second]) {
      const program = compileMotion(shot.visual);
      for (let frame = shot.from; frame <= shot.from + shot.durationInFrames; frame += 2) {
        const actors = program.entities.map((prepared) => ({prepared, state: entityAtFrame(prepared, frame)}));
        for (const {prepared, state} of actors) {
          const at = toStage(state);
          const extent = entityHalfExtents(prepared.entity.kind, state.size, state.rotation,
            sketch ? 'sketch' : 'vector', prepared.rigExtents);
          inside({left: at.x - extent.x, right: at.x + extent.x, top: at.y - extent.y, bottom: at.y + extent.y}, plan.viewport);
        }
        for (const label of placeActorLabels(actors, plan.viewport, plan.labelSlots)) inside(label.bounds, plan.viewport, 'label');
      }
    }
  }
  assert.equal(JSON.stringify([first, second]), original);
});

test('stock-only and process scene framing preserve their existing exact results', () => {
  const drawing = {title: 'Original', entities: [entity({kind: 'person', rigId: undefined, label: 'Customer'})], paths: [], actions: []};
  const original = scene('stock', 0, drawing);
  const program = compileMotion(drawing);
  for (const look of ['vector', 'sketch']) {
    assert.deepEqual(fitAuthoredMotionViewport(program, {look}), fitMotionViewport(program, {look}));
    const generic = processPresentations([original], look === 'sketch').get('stock');
    assert.deepEqual(generic.viewport, fitMotionViewport(program, {look}));
    const process = {...original, processTrace: {sourceTemplate: 'process', actorIds: ['plant'], stationEntityIds: [],
      initialQueue: ['plant'], initialService: [], finalQueue: ['plant'], finalService: [], completed: [], events: []}};
    assert.deepEqual(processPresentations([process], look === 'sketch').get('stock').viewport,
      fitProcessViewport([program], look === 'sketch', look));
  }
});

test('custom authored framing includes faint visible actors while legacy process visibility stays unchanged', () => {
  const definition = rig([part('blade', {shapes: [rect({x: -10, y: -10, width: 20, height: 20})]})],
    [track('blade', 'rotation', [0, 0])]);
  const program = compileMotion(visual(definition, {entities: [entity({x: 50}),
    entity({id: 'faint', x: 0, opacity: 0.04})]}));
  const framed = fitAuthoredMotionViewport(program);
  assert.ok(framed.x <= -13, 'the visible four-percent-opacity actor remains inside the frame');
  const legacyContentFit = fitMotionViewport(program, {fitContent: true});
  assert.ok(legacyContentFit.x > 0, 'default content fitting retains its established visibility cutoff');
});

test('small whole-object banking uses analytic custom bounds while full rotations and stock framing stay conservative', () => {
  const dimensions = [200, 10];
  const small = rotatedRigExtents(dimensions, [0, 5]);
  assert.ok(Math.abs(small.x - Math.hypot(...dimensions)) < 1e-9, 'includes the maximum between zero and five degrees');
  assert.ok(Math.abs(small.y - (200 * Math.sin(5 * Math.PI / 180) + 10 * Math.cos(5 * Math.PI / 180))) < 1e-9);
  const full = rotatedRigExtents(dimensions, [0, 360]);
  assert.ok(Math.abs(full.x - full.y) < 1e-9 && full.y > 200);
  const definition = rig([part('blade', {shapes: [rect({x: -200, y: -10, width: 400, height: 20})]})],
    [track('blade', 'rotation', [0, 0])]);
  const make = (degrees, custom = true) => compileMotion(visual(definition, {
    entities: [entity({kind: custom ? 'custom' : 'box', label: 'Wing'})],
    actions: [{entityId: 'plant', kind: 'rotate', from: 0, durationInFrames: 120, startLine: 0, endLine: 0,
      startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0, value: degrees, easing: 'ease-in-out'},
    {entityId: 'plant', kind: 'scale', from: 0, durationInFrames: 120, startLine: 0, endLine: 0,
      startOffset: 0, endOffset: 1, pathId: '', x: 0, y: 0, value: 2, easing: 'ease-in-out'}],
  }));
  const banking = make(5); const spinning = make(360);
  const closeCamera = fitAuthoredMotionViewport(banking);
  assert.equal(closeCamera.height, 320, 'five-degree banking should not manufacture a full-circle footprint');
  assert.ok(fitAuthoredMotionViewport(spinning).height > 800);
  const slots = planLabelSlots([{program: banking, frames: [0, 60, 120]}], undefined, {viewport: closeCamera});
  assert.ok(slots.layouts.get('plant').halfHeight < 65, 'labels use the same restricted rotation envelope');
  for (let frame = 0; frame <= 120; frame++) {
    const prepared = banking.entities[0]; const state = entityAtFrame(prepared, frame); const origin = toStage(state);
    const extent = entityHalfExtents('custom', state.size, state.rotation, 'vector', prepared.rigExtents);
    inside({left: origin.x - extent.x, right: origin.x + extent.x,
      top: origin.y - extent.y, bottom: origin.y + extent.y}, closeCamera);
  }
  assert.deepEqual(fitAuthoredMotionViewport(make(5, false)), fitAuthoredMotionViewport(make(360, false)),
    'stock actors keep their previous full-circle rotation envelope');
});

test('asymmetric custom framing retains directional bounds through translation, scaling, labels and complete turns', () => {
  const definition = rig([part('rod', {shapes: [rect({x: 80, y: 0, width: 20, height: 240})]})],
    [track('rod', 'rotation', [0, 0])]);
  const actions = ['move', 'scale', 'rotate'].map((kind) => ({entityId: 'plant', kind,
    from: 0, durationInFrames: 120, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
    pathId: '', x: 55, y: 65, value: kind === 'scale' ? 0.4 : 5, easing: 'ease-in-out'}));
  const program = compileMotion(visual(definition, {entities: [entity({x: 45, y: 25, size: 1.8, label: 'Arm'})], actions}));
  const prepared = program.entities[0];
  assert.deepEqual(prepared.rig.bounds, {left: 80, right: 100, top: 0, bottom: 240});
  const complete = transformedRigBounds(prepared.rig.bounds, [0.4, 1.8], [0, 5]);
  assert.ok(complete.left < 32, 'the smaller scale brings the offset object closer to its origin');
  const view = fitAuthoredMotionViewport(program);
  assert.ok(view.height < 850, 'do not reserve the absent mirrored rod above the pivot');
  const slots = planLabelSlots([{program, frames: [0, 30, 60, 90, 120]}], [1], {viewport: view});
  assert.equal(slots.layouts.get('plant').bounds.top, complete.top);
  const relativeLabelY = new Set();
  for (let frame = 0; frame <= 120; frame += 0.25) {
    const state = entityAtFrame(prepared, frame); const origin = toStage(state);
    const bounds = transformedRigBounds(prepared.rig.bounds, [state.size, state.size], [state.rotation, state.rotation]);
    inside({left: origin.x + bounds.left, right: origin.x + bounds.right,
      top: origin.y + bounds.top, bottom: origin.y + bounds.bottom}, view, 'directional body');
    for (const label of placeActorLabels([{prepared, state}], view, slots)) {
      inside(label.bounds, view, 'directional label');
      relativeLabelY.add((label.y - origin.y).toFixed(8));
    }
  }
  assert.equal(relativeLabelY.size, 1, 'label anchors remain fixed throughout the entire performance');
  const spun = transformedRigBounds(prepared.rig.bounds, [0.4, 1.8], [-180, 180]);
  const radius = Math.hypot(100, 240) * 1.8 + 5.4;
  for (const edge of Object.values(spun)) assert.ok(Math.abs(Math.abs(edge) - radius) < 1e-8);
});
