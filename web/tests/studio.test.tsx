import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from '../src/App';
import { api, ApiError, type Health, type Job, type User, type VideoRequest } from '../src/api';

const user: User = { id: 'u'.repeat(32), username: 'alice', createdAt: new Date().toISOString() };
const JOB_KEY = `traversaal.studio.current-job.v2.${user.id}`;

const request: VideoRequest = {
  topic: 'How does GPS know where you are?', audience: 'Curious adults', durationSeconds: 90,
  review: true, music: true, theme: 'light', draft: false, source: 'topic',
};
const health: Health = {
  status: 'ok', liveReady: true, sampleReady: true,
  checks: [{ id: 'claude_key', label: 'Claude API credential', ok: true, detail: 'Configured on the server.' }],
  sample: { title: 'How a Message Crosses the Internet', topic: 'How does a message travel across the internet?', audience: 'Curious adults with no networking background', durationSeconds: 45 },
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
  vi.spyOn(api, 'me').mockResolvedValue(user);
  vi.spyOn(api, 'logout').mockResolvedValue(undefined);
  vi.spyOn(api, 'jobs').mockResolvedValue([]);
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
    expect(localStorage.getItem(JOB_KEY)).toBe(baseJob.id);
  });

  it('can generate the sample with an empty topic and no Claude credential', async () => {
    vi.mocked(api.health).mockResolvedValue({ ...health, liveReady: false });
    render(<App />);
    await screen.findByRole('button', { name: /Setup needed/ });
    await userEvent.click(screen.getByRole('button', { name: 'Try a sample' }));
    await userEvent.click(screen.getByRole('button', { name: 'Generate sample video' }));
    expect(api.createJob).toHaveBeenCalledWith(expect.objectContaining({ source: 'sample', topic: health.sample.topic, audience: health.sample.audience, durationSeconds: 45, review: false }));
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
    localStorage.setItem(JOB_KEY, baseJob.id);
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
    localStorage.setItem(JOB_KEY, baseJob.id);
    vi.mocked(api.job).mockResolvedValue({ ...baseJob, stage: 'failed', status: 'failed', error: 'Generation failed during rendering.' });
    render(<App />);
    await screen.findByText('Generation failed during rendering.');
    expect(screen.queryByRole('link', { name: 'Download MP4' })).toBeNull();
    await userEvent.click(screen.getByRole('button', { name: 'Try again with this brief' }));
    expect(api.createJob).toHaveBeenCalledWith(request);
    expect(api.createJob).toHaveBeenCalledTimes(1);
  });

  it('reconnects after a transient polling error and clears the error when the task is gone', async () => {
    localStorage.setItem(JOB_KEY, baseJob.id);
    vi.mocked(api.job).mockResolvedValueOnce(baseJob).mockRejectedValueOnce(new ApiError('Offline', 0)).mockRejectedValueOnce(new ApiError('Not found', 404));
    render(<App />);
    await screen.findByText('In the queue');
    await waitFor(() => expect(screen.getByText(/Connection interrupted/)).toBeTruthy(), { timeout: 2500 });
    await waitFor(() => expect(screen.getByText('This task is no longer available. Create a new video to continue.')).toBeTruthy(), { timeout: 4500 });
    expect(screen.queryByText(/Connection interrupted/)).toBeNull();
    expect(localStorage.getItem(JOB_KEY)).toBeNull();
  }, 10000);
});

describe('Accounts', () => {
  it('asks a signed-out visitor to sign in, checks the form, then opens their studio', async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError('Sign in to use the studio.', 401, 'not_signed_in'));
    const login = vi.spyOn(api, 'login').mockResolvedValue(user);
    render(<App />);
    await screen.findByRole('heading', { name: 'Sign in to your studio.' });
    expect(api.health).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Use 3–32 letters, numbers, dots, dashes or underscores.')).toBeTruthy();
    expect(login).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText('Username'), ' alice ');
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(login).toHaveBeenCalledWith('alice', 'correct horse');
    await screen.findByRole('button', { name: /Studio ready/ });
    expect(screen.getByText('alice')).toBeTruthy();
  });

  it('shows the server message when the password is wrong', async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError('Sign in to use the studio.', 401));
    vi.spyOn(api, 'login').mockRejectedValue(new ApiError('The username or password is incorrect.', 401, 'invalid_credentials'));
    render(<App />);
    await userEvent.type(await screen.findByLabelText('Username'), 'alice');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong password');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect((await screen.findByRole('alert')).textContent).toContain('The username or password is incorrect.');
    expect(screen.queryByRole('button', { name: /Studio ready/ })).toBeNull();
  });

  it('creates an account only when both passwords match', async () => {
    vi.mocked(api.me).mockRejectedValue(new ApiError('Sign in to use the studio.', 401));
    const register = vi.spyOn(api, 'register').mockResolvedValue({ ...user, username: 'new.user' });
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Create an account' }));
    await userEvent.type(screen.getByLabelText('Username'), 'new.user');
    await userEvent.type(screen.getByLabelText('Password'), 'long password');
    await userEvent.type(screen.getByLabelText('Confirm password'), 'long passwrod');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(screen.getByText('The passwords do not match.')).toBeTruthy();
    expect(register).not.toHaveBeenCalled();
    await userEvent.clear(screen.getByLabelText('Confirm password'));
    await userEvent.type(screen.getByLabelText('Confirm password'), 'long password');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(register).toHaveBeenCalledWith('new.user', 'long password');
    await screen.findByText('new.user');
  });

  it('signs out and returns to the sign-in page', async () => {
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
    expect(api.logout).toHaveBeenCalledTimes(1);
    await screen.findByRole('heading', { name: 'Sign in to your studio.' });
  });

  it('returns to sign-in with a notice when the server ends the session', async () => {
    vi.mocked(api.health).mockRestore();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ error: { code: 'not_signed_in', message: 'Sign in to use the studio.' } }), { status: 401 }));
    render(<App />);
    await screen.findByText('Your session has ended. Sign in again to continue.');
    expect(screen.getByRole('heading', { name: 'Sign in to your studio.' })).toBeTruthy();
  });

  it('does not restore a task remembered for a different account', async () => {
    localStorage.setItem(`traversaal.studio.current-job.v2.${'b'.repeat(32)}`, baseJob.id);
    localStorage.setItem('traversaal.studio.current-job.v1', baseJob.id);
    render(<App />);
    await screen.findByRole('button', { name: /Studio ready/ });
    expect(api.job).not.toHaveBeenCalled();
    expect(screen.getByText('Waiting for your idea')).toBeTruthy();
  });
});

describe('History', () => {
  const failed: Job = { ...baseJob, id: 'f'.repeat(32), status: 'failed', stage: 'failed', error: 'Generation failed during rendering.', request: { ...request, topic: 'Why do we have leap years?' } };

  it('lists past videos with their status and download links', async () => {
    vi.mocked(api.jobs).mockResolvedValue([complete, failed]);
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    expect(await screen.findByText('2 videos')).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'How GPS finds you' })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Why do we have leap years?' })).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Stopped')).toBeTruthy();
    expect(screen.getByText('Generation failed during rendering.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Download MP4: How GPS finds you' }).getAttribute('href')).toBe(complete.result!.downloadUrl);
  });

  it('opens a finished video in the workspace and remembers it', async () => {
    vi.mocked(api.jobs).mockResolvedValue([complete]);
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Open' }));
    expect(await screen.findByLabelText('Generated video: How GPS finds you')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Video workspace' }).getAttribute('aria-current')).toBe('page');
    expect(localStorage.getItem(JOB_KEY)).toBe(complete.id);
  });

  it('retries a stopped video as a new task with its original brief', async () => {
    vi.mocked(api.jobs).mockResolvedValue([failed]);
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    await userEvent.click(await screen.findByRole('button', { name: 'Try again' }));
    expect(api.createJob).toHaveBeenCalledWith(failed.request);
    await screen.findByText('In the queue');
  });

  it('shows an empty library with a way back to the workspace', async () => {
    render(<App />);
    await userEvent.click(await screen.findByRole('button', { name: 'History' }));
    await screen.findByText('No videos yet. Your first one will appear here.');
    await userEvent.click(screen.getByRole('button', { name: /Make a video/ }));
    expect(screen.getByRole('heading', { name: 'The brief' })).toBeTruthy();
  });

  it('keeps other videos closed while one is being created', async () => {
    localStorage.setItem(JOB_KEY, baseJob.id);
    vi.mocked(api.jobs).mockResolvedValue([baseJob, { ...complete, id: 'c'.repeat(32) }]);
    vi.mocked(api.job).mockResolvedValue({ ...baseJob, status: 'running', stage: 'narrating' });
    render(<App />);
    await screen.findByRole('button', { name: 'Generation in progress' });
    await userEvent.click(screen.getByRole('button', { name: 'History' }));
    await screen.findByText('2 videos');
    const [current, other] = screen.getAllByRole('button', { name: 'Open' }) as HTMLButtonElement[];
    expect(current.disabled).toBe(false);
    expect(other.disabled).toBe(true);
  });
});
