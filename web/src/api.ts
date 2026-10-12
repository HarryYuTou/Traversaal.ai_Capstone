/** The only HTTP boundary. UI components do not depend on the Python pipeline. */
export type Stage = 'queued' | 'planning' | 'reviewing' | 'narrating' | 'rendering' | 'completed' | 'failed';
export type VideoRequest = {
  topic: string;
  audience: string;
  durationSeconds: number;
  review: boolean;
  theme: 'light' | 'night';
  music: boolean;
  draft: boolean;
  source: 'topic' | 'sample';
};
export type Job = {
  id: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  stage: Stage;
  message: string;
  createdAt: string;
  updatedAt: string;
  request: VideoRequest;
  error: string | null;
  lineProgress?: { current: number; total: number };
  result: null | {
    title: string;
    videoUrl: string;
    downloadUrl: string;
    thumbnailUrl: string | null;
    subtitlesUrl: string | null;
    durationSeconds: number;
    width: number;
    height: number;
    bytes: number;
  };
};
export type Health = {
  status: 'ok';
  liveReady: boolean;
  sampleReady: boolean;
  checks: { id: string; label: string; ok: boolean; detail: string }[];
  sample: { title: string; topic: string; audience: string; durationSeconds: number };
};

export class ApiError extends Error {
  constructor(message: string, public status: number, public code?: string) {
    super(message);
    this.name = 'ApiError';
  }
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
  if (!response.ok || !body) {
    throw new ApiError(body?.error?.message || 'The generation service did not return a valid response.', response.status, body?.error?.code);
  }
  return body as T;
}

export const api = {
  health: () => request<Health>('/health'),
  createJob: (input: VideoRequest) => request<Job>('/jobs', { method: 'POST', body: JSON.stringify(input) }),
  job: (id: string) => request<Job>(`/jobs/${encodeURIComponent(id)}`),
};

export function isActive(job: Job | null): boolean {
  return job?.status === 'running' || job?.status === 'queued';
}
