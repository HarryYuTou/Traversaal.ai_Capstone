// Reproducible visual acceptance sample; it uses production rendering and no planning/TTS APIs.
// Usage (from renderer): node scripts/quality-preview.mjs <new output directory> [vector|sketch]
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const [destination, look = 'vector'] = process.argv.slice(2);
if (!destination || !['vector', 'sketch'].includes(look)) {
  throw new Error('Usage: node scripts/quality-preview.mjs <new output directory> [vector|sketch]');
}
const output = path.resolve(destination);
await fs.mkdir(output, {recursive: true});
const video = path.join(output, `quality-${look}.mp4`);
try { await fs.access(video); throw new Error(`Preview already exists: ${video}`); }
catch (error) { if (error.code !== 'ENOENT') throw error; }

const entity = (id, kind, x, y, extra = {}) => ({id, kind, x, y, size: 1.6, rotation: 0,
  opacity: 1, value: 0, color: 'accent', label: '', ...extra});
const action = (entityId, kind, from, durationInFrames, extra = {}) => ({entityId, kind, from,
  durationInFrames, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
  pathId: '', x: 0, y: 0, value: 0, easing: 'ease-in-out', ...extra});
let cursor = 45;
const scenes = [];
const scene = (id, title, duration, entities, actions, activities = [], paths = []) => {
  scenes.push({id, template: 'motion', chapterId: null, from: cursor, durationInFrames: duration,
    lines: [], visual: {title, entities, paths,
      actions: actions.map((item) => ({...item, from: item.from + cursor})),
      activities: activities.map((item) => ({...item, from: item.from + cursor}))}});
  cursor += duration;
};
scene('human', 'Look, walk, work, acknowledge, return', 270,
  [entity('guide', 'person', 25, 62, {size: 2}), entity('destination', 'marker', 76, 62,
    {size: 1, color: 'secondary', label: 'Destination'})],
  [action('guide', 'move', 30, 60, {x: 62, y: 62, easing: 'walk'}),
    action('guide', 'move', 200, 50, {x: 25, y: 62, easing: 'walk'})],
  [{entityId: 'guide', kind: 'work', from: 105, durationInFrames: 60},
    {entityId: 'guide', kind: 'complete', from: 165, durationInFrames: 18}]);
scene('parcels', 'A parcel reaches a workbench', 180,
  [entity('parcel', 'box', 20, 60, {label: 'Parcel'}),
    entity('bench', 'workbench', 76, 60, {color: 'secondary', label: 'Workbench'})],
  [action('parcel', 'move', 20, 60, {x: 57, y: 60}),
    action('parcel', 'move', 150, 25, {x: 90, y: 30})],
  ['parcel', 'bench'].flatMap((entityId) => [
    {entityId, kind: 'work', from: 80, durationInFrames: 60},
    {entityId, kind: 'complete', from: 140, durationInFrames: 10}]));
scene('network', 'Messages follow separate curved routes', 180,
  [entity('receiver', 'server', 82, 55, {color: 'secondary', label: 'Receiver'}),
    entity('message-a', 'packet', 16, 28, {size: 1.2, label: 'A'}),
    entity('message-b', 'packet', 16, 78, {size: 1.2, color: 'secondary', label: 'B'})],
  [action('message-a', 'follow-path', 20, 110, {pathId: 'route-a'}),
    action('message-b', 'follow-path', 35, 95, {pathId: 'route-b'})],
  [{entityId: 'receiver', kind: 'work', from: 130, durationInFrames: 25},
    {entityId: 'receiver', kind: 'complete', from: 155, durationInFrames: 12}],
  [{id: 'route-a', points: [{x: 45, y: 22}, {x: 67, y: 45}], curved: true, closed: false, color: 'accent'},
    {id: 'route-b', points: [{x: 45, y: 83}, {x: 67, y: 65}], curved: true, closed: false, color: 'secondary'}]);
scene('orbit', 'An orbit keeps its authored geometry', 180,
  [entity('world', 'planet', 50, 50, {size: 1.2, color: 'secondary', label: 'Planet'}),
    entity('orbiter', 'satellite', 72, 50, {size: 0.8, label: 'Satellite'})],
  [action('orbiter', 'orbit', 15, 150, {x: 50, y: 50, value: 360, easing: 'linear'}),
    action('orbiter', 'rotate', 15, 150, {value: 360, easing: 'linear'})]);

const inputProps = {schemaVersion: '1', projectId: 'renderer-quality-preview', title: 'Reusable motion quality',
  width: 1920, height: 1080, fps: 30, durationInFrames: cursor, titleFrames: 45,
  look, audio: {path: '', sampleRate: 48000, channels: 1}, chapters: [], scenes};
await fs.writeFile(path.join(output, 'timeline.json'), `${JSON.stringify(inputProps, null, 2)}\n`);
const serveUrl = await bundle({entryPoint: path.resolve('src/index.ts')});
const composition = await selectComposition({serveUrl, id: 'Explainer', inputProps});
let reported = -1;
await renderMedia({composition, serveUrl, inputProps, codec: 'h264', outputLocation: video,
  scale: 2 / 3, crf: 20, concurrency: 2, muted: true,
  onProgress: ({progress}) => {
    const bucket = Math.floor(progress * 10);
    if (bucket !== reported) { reported = bucket; console.log(`Rendering ${look}: ${bucket * 10}%`); }
  }});
for (const shot of scenes) {
  await renderStill({composition, serveUrl, inputProps, frame: shot.from + 65, scale: 0.5,
    output: path.join(output, `${shot.id}.png`)});
}
console.log(video);
