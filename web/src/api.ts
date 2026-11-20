/** The only HTTP boundary. UI components do not depend on the Python pipeline. */
export type Stage = 'queued' | 'planning' | 'reviewing' | 'narrating' | 'storyboarding' | 'generating_video' | 'rendering' | 'completed' | 'failed';
export type VideoRequest = {
  topic: string;
  audience: string;
  durationSeconds: number;
  minimumDurationSec?: number;
  review: boolean;
  theme: 'light' | 'night';
  music: boolean;
  draft: boolean;
  source: 'topic' | 'sample';
  visualMode?: 'animation' | 'seedance';
  videoResolution?: '480p' | '720p';
  // Only present in saved hybrid jobs. New submissions do not send a footage limit.
  maxGeneratedSeconds?: number;
};
export type Job = {
  pipelineVersion?: number;
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: Stage;
  message: string;
  createdAt: string;
  updatedAt: string;
  request: VideoRequest;
  error: string | null;
  lineProgress?: { current: number; total: number };
  clipProgress?: { current: number; total: number };
  canResume?: boolean;
  result: null | {
    title: string;
    videoUrl: string;
    downloadUrl: string;
    thumbnailUrl: string | null;
    subtitlesUrl: string | null;
    durationSeconds: number;
    durationCheck?: {
      targetDurationSec: number | null;
      minimumDurationSec: number;
      actualDurationSec: number;
      measurement: 'narrated-timeline' | 'rendered-mp4';
      passed: boolean | null;
    };
    width: number;
    height: number;
    bytes: number;
    generatedVideo?: {model: string; resolution: string; shotCount: number; seconds: number; coverage?: 'full';
      submittedSeconds: number; completionTokens: number; estimatedCostCny: number | null};
  };
};
export type User = { id: string; username: string; createdAt: string };
export type Health = {
  status: 'ok';
  liveReady: boolean;
  sampleReady: boolean;
  seedanceReady?: boolean;
  seedanceSampleReady?: boolean;
  seedanceSample?: { title: string; topic: string; audience: string; durationSeconds: number };
  checks: { id: string; label: string; ok: boolean; detail: string }[];
  sample: { title: string; topic: string; audience: string; durationSeconds: number };
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
    this.name = 'ApiError';
  }
}

let signedOut: (() => void) | null = null;
/** Called when the server says the session has ended, so the app can return to sign-in. */
export function onSignedOut(handler: (() => void) | null) {
  signedOut = handler;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers: { 'Content-Type': 'application/json', ...options?.headers },
      signal: AbortSignal.timeout(15000),
    });
  } catch {
    throw new ApiError('The studio cannot reach the generation service. Check that it is running, then try again.', 0);
  }
  const body = await response.json().catch(() => null);
  if (response.status === 401 && !path.startsWith('/auth/')) signedOut?.();
  if (!response.ok || !body) {
    throw new ApiError(body?.error?.message || 'The generation service did not return a valid response.', response.status, body?.error?.code);
  }
  return body as T;
}

const credentials = (username: string, password: string) => ({ method: 'POST', body: JSON.stringify({ username, password }) });

export const api = {
  me: () => request<{ user: User }>('/auth/me').then((body) => body.user),
  login: (username: string, password: string) => request<{ user: User }>('/auth/login', credentials(username, password)).then((body) => body.user),
  register: (username: string, password: string) => request<{ user: User }>('/auth/register', credentials(username, password)).then((body) => body.user),
  logout: () => request<{ user: null }>('/auth/logout', { method: 'POST' }).then(() => undefined),
  jobs: () => request<{ jobs: Job[] }>('/jobs').then((body) => body.jobs),
  health: () => request<Health>('/health'),
  createJob: (input: VideoRequest) => {
    const {maxGeneratedSeconds: _legacyLimit, ...current} = input;
    const body = input.visualMode === 'seedance' ? {...current, draft: false, theme: 'light', minimumDurationSec: 0} : current;
    return request<Job>('/jobs', { method: 'POST', body: JSON.stringify(body) });
  },
  job: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
  resumeJob: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}/resume`, {method: 'POST', body: '{}'}),
};

export function isReady(health: Health | null, brief: VideoRequest): boolean {
  return Boolean(brief.visualMode === 'seedance'
    ? brief.source === 'sample' ? health?.seedanceSampleReady : health?.seedanceReady
    : brief.source === 'sample' ? health?.sampleReady : health?.liveReady);
}

export function isActive(job: Job | null): boolean {
  return job?.status === 'running' || job?.status === 'queued';
}
