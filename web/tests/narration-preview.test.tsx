import { afterEach, expect, it, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const template = readFileSync(resolve(process.cwd(), '../capstone_script/preview.html'), 'utf8');

const preview = {
  plan: { title: 'A network story', scenes: [
    { id: 'motion-scene', template: 'motion', visual: { title: 'Across the network' }, narration: [
      { id: 'one', text: 'Send the message.' }, { id: 'two', text: 'The reply arrives.' },
    ] },
    { id: 'concept-scene', template: 'concept', visual: { title: 'Remember', statement: 'Packets carry messages.', points: ['Small pieces'] }, narration: [
      { id: 'three', text: 'Small pieces arrive.', highlightPointIndex: 0 },
    ] },
  ] },
  blocks: [
    { sceneId: 'motion-scene', narrationId: 'one', text: 'Send the message.', previewStartSeconds: 0.2, durationSeconds: 2 },
    { sceneId: 'motion-scene', narrationId: 'two', text: 'The reply arrives.', previewStartSeconds: 2.5, durationSeconds: 2 },
    { sceneId: 'concept-scene', narrationId: 'three', text: 'Small pieces arrive.', previewStartSeconds: 5, durationSeconds: 2 },
  ],
  audio: 'narration-preview.wav', lead: 0.2, tail: 0.3, speechSeconds: 6,
  motionBeats: { 'motion-scene': [
    { narrationId: 'one', description: 'Your message follows its route.' },
    { narrationId: 'two', description: 'The reply moves to a new position.' },
  ] },
  renderedVideos: [] as { href: string; label: string }[],
};

function openPreview(data = preview) {
  const html = template.replace('__PREVIEW_DATA__', JSON.stringify(data));
  const parsed = new DOMParser().parseFromString(html, 'text/html');
  document.body.innerHTML = parsed.body.innerHTML;
  const script = document.querySelector('script:not([id])')!.textContent!;
  // Execute the actual standalone preview against jsdom, without retaining resize listeners.
  new Function('window', script)({ addEventListener: vi.fn() });
  return document.querySelector('audio')!;
}

function seek(audio: HTMLAudioElement, seconds: number) {
  audio.currentTime = seconds;
  audio.dispatchEvent(new Event('seeked'));
}

afterEach(() => { document.body.replaceChildren(); });

it('labels motion as narration-only, describes every beat, and preserves traditional scenes', () => {
  const audio = openPreview();
  expect(document.querySelector('.template')!.textContent).toBe('Narration-only preview');
  expect(document.querySelector('.motion-note')!.textContent).toContain('does not show the animation');
  expect(document.querySelector('.motion-beat')!.textContent).toContain('Your message follows its route.');
  expect(document.querySelector('#render-links')!.textContent).toContain('Render the MP4');
  seek(audio, 3);
  expect(document.querySelector('.motion-beat')!.textContent).toContain('Planned beat 2 of 2');
  expect(document.querySelector('.motion-beat')!.textContent).toContain('The reply moves');
  expect(document.querySelector('#subtitle')!.textContent).toBe('The reply arrives.');
  seek(audio, 5.2);
  expect(document.querySelector('.statement')!.textContent).toBe('Packets carry messages.');
  expect(document.querySelector('.points .on')!.textContent).toBe('Small pieces');
  expect(document.querySelector('#slide')!.textContent).not.toContain('undefined');
});

it('offers the supplied rendered video link for inspecting actual motion', () => {
  openPreview({ ...preview, renderedVideos: [{ href: 'video.mp4', label: 'Watch rendered MP4' }] });
  expect(document.querySelector('#render-links a')!.getAttribute('href')).toBe('video.mp4');
  expect(document.querySelector('#render-links')!.textContent).not.toContain('Render the MP4');
});

it('shows semantic process scenes as narration previews with their supplied event descriptions', () => {
  const data = structuredClone(preview);
  data.plan.scenes[0].template = 'process';
  data.motionBeats['motion-scene'][0].description = 'A parcel begins processing at Packing.';
  const audio = openPreview(data);
  expect(document.querySelector('.template')!.textContent).toBe('Narration-only preview');
  expect(document.querySelector('.motion-beat')!.textContent).toContain('begins processing at Packing');
  seek(audio, 3);
  expect(document.querySelector('.motion-beat')!.textContent).toContain('Planned beat 2 of 2');
  expect(document.querySelector('#slide')!.textContent).not.toContain('undefined');
});
