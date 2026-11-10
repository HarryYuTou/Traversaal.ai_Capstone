// Hand-authored contract acceptance fixture, compiled by the production Python timeline.
// Synthetic timing only: this does not call a planner, TTS, image or video generation API.
// From renderer: node scripts/custom-rig-preview.mjs <new output directory> [vector|sketch] [--timeline-only]
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
  throw new Error('Usage: node scripts/custom-rig-preview.mjs <new output directory> [vector|sketch] [--timeline-only]');
}
const rendererRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = path.resolve(rendererRoot, '..');
const output = path.resolve(destination);
const timelinePath = path.join(output, 'timeline.json');
const video = path.join(output, `custom-rigs-${look}.mp4`);
for (const filename of [timelinePath, video]) {
  try { await fs.access(filename); throw new Error(`Refusing to replace existing output: ${filename}`); }
  catch (error) { if (error.code !== 'ENOENT') throw error; }
}

let python = process.env.CAPSTONE_PYTHON;
if (!python) {
  const localPython = path.join(repoRoot, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
  try { await fs.access(localPython); python = localPython; }
  catch { python = process.platform === 'win32' ? 'python' : 'python3'; }
}
const compiled = execFileSync(python, ['-c', `
import hashlib, json
from capstone_script.scene_plan import dump_plan, load_plan
from capstone_script.timeline import build_timeline
plan = load_plan('fixtures/scene-plan.custom-rigs.json')
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
  const performances = scene.visual.performances ?? [];
  const lastFrame = scene.from + scene.durationInFrames - 1;
  return [
    {id: `${scene.id}-rest`, frame: scene.from + 2},
    ...performances.flatMap((performance, index) => [0.14, 0.43, 0.74, 1].map((phase, sample) => ({
      id: `${scene.id}-clip-${index + 1}-pose-${sample + 1}`,
      frame: Math.min(lastFrame, performance.from + Math.round(performance.durationInFrames * phase)),
    }))),
    {id: `${scene.id}-held`, frame: lastFrame - 2},
  ];
});
await fs.mkdir(output, {recursive: true});
await fs.writeFile(timelinePath, `${JSON.stringify(inputProps, null, 2)}\n`);
await fs.writeFile(path.join(output, 'inspection-frames.json'), `${JSON.stringify(inspections, null, 2)}\n`);
await fs.writeFile(path.join(output, 'provenance.json'), `${JSON.stringify({
  fixture: 'fixtures/scene-plan.custom-rigs.json',
  source: 'Hand-authored acceptance fixture; not a live model output.',
  timing: 'Synthetic 3-second narration lines compiled by capstone_script.timeline.build_timeline.',
  audio: 'Silent; no narration recording or generated speech.',
  generatedByModel: false,
}, null, 2)}\n`);
if (timelineOnly) {
  console.log(timelinePath);
} else {
  const serveUrl = await bundle({entryPoint: path.join(rendererRoot, 'src/index.ts')});
  const composition = await selectComposition({serveUrl, id: 'Explainer', inputProps});
  let reported = -1;
  await renderMedia({composition, serveUrl, inputProps, codec: 'h264', outputLocation: video,
    scale: 2 / 3, crf: 20, concurrency: 2, muted: true,
    onProgress: ({progress}) => {
      const bucket = Math.floor(progress * 10);
      if (bucket !== reported) { reported = bucket; console.log(`Rendering custom rigs: ${bucket * 10}%`); }
    }});
  for (const {id, frame} of inspections) {
    await renderStill({composition, serveUrl, inputProps, frame, scale: 2 / 3,
      output: path.join(output, `${id}.png`)});
  }
  console.log(video);
}
