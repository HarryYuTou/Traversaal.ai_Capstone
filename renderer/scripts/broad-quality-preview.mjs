// Production-rendered visual acceptance scenes; no planner, TTS, or video-generation APIs.
// Usage (from renderer): node scripts/broad-quality-preview.mjs <new output directory> [vector|sketch] [--timeline-only] [--entry=<entry point>]
import fs from 'node:fs/promises';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const args = process.argv.slice(2);
const destination = args.find((arg) => !arg.startsWith('--'));
const look = args.filter((arg) => !arg.startsWith('--'))[1] ?? 'vector';
const timelineOnly = args.includes('--timeline-only');
const entryPoint = path.resolve(args.find((arg) => arg.startsWith('--entry='))?.slice(8) ?? 'src/index.ts');
if (!destination || !['vector', 'sketch'].includes(look)) {
  throw new Error('Usage: node scripts/broad-quality-preview.mjs <new output directory> [vector|sketch] [--timeline-only] [--entry=<entry point>]');
}
const output = path.resolve(destination);
await fs.mkdir(output, {recursive: true});
const video = path.join(output, `broad-quality-${look}.mp4`);
try { await fs.access(video); throw new Error(`Preview already exists: ${video}`); }
catch (error) { if (error.code !== 'ENOENT') throw error; }

const entity = (id, kind, x, y, extra = {}) => ({id, kind, x, y, size: 1.8,
  rotation: 0, opacity: 1, value: 0, color: 'accent', label: '', ...extra});
const action = (entityId, kind, from, durationInFrames, extra = {}) => ({entityId, kind, from,
  durationInFrames, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1,
  pathId: '', x: 0, y: 0, value: 0, easing: 'ease-in-out', ...extra});
const cue = (entityId, kind, from, durationInFrames, extra = {}) => ({entityId, kind, from,
  durationInFrames, startLine: 0, endLine: 0, startOffset: 0, endOffset: 1, ...extra});
const scenes = [];
const inspections = [];
let cursor = 30;
const scene = ({id, title, duration = 210, entities, actions = [], cues = [], activities = [], paths = [], shots = [90, 165]}) => {
  inspections.push(...shots.map((frame, index) => ({id: `${id}-${index + 1}`, frame: cursor + frame})));
  scenes.push({id, template: 'motion', chapterId: null, from: cursor, durationInFrames: duration,
    lines: [], visual: {title, entities, paths,
      actions: actions.map((item) => ({...item, from: item.from + cursor})),
      cues: cues.map((item) => ({...item, from: item.from + cursor})),
      activities: activities.map((item) => ({...item, from: item.from + cursor}))}});
  cursor += duration;
};

scene({id: 'pack', title: 'Close, seal, label',
  entities: [entity('parcel', 'box', 18, 54, {size: 2.3, label: 'Parcel'}),
    entity('packing-bench', 'workbench', 68, 62, {size: 2.4, color: 'secondary', label: 'Packing bench'})],
  actions: [action('parcel', 'move', 15, 45, {x: 49, y: 54}),
    action('parcel', 'move', 160, 38, {x: 18, y: 54})],
  cues: [cue('parcel', 'pack', 62, 88)],
  activities: [{entityId: 'packing-bench', kind: 'work', from: 62, durationInFrames: 88}],
  shots: [65, 107, 153, 190]});

const orbitPoints = Array.from({length: 16}, (_, i) => ({x: 50 + 24 * Math.cos(i * Math.PI / 8),
  y: 50 + 42 * Math.sin(i * Math.PI / 8)}));
scene({id: 'orbit', title: 'The Moon follows its orbit',
  entities: [entity('earth', 'planet', 50, 50, {size: 1.65, color: 'secondary', label: 'Earth'}),
    entity('moon', 'moon', 74, 50, {size: 0.7, color: 'muted', label: 'Moon'})],
  paths: [{id: 'lunar-orbit', points: orbitPoints, curved: true, closed: true, color: 'muted'}],
  actions: [action('moon', 'follow-path', 12, 186, {pathId: 'lunar-orbit', easing: 'linear'})],
  shots: [60, 125]});

scene({id: 'network', title: 'Send, receive, process',
  entities: [entity('client', 'laptop', 19, 55, {label: 'Client'}),
    entity('server', 'server', 79, 55, {color: 'secondary', label: 'Server'}),
    entity('request', 'packet', 29, 55, {size: 1, opacity: 0})],
  paths: [{id: 'request-route', points: [{x: 29, y: 55}, {x: 43, y: 32}, {x: 58, y: 32}, {x: 69, y: 55}],
    curved: true, closed: false, color: 'accent'}],
  actions: [action('request', 'opacity', 28, 6, {value: 1}),
    action('request', 'follow-path', 30, 65, {pathId: 'request-route', easing: 'linear'}),
    action('request', 'opacity', 95, 10, {value: 0})],
  cues: [cue('client', 'send', 24, 30), cue('server', 'receive', 95, 28),
    cue('server', 'compute', 125, 65)],
  shots: [45, 105, 155]});

scene({id: 'spacecraft', title: 'A short burn, then a quiet coast',
  entities: [entity('craft', 'spacecraft', 19, 54, {size: 2.3, label: 'Spacecraft'})],
  actions: [action('craft', 'move', 22, 165, {x: 79, y: 54, easing: 'linear'})],
  cues: [cue('craft', 'thrust', 22, 62)],
  shots: [57, 147]});

scene({id: 'value', title: 'An illustrative value change',
  entities: [entity('coin', 'coin', 19, 59, {size: 1.6, label: 'Transfer'}),
    entity('destination', 'marker', 52, 62, {size: 1.15, color: 'secondary'}),
    entity('balance', 'gauge', 78, 54, {size: 1.9, value: 0.15, color: 'secondary', label: 'Example value'})],
  actions: [action('coin', 'move', 20, 85, {x: 48, y: 59}),
    action('coin', 'rotate', 20, 85, {value: 360}),
    action('coin', 'opacity', 105, 12, {value: 0}),
    action('balance', 'value', 108, 70, {value: 0.8})],
  shots: [55, 145]});

const inputProps = {schemaVersion: '1', projectId: 'broad-motion-quality-preview', title: 'Actions beyond characters',
  width: 1920, height: 1080, fps: 30, durationInFrames: cursor, titleFrames: 30,
  look, theme: 'light', audio: {path: '', sampleRate: 48000, channels: 1}, chapters: [], scenes};
await fs.writeFile(path.join(output, 'timeline.json'), `${JSON.stringify(inputProps, null, 2)}\n`);
await fs.writeFile(path.join(output, 'inspection-frames.json'), `${JSON.stringify(inspections, null, 2)}\n`);
if (!timelineOnly) {
  const serveUrl = await bundle({entryPoint});
  const composition = await selectComposition({serveUrl, id: 'Explainer', inputProps});
  let reported = -1;
  await renderMedia({composition, serveUrl, inputProps, codec: 'h264', outputLocation: video,
    scale: 2 / 3, crf: 20, concurrency: 2, muted: true,
    onProgress: ({progress}) => {
      const bucket = Math.floor(progress * 10);
      if (bucket !== reported) { reported = bucket; console.log(`Rendering ${look}: ${bucket * 10}%`); }
    }});
  for (const {id, frame} of inspections) {
    await renderStill({composition, serveUrl, inputProps, frame, scale: 2 / 3,
      output: path.join(output, `${id}.png`)});
  }
  console.log(video);
} else console.log(path.join(output, 'timeline.json'));
