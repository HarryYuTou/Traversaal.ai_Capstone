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
    if (match[2] === 'react-peeps') dependency = `data:text/javascript;base64,${Buffer.from(
      `import pkg from '${dependency}'; export default pkg.default ?? pkg;`).toString('base64')}`;
    outputText = outputText.replace(match[0], `from '${dependency}'`);
  }
  const url = `data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`;
  urls.set(file.href, url);
  return url;
};
const load = async (name, extension = '.ts') => import(await moduleUrl(new URL(`../src/motion/${name}${extension}`, import.meta.url)));
const {Illustration} = await load('Illustration', '.tsx');
const {compileMotion, entityAtFrame} = await load('engine');
const {illustrationPoseAtFrame} = await load('pose');
const {objectPerformanceAtFrame} = await load('objectPerformance');
const {ENTITY_EXTENTS} = await load('metrics');
const palette = {ink: '#182c3c', accent: '#dd8452', secondary: '#77a194', muted: '#737b81',
  paper: '#fffaf0', soft: '#ece6db', line: '#ced0cd'};
const render = (kind, look, frame, {activities = [], cues = [], station, packingState} = {}) => {
  const entity = {id: 'subject', kind, x: 50, y: 50, size: 1, rotation: 0, opacity: 1,
    value: 0.5, color: 'accent', label: '', ...(packingState ? {packingState} : {})};
  const prepared = compileMotion({title: 'Object rendering', entities: [entity], actions: [], paths: [],
    activities: activities.map((activity) => ({entityId: entity.id, ...activity})),
    cues: cues.map((cue) => ({entityId: entity.id, ...cue})),
  }).entities[0];
  return renderToStaticMarkup(React.createElement('svg', null, React.createElement(Illustration, {
    entity, look, station, prefix: 'regression', palette, state: entityAtFrame(prepared, frame),
    pose: illustrationPoseAtFrame(prepared, frame), objectPose: objectPerformanceAtFrame(prepared, frame),
  })));
};
const complete = [{kind: 'complete', from: 30, durationInFrames: 18}];

test('every nonhuman legacy activity still draws one completion acknowledgement in both looks', () => {
  for (const look of ['vector', 'sketch']) {
    for (const kind of Object.keys(ENTITY_EXTENTS).filter((kind) => kind !== 'person')) {
      const completed = render(kind, look, 35, {activities: complete});
      const marks = [...completed.matchAll(/data-(?:motion-activity="complete"|object-part="completed")/g)];
      assert.equal(marks.length, 1, `${kind}/${look} must visibly acknowledge completion exactly once`);
      assert.doesNotMatch(render(kind, look, 29, {activities: complete}),
        /data-(?:motion-activity="complete"|object-part="completed")/,
        `${kind}/${look} cannot acknowledge before the event`);
      assert.doesNotMatch(render(kind, look, 48, {activities: complete}),
        /data-(?:motion-activity="complete"|object-part="completed")/,
        `${kind}/${look} must clear the transient acknowledgement after the interval`);
    }
  }
});

test('a server station completion sits above the opaque open/closed status panel', () => {
  for (const look of ['vector', 'sketch']) {
    for (const open of [true, false]) {
      const markup = render('server', look, 35, {activities: complete,
        station: {open, openingProgress: 0}});
      const completion = markup.match(/<g[^>]*data-object-part="completed"[^>]*>/)?.[0];
      assert.ok(completion, 'the server has a drawn completion group');
      const position = completion.match(/transform="translate\(([-.\d]+) ([-.\d]+)\)"/);
      assert.ok(position, 'the completion is anchored to a visible hardware row');
      const y = Number(position[2]);
      assert.ok(y + 8 + 1.5 < 12, `completion's circle and stroke must not enter panel y=12..37: y=${y}`);
      assert.match(markup, /data-station-state="(?:open|closed)"/);
    }
  }
});

test('rocket and spacecraft exhaust is drawn only during an explicit burn, never baked into coasting art', () => {
  for (const look of ['vector', 'sketch']) {
    for (const kind of ['rocket', 'spacecraft', 'lander', 'lander-ascent', 'satellite']) {
      const cues = [{kind: 'thrust', from: 30, durationInFrames: 60}];
      for (const frame of [0, 30, 90, 100]) {
        assert.doesNotMatch(render(kind, look, frame, {cues}), /data-object-part="thrust"/,
          `${kind}/${look} must coast without a plume outside the burn envelope`);
      }
      assert.match(render(kind, look, 45, {cues}), /data-object-part="thrust"/);
      const coast = render(kind, look, 45);
      assert.doesNotMatch(coast, /data-object-part="thrust"/);
      assert.doesNotMatch(coast, /M-8 40 0 59 8 40|M-15 38-23 60 0 52 23 60 15 38/,
        'the old permanent rocket flame silhouettes cannot survive underneath the cue layer');
    }
  }
});

test('waiting, prepared and sealed parcels preserve their drawn parts when a later shot adds packing cues', () => {
  for (const look of ['vector', 'sketch']) {
    const futurePack = [{kind: 'pack', from: 300, durationInFrames: 90}];
    const waiting = render('box', look, 20, {packingState: 'open'});
    assert.match(waiting, /data-object-part="packing-box"/);
    assert.equal(waiting, render('box', look, 20, {packingState: 'open', cues: futurePack}),
      'a waiting actor must not switch between sealed art and open flaps at the scene cut');
    const prepared = render('box', look, 20, {packingState: 'prepared'});
    assert.equal(prepared, render('box', look, 20, {packingState: 'prepared',
      cues: [{...futurePack[0], continued: true}]}),
    'a carried service state must retain its already closed flaps before sealing resumes');
    const sealed = render('box', look, 20, {packingState: 'sealed'});
    assert.equal(sealed, render('box', look, 340, {packingState: 'sealed', cues: futurePack}),
      'a previously sealed package cannot reopen when a later cue is added');
    assert.notEqual(waiting, prepared);
    assert.notEqual(prepared, sealed);
    assert.doesNotMatch(render('box', look, 20), /data-object-part="packing-box"/,
      'legacy boxes with no packing state or cue retain their existing illustration');
  }
});
