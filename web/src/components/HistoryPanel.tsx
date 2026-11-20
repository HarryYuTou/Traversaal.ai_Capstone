import { ArrowDownToLine, ArrowUpRight, Check, CircleAlert, Clock3, Film, LoaderCircle, RefreshCw, RotateCcw } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { api, isActive, type Job } from '../api';
import { formatDuration } from './VideoPreview';

function when(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

function StatusBadge({ job }: { job: Job }) {
  if (job.status === 'completed') return <span className="history-status done"><Check size={12} />Ready</span>;
  if (job.status === 'failed') return <span className="history-status failed"><CircleAlert size={12} />Stopped</span>;
  return <span className="history-status active"><LoaderCircle size={12} className="spin" />{job.status === 'queued' ? 'Queued' : 'Creating'}</span>;
}

type Props = {
  busy: boolean;
  currentJobId: string | null;
  onOpen: (job: Job) => void;
  onRetry: (job: Job) => void;
  onCreate: () => void;
};

export default function HistoryPanel({ busy, currentJobId, onOpen, onRetry, onCreate }: Props) {
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try { setJobs(await api.jobs()); setError(''); }
    catch (failure) { setError((failure as Error).message); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Keep in-progress rows current without a manual refresh.
  const anyActive = jobs?.some(isActive) ?? false;
  useEffect(() => {
    if (!anyActive) return;
    const timer = setInterval(() => { api.jobs().then(setJobs, () => undefined); }, 4000);
    return () => clearInterval(timer);
  }, [anyActive]);

  return <section className="history" aria-labelledby="history-heading">
    <div className="history-intro">
      <div><div className="eyebrow"><span className="eyebrow-line" />YOUR LIBRARY</div><h1 id="history-heading">Every video you’ve made.</h1><p>Open a finished video, download it again, or retry one that stopped.</p></div>
      <button type="button" className="secondary-button" onClick={() => { void load(); }} disabled={loading}><RefreshCw size={14} className={loading ? 'spin' : undefined} />Refresh</button>
    </div>

    {error && <div className="inline-error" role="alert">{error}</div>}
    {jobs === null && loading && <p className="history-empty" role="status"><LoaderCircle size={15} className="spin" />Loading your videos…</p>}
    {jobs?.length === 0 && <div className="history-empty"><Film size={20} /><p>No videos yet. Your first one will appear here.</p><button type="button" className="primary-button" onClick={onCreate}>Make a video<ArrowUpRight size={15} /></button></div>}

    {jobs && jobs.length > 0 && <>
      <p className="history-count">{jobs.length} {jobs.length === 1 ? 'video' : 'videos'}</p>
      <ul className="history-list">
        {jobs.map((job) => {
          const result = job.status === 'completed' ? job.result : null;
          const title = result?.title || job.request.topic;
          const current = job.id === currentJobId;
          const blocked = busy && !current;
          return <li key={job.id} className={`history-item ${current ? 'current' : ''}`}>
            <div className={`history-thumb ${job.request.theme}`} aria-hidden="true">{result?.thumbnailUrl ? <img src={result.thumbnailUrl} alt="" loading="lazy" /> : <Film size={18} />}</div>
            <div className="history-copy">
              <h2>{title}</h2>
              <div className="history-meta">
                <StatusBadge job={job} />
                <span>{when(job.createdAt)}</span>
                {result ? <span><Clock3 size={12} />{formatDuration(result.durationSeconds)}</span> : <span>Target {formatDuration(job.request.durationSeconds)}</span>}
                {job.request.source === 'sample' && <span>Sample script</span>}
                {job.request.draft && <span>Draft</span>}
                {job.request.visualMode === 'seedance' && <span>Seedance Fast · {job.request.videoResolution || '480p'}</span>}
                {current && <span className="history-current">In your workspace</span>}
              </div>
              {job.status === 'failed' && job.error && <p className="history-error">{job.error}</p>}
            </div>
            <div className="history-actions">
              <button type="button" className="secondary-button" onClick={() => onOpen(job)} disabled={blocked} title={blocked ? 'Wait for the current video to finish first.' : undefined}>Open</button>
              {result && <a className="secondary-button" href={result.downloadUrl} download aria-label={`Download MP4: ${title}`}><ArrowDownToLine size={14} />MP4</a>}
              {job.status === 'failed' && (job.canResume || job.request.visualMode !== 'seedance') && <button type="button" className="text-button" onClick={() => onRetry(job)} disabled={busy}><RotateCcw size={13} />{job.canResume ? 'Resume' : 'Try again'}</button>}
            </div>
          </li>;
        })}
      </ul>
    </>}
  </section>;
}
