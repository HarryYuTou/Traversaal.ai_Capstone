import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, isActive, type Health, type Job, type VideoRequest } from './api';

// Scoped by account so a second person on the same browser never restores someone else's task.
export const activeJobKey = (userId: string) => `traversaal.studio.current-job.v2.${userId}`;

export function useStudio(userId: string) {
  const key = activeJobKey(userId);
  const storedJob = useCallback((): string | null => {
    try { return localStorage.getItem(key); } catch { return null; }
  }, [key]);
  const rememberJob = useCallback((id: string | null) => {
    try {
      if (id) localStorage.setItem(key, id);
      else localStorage.removeItem(key);
    } catch { /* A private browser can still generate and play a video. */ }
  }, [key]);
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState('');
  const [checking, setChecking] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [restoring, setRestoring] = useState(() => Boolean(storedJob()));
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [connectionError, setConnectionError] = useState('');
  const submittingRef = useRef(false);
  const generation = useRef(0);

  const checkHealth = useCallback(async () => {
    setChecking(true);
    try { setHealth(await api.health()); setHealthError(''); }
    catch (error) { setHealth(null); setHealthError((error as Error).message); }
    finally { setChecking(false); }
  }, []);

  useEffect(() => { void checkHealth(); }, [checkHealth]);

  useEffect(() => {
    const id = storedJob();
    if (!id) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const restore = async () => {
      try {
        const current = await api.job(id);
        if (stopped) return;
        setJob(current);
        setConnectionError('');
        setRestoring(false);
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.status === 404) {
          rememberJob(null);
          setRestoring(false);
          setConnectionError('');
          setSubmitError('Your previous video is no longer available. You can create a new one.');
        } else {
          setConnectionError('Reconnecting to your last video. Your task is kept on the server.');
          timer = setTimeout(restore, 3000);
        }
      }
    };
    void restore();
    return () => { stopped = true; clearTimeout(timer); };
  }, [storedJob, rememberJob]);

  useEffect(() => {
    if (!job || !isActive(job)) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const id = job.id;
    const poll = async () => {
      try {
        const updated = await api.job(id);
        if (stopped) return;
        setJob(updated);
        setConnectionError('');
        if (isActive(updated)) timer = setTimeout(poll, 1500);
      } catch (error) {
        if (stopped) return;
        if (error instanceof ApiError && error.status === 404) {
          setJob(null);
          rememberJob(null);
          setConnectionError('');
          setSubmitError('This task is no longer available. Create a new video to continue.');
          return;
        }
        setConnectionError('Connection interrupted. Reconnecting automatically; generation may still be running.');
        timer = setTimeout(poll, 3000);
      }
    };
    timer = setTimeout(poll, 1000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [job?.id, job?.status, rememberJob]);

  const submit = useCallback(async (input: VideoRequest) => {
    if (submittingRef.current || isActive(job) || restoring) return;
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError('');
    const version = ++generation.current;
    try {
      const created = await api.createJob(input);
      if (generation.current !== version) return;
      rememberJob(created.id);
      setJob(created);
      setConnectionError('');
    } catch (error) {
      setSubmitError((error as Error).message);
      void checkHealth();
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }, [job, restoring, checkHealth, rememberJob]);

  const reset = useCallback(() => {
    if (isActive(job) || submittingRef.current || restoring) return;
    generation.current += 1;
    rememberJob(null);
    setJob(null);
    setSubmitError('');
    setConnectionError('');
  }, [job, restoring, rememberJob]);

  const resume = useCallback(async (selected: Job) => {
    if (submittingRef.current || isActive(job) || restoring || !selected.canResume) return;
    submittingRef.current = true;
    setSubmitting(true);
    setSubmitError('');
    try {
      const resumed = await api.resumeJob(selected.id);
      rememberJob(resumed.id);
      setJob(resumed);
      setConnectionError('');
    } catch (error) {
      setSubmitError((error as Error).message);
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  }, [job, restoring, rememberJob]);

  /** Show a job from history in the workspace; refused while another job is still being created. */
  const open = useCallback((selected: Job) => {
    if (selected.id === job?.id) return true;
    if (isActive(job) || submittingRef.current || restoring) return false;
    generation.current += 1;
    rememberJob(selected.id);
    setJob(selected);
    setSubmitError('');
    setConnectionError('');
    return true;
  }, [job, restoring, rememberJob]);

  return { health, healthError, checking, checkHealth, job, restoring, submitting, submitError, connectionError, submit, resume, reset, open };
}
