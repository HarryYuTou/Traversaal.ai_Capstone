// Render a few frames of a timeline as PNG files, for checking layouts without rendering a whole video.
// Usage: node scripts/stills.mjs <run>/video/timeline.json <output folder> <frame> [<frame> ...]
import fs from 'node:fs';
import path from 'node:path';
import {bundle} from '@remotion/bundler';
import {renderStill, selectComposition} from '@remotion/renderer';

const [timelinePath, outDir, ...frames] = process.argv.slice(2);
if (!timelinePath || !outDir || frames.length === 0) {
  console.error('Usage: node scripts/stills.mjs <timeline.json> <output folder> <frame> [<frame> ...]');
  process.exit(1);
}
const inputProps = JSON.parse(fs.readFileSync(timelinePath, 'utf8'));
const serveUrl = await bundle({
  entryPoint: path.resolve('src/index.ts'),
  publicDir: path.dirname(path.resolve(timelinePath)),
});
const composition = await selectComposition({serveUrl, id: 'Explainer', inputProps});
fs.mkdirSync(outDir, {recursive: true});
for (const frame of frames) {
  const output = path.join(outDir, `frame-${String(frame).padStart(5, '0')}.png`);
  await renderStill({composition, serveUrl, inputProps, frame: Number(frame), output, scale: 0.5});
  console.log(output);
}
