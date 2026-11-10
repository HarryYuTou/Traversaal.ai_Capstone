// Authored spatial-and-acting acceptance fixture, not a live model-generated plan.
// Production compiler + synthetic timings; no planner, TTS, image or video generation APIs.
// From renderer: node scripts/spatial-quality-preview.mjs <new output directory> [vector|sketch] [--timeline-only]
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {bundle} from '@remotion/bundler';
import {renderMedia, renderStill, selectComposition} from '@remotion/renderer';

const args = process.argv.slice(2);
const positionals = args.filter((arg) => !arg.startsWith('--'));
const [destination, look = 'vector'] = positionals;
const timelineOnly = args.includes('--timeline-only');
if (!destination || !['vector', 'sketch'].includes(look) || positionals.length > 2
  || args.some((arg) => arg.startsWith('--') && arg !== '--timeline-only')) {
  throw new Error('Usage: node scripts/spatial-quality-preview.mjs <new output directory> [vector|sketch] [--timeline-only]');
}
const rendererRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(rendererRoot, '..');
const output = path.resolve(destination);
const timelinePath = path.join(output, 'timeline.json');
const videoName = `spatial-quality-${look}.mp4`;
for (const filename of [timelinePath, path.join(output, videoName)]) {
  try { await fs.access(filename); throw new Error(`Refusing to replace existing output: ${filename}`); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
}
let python = process.env.CAPSTONE_PYTHON;
if (!python) {
  const local = path.join(repoRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  try { await fs.access(local); python = local; }
  catch { python = process.platform === 'win32' ? 'python' : 'python3'; }
}
const compiled = execFileSync(python, ['-c', `
import hashlib, json
from capstone_script.scene_plan import dump_plan, load_plan
from capstone_script.timeline import build_timeline
plan = load_plan('fixtures/scene-plan.spatial-quality.json')
manifest = {
    'status': 'completed', 'sampleRate': 48000,
    'planSha256': hashlib.sha256(dump_plan(plan).encode('utf-8')).hexdigest(),
    'blocks': [{'narrationId': line.id, 'sampleRate': 48000, 'channels': 1,
                'sampleCount': 144000, 'audioPath': ''}
               for scene in plan.scenes for line in scene.narration]
}
timeline = build_timeline(plan, manifest)
timeline['audio']['path'] = ''
print(json.dumps(timeline))
`], {cwd: repoRoot, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024});
const inputProps = {...JSON.parse(compiled), look, theme: 'light'};
const inspections = inputProps.scenes.flatMap((scene) => {
  const last = scene.from + scene.durationInFrames - 1;
  const shot = (id, frame) => ({id: `${scene.id}-${id}`, frame: Math.max(scene.from, Math.min(last, Math.round(frame)))});
  return [
    shot('initial', scene.from + 2),
    ...(scene.visual.contacts ?? []).flatMap((contact, i) => {
      const acquired = contact.from + contact.approachFrames;
      const release = contact.from + contact.durationInFrames;
      return [shot(`contact-${i + 1}-begin`, contact.from),
        shot(`contact-${i + 1}-acquiring`, (contact.from + acquired) / 2),
        shot(`contact-${i + 1}-acquired`, acquired),
        shot(`contact-${i + 1}-held`, (acquired + release) / 2),
        shot(`contact-${i + 1}-before-release`, release - 1),
        shot(`contact-${i + 1}-release`, release),
        shot(`contact-${i + 1}-after-release`, release + 1)];
    }),
    ...(scene.visual.actions ?? []).filter((action) => action.kind === 'move').map((action, i) =>
      shot(`travel-${i + 1}-middle`, action.from + action.durationInFrames * 0.5)),
    ...(scene.visual.performances ?? []).flatMap((performance, i) => {
      const entity = scene.visual.entities.find((item) => item.id === performance.entityId);
      const rig = scene.visual.rigs.find((item) => item.id === entity.rigId);
      const clip = rig.clips.find((item) => item.id === performance.clipId);
      const phases = [...new Set(clip.tracks.flatMap((track) => track.keyframes.map((key) => key.at)))].sort((a, b) => a - b);
      const cycle = performance.durationInFrames / performance.repeat;
      return [...phases.map((phase, key) => shot(`performance-${i + 1}-key-${key + 1}`,
        performance.from + cycle * phase)),
      shot(`performance-${i + 1}-middle`, performance.from + performance.durationInFrames * 0.5),
      shot(`performance-${i + 1}-held`, performance.from + performance.durationInFrames)];
    }),
    shot('final', last - 2),
  ];
});
const expected = {
  units: 'Physical SVG stage units (1200 by 500), before camera fitting.',
  purpose: 'Authored checkpoints for spatial acceptance; these values are not an executed contact audit.',
  scenes: [
    {sceneId: 'scene-01', source: 'presenter:left-foot@(0,6)', target: 'platform:surface@(-12,0)',
      initialAnchor: [570, 400], check: 'Keep the foot anchor fixed during the restrained leg scale change.'},
    {sceneId: 'scene-02', source: 'sample:body@(0,0)', target: 'gripper:grip-point@(0,0)',
      acquiredAnchor: [600, 375], sampleBottomBeforeLift: 415, pedestalTop: 415,
      closedJawInnerFaces: [-16, 16], sampleLocalSides: [-16, 16],
      jawBottomInGripperUnits: 70, sampleBottomInGripperUnits: 71,
      check: 'Align, close and pause; lift vertically clear of the pedestal before carrying sideways. Jaw tips have one local unit of clearance.'},
    {sceneId: 'scene-03', source: 'butterfly:feet@(0,3)', target: 'leaf:blade@(0,-6)',
      initialAnchor: [600, 315], heldCorrectionAtRelease: [54, -10],
      check: 'Preserve the nonzero correction at release; the first free-flight frame must not reset to the old root.'},
  ],
};
const provenance = {
  fixture: 'fixtures/scene-plan.spatial-quality.json',
  phase: 'Phase 3: articulated acting after the spatial contact baseline passed its numerical and visual gate.',
  source: 'Hand-authored acceptance fixture; not a live model output.',
  timing: 'Synthetic three-second narration lines compiled by capstone_script.timeline.build_timeline.',
  audio: 'Silent; no narration recording or generated speech.',
  generatedByModel: false,
  status: timelineOnly ? 'timeline-only' : 'rendering',
};
await fs.mkdir(output, {recursive: true});
const writeJson = (filename, value) => fs.writeFile(path.join(output, filename), `${JSON.stringify(value, null, 2)}\n`);
await writeJson('timeline.json', inputProps);
await writeJson('inspection-frames.json', inspections);
await writeJson('spatial-checkpoints.json', expected);
await writeJson('provenance.json', provenance);
if (timelineOnly) {
  console.log(timelinePath);
} else {
  // Keep incomplete media separate; publish the finished preview and frames only after all renders succeed.
  const staging = path.join(output, 'staging');
  await fs.mkdir(staging, {recursive: false});
  const serveUrl = await bundle({entryPoint: path.join(rendererRoot, 'src/index.ts')});
  const composition = await selectComposition({serveUrl, id: 'Explainer', inputProps});
  let reported = -1;
  await renderMedia({composition, serveUrl, inputProps, codec: 'h264', outputLocation: path.join(staging, videoName),
    scale: 2 / 3, crf: 20, concurrency: 2, muted: true,
    onProgress: ({progress}) => {
      const bucket = Math.floor(progress * 10);
      if (bucket !== reported) { reported = bucket; console.log(`Rendering spatial and acting acceptance: ${bucket * 10}%`); }
    }});
  const renderedFrames = new Map();
  for (const {id, frame} of inspections) {
    const output = path.join(staging, `${id}.png`);
    if (renderedFrames.has(frame)) {
      await fs.copyFile(renderedFrames.get(frame), output);
    } else {
      await renderStill({composition, serveUrl, inputProps, frame, scale: 2 / 3, output});
      renderedFrames.set(frame, output);
    }
  }
  for (const filename of [videoName, ...inspections.map(({id}) => `${id}.png`)]) {
    await fs.rename(path.join(staging, filename), path.join(output, filename));
  }
  await fs.rmdir(staging);
  await writeJson('provenance.json', {...provenance, status: 'completed'});
  console.log(path.join(output, videoName));
}
