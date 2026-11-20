import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/fullVideoContract.ts', import.meta.url), 'utf8');
const {outputText} = ts.transpileModule(source, {compilerOptions: {
  module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022,
}});
const {fullVideoScenes} = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);
const scene = (id, from, frames) => ({id, from, durationInFrames: frames, template: 'generated-video',
  lines: [], visual: {title: id, clips: [{path: `generated/${id}.mp4`, from: 0, durationInFrames: frames}]}});
const timeline = () => ({visualMode: 'seedance-full', titleFrames: 0, chapters: [], width: 854, height: 480,
  durationInFrames: 240, scenes: [scene('one', 0, 120), scene('two', 120, 120)]});

test('full video has exactly one generated clip at every frame, including both ends and cuts', () => {
  for (const [width, height] of [[854, 480], [1280, 720]]) {
    const input = {...timeline(), width, height};
    const scenes = fullVideoScenes(input);
    for (let frame = 0; frame < input.durationInFrames; frame++) {
      const visible = scenes.flatMap((s) => s.visual.clips.filter((c) =>
        frame >= s.from + c.from && frame < s.from + c.from + c.durationInFrames));
      assert.equal(visible.length, 1, `frame ${frame}`);
    }
  }
});

test('cards, uncovered frames, short clips and animation fallback are rejected', () => {
  const variants = [
    (t) => {t.titleFrames = 60;},
    (t) => {t.chapters = [{from: 0, cardFrames: 45}];},
    (t) => {t.scenes[0].template = 'concept';},
    (t) => {t.scenes[0].from = 1;},
    (t) => {t.scenes[1].from = 119;},
    (t) => {t.scenes[1].visual.clips[0].durationInFrames = 119;},
    (t) => {t.durationInFrames = 241;},
    (t) => {t.width = 1920; t.height = 1080;},
  ];
  for (const change of variants) {
    const input = timeline();
    change(input);
    assert.throws(() => fullVideoScenes(input));
  }
});
