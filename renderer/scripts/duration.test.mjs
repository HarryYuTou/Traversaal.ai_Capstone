import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';
const source = await readFile(new URL('../src/duration.ts', import.meta.url), 'utf8');
const {outputText} = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.ESNext}});
const {timelineLengthText} = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

test('short samples do not round up to a minute; chapter counts and longer duration labels are retained', () => {
  const label = (seconds, chapters = []) => timelineLengthText({durationInFrames: seconds * 30, fps: 30, chapters});
  assert.equal(label(34.24), 'under a minute');
  assert.equal(label(59.99), 'under a minute');
  assert.equal(label(60), 'about 1 minute');
  assert.equal(label(434), 'about 7 minutes');
  assert.equal(label(434, [{}, {}]), '2 chapters · about 7 minutes');
});
