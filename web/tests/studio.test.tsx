import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import { api, ApiError, type Health, type Job, type VideoRequest } from '../src/api';

const request: VideoRequest = {
  topic: 'How does GPS know where you are?', audience: 'Curious adults', durationSeconds: 90,
  review: true, music: true, theme: 'light', draft: false, source: 'topic',
};
const health: Health = {
  status: 'ok', liveReady: true, sampleReady: true,
  checks: [{ id: 'claude_key', label: 'Claude API credential', ok: true, detail: 'Configured on the server.' }],
  sample: { title: 'From an Address to a Web Page', topic: 'What happens when you type a website address and press Enter?', audience: 'Curious adults with no technical background', durationSeconds: 90 },
};
const baseJob: Job = {
  id: 'a'.repeat(32), status: 'queued', stage: 'queued', message: 'Queued.',
  createdAt: new Date().toISOString(), updatedAt: new Date().toISOString(), request, error: null, result: null,
};
const complete: Job = {
  ...baseJob, status: 'completed', stage: 'completed', message: 'Ready.',
  result: { title: 'How GPS finds you', videoUrl: '/api/jobs/a/files/video.mp4', downloadUrl: '/api/jobs/a/files/video.mp4?download=1', thumbnailUrl: null, subtitlesUrl: '/api/jobs/a/files/subtitles.vtt', durationSeconds: 91.2, width: 1920, height: 1080, bytes: 10_000_000 },
};

beforeEach(() => {
  localStorage.clear();
  vi.spyOn(api, 'health').mockResolvedValue(health);
  vi.spyOn(api, 'createJob').mockResolvedValue(baseJob);
  vi.spyOn(api, 'job').mockResolvedValue(baseJob);
  // jsdom has no modal top layer; these shims let us test its user-visible content.
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', ''); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute('open'); };
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe('Studio workflow', () => {
  it('rejects an empty brief before creating a task and focuses the problem', async () => {
    render(<App />);
    await screen.findByRole('button', { name: /Studio ready/ });
    await userEvent.click(screen.getByRole('button', { name: 'Generate video' }));
    expect(screen.getByText('Add a topic for your video.')).toBeTruthy();
    expect(document.activeElement).toBe(screen.getByLabelText('What would you like to explain?'));
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it('submits the actual brief and blocks duplicate clicks while the request is pending', async () => {
    let resolve!: (job: Job) => void;
    vi.mocked(api.createJob).mockReturnValue(new Promise((done) => { resolve = done; }));
    render(<App />);
    await screen.findByRole('button', { name: /Studio ready/ });
    await userEvent.click(screen.getByRole('button', { name: 'How GPS works' }));
    await userEvent.clear(screen.getByLabelText('Who’s watching?'));
    await userEvent.type(screen.getByLabelText('Who’s watching?'), 'High school students');
    await userEvent.selectOptions(screen.getByLabelText('Target length'), '420');
    const button = screen.getByRole('button', { name: 'Generate video' });
    fireEvent.click(button);
    fireEvent.click(button);
    expect(api.createJob).toHaveBeenCalledTimes(1);
    expect(api.createJob).toHaveBeenCalledWith(expect.objectContaining({ topic: request.topic, audience: 'High school students', durationSeconds: 420, source: 'topic' }));
    await act(async () => { resolve({ ...baseJob, request: { ...request, durationSeconds: 420 } }); });
    expect((screen.getByRole('button', { name: 'Generation in progress' }) as HTMLButtonElement).disabled).toBe(true);
    expect(localStorage.getItem('traversaal.studio.current-job.v1')).toBe(baseJob.id);
  });

  it('can generate the sample with an empty topic and no Claude credential', async () => {
    vi.mocked(api.health).mockResolvedValue({ ...health, liveReady: false });
    render(<App />);
    await screen.findByRole('button', { name: /Setup needed/ });
    await userEvent.click(screen.getByRole('button', { name: 'Try a sample' }));
    await userEvent.click(screen.getByRole('button', { name: 'Generate sample video' }));
    expect(api.createJob).toHaveBeenCalledWith(expect.objectContaining({ source: 'sample', topic: health.sample.topic, audience: health.sample.audience, durationSeconds: 90, review: false }));
  });

  it('shows setup instead of making a paid request when topic generation is unavailable', async () => {
    vi.mocked(api.health).mockResolvedValue({ ...health, liveReady: false, checks: [{ id: 'claude_key', label: 'Claude API credential', ok: false, detail: 'Add a key to the server environment.' }] });
    render(<App />);
    await screen.findByRole('button', { name: /Setup needed/ });
    await userEvent.click(screen.getByRole('button', { name: 'How GPS works' }));
    await userEvent.click(screen.getByRole('button', { name: 'Generate video' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(screen.getByText('Add a key to the server environment.')).toBeTruthy();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it('restores a completed task after refresh and offers the correct media URLs', async () => {
    localStorage.setItem('traversaal.studio.current-job.v1', baseJob.id);
    vi.mocked(api.job).mockResolvedValue(complete);
    render(<App />);
    const download = await screen.findByRole('link', { name: 'Download MP4' });
    expect(download.getAttribute('href')).toBe(complete.result!.downloadUrl);
    const video = screen.getByLabelText('Generated video: How GPS finds you') as HTMLVideoElement;
    expect(video.querySelector('source')?.getAttribute('src')).toBe(complete.result!.videoUrl);
    expect(video.hasAttribute('controls')).toBe(true);
    expect(screen.getByText('Ready to watch')).toBeTruthy();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it('clears stale readiness when the service can no longer be reached', async () => {
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: /Studio ready/ }));
    vi.mocked(api.health).mockRejectedValue(new ApiError('The service is unavailable.', 0));
    await userEvent.click(screen.getByRole('button', { name: 'Check again' }));
    await screen.findByText('The service is unavailable.');
    await userEvent.click(screen.getByRole('button', { name: 'Close dialog' }));
    expect(screen.getByRole('button', { name: /Service offline/ })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Studio ready/ })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'How GPS works' }));
    await userEvent.click(screen.getByRole('button', { name: 'Generate video' }));
    expect(screen.getByRole('dialog')).toBeTruthy();
    expect(api.createJob).not.toHaveBeenCalled();
  });

  it('surfaces a failure and retries as a new task using the original brief', async () => {
    localStorage.setItem('traversaal.studio.current-job.v1', baseJob.id);
    vi.mocked(api.job).mockResolvedValue({ ...baseJob, stage: 'failed', status: 'failed', error: 'Generation failed during rendering.' });
    render(<App />);
    await screen.findByText('Generation failed during rendering.');
    expect(screen.queryByRole('link', { name: 'Download MP4' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Try again with this brief' }));
    expect(api.createJob).toHaveBeenCalledWith(request);
    expect(api.createJob).toHaveBeenCalledTimes(1);
  });

  it('reconnects after a transient polling error and clears the error when the task is gone', async () => {
    localStorage.setItem('traversaal.studio.current-job.v1', baseJob.id);
    vi.mocked(api.job).mockResolvedValueOnce(baseJob).mockRejectedValueOnce(new ApiError('Offline', 0)).mockRejectedValueOnce(new ApiError('Not found', 404));
    render(<App />);
    await screen.findByText('In the queue');
    await waitFor(() => expect(screen.getByText(/Connection interrupted/)).toBeTruthy(), { timeout: 2500 });
    await waitFor(() => expect(screen.getByText('This task is no longer available. Create a new video to continue.')).toBeTruthy(), { timeout: 4500 });
    expect(screen.queryByText(/Connection interrupted/)).toBeNull();
    expect(localStorage.getItem('traversaal.studio.current-job.v1')).toBeNull();
  }, 10000);
});
