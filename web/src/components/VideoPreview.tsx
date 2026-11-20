import { ArrowDownToLine, ArrowUpRight, Check, Clock3, FileText, Film, LoaderCircle, Maximize2, Volume2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import { isActive, type Job, type VideoRequest } from '../api';

export function formatDuration(seconds: number): string {
  const whole = Math.round(seconds);
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

function elapsed(job: Job | null): string {
  if (!job) return '';
  const end = isActive(job) ? Date.now() : new Date(job.updatedAt).getTime();
  return formatDuration(Math.max(0, (end - new Date(job.createdAt).getTime()) / 1000));
}

export default function VideoPreview({ job, brief, onReset, restoring }: { job: Job | null; brief: VideoRequest; onReset: () => void; restoring: boolean }) {
  const [elapsedText, setElapsedText] = useState(() => elapsed(job));
  const [playError, setPlayError] = useState(false);
  useEffect(() => {
    setElapsedText(elapsed(job));
    if (!isActive(job)) return;
    const timer = setInterval(() => setElapsedText(elapsed(job)), 1000);
    return () => clearInterval(timer);
  }, [job]);
  useEffect(() => { setPlayError(false); }, [job?.id]);
  const active = isActive(job);
  const result = job?.status === 'completed' ? job.result : null;
  const theme = job?.request.theme || brief.theme;
  const title = result?.title || job?.request.topic;

  return <section className="preview-section" aria-labelledby="preview-heading">
    <div className="panel-heading preview-heading"><span className="section-number">02</span><h2 id="preview-heading">Your video</h2><span className={`preview-state ${result ? 'success' : ''}`}>{result ? <><Check size={13} />Ready to watch</> : active ? <><LoaderCircle size={13} className="spin" />Creating</> : restoring ? 'Reconnecting' : job?.status === 'failed' ? 'Generation stopped' : 'Waiting for your idea'}</span></div>
    {result ? <div className="finished-video">
      <video key={job?.id} controls preload="metadata" playsInline poster={result.thumbnailUrl || undefined} onError={() => setPlayError(true)} aria-label={`Generated video: ${result.title}`}>
        <source src={result.videoUrl} type="video/mp4" />
        Your browser does not support embedded video. Use Download MP4 below.
      </video>
      {playError && <p className="playback-error" role="alert">This browser couldn’t play the video. You can still download it below.</p>}
    </div> : <div className={`preview-canvas ${theme} ${active ? 'is-generating' : ''}`}>
      <div className="canvas-top"><span><span className="tiny-mark" />TRAVERSAAL STUDIO</span><span>16:9</span></div>
      <div className="story-paper" aria-hidden="true">
        <span className="story-eyebrow">{active ? 'YOUR STORY IS TAKING SHAPE' : 'A LITTLE CURIOSITY GOES A LONG WAY'}</span>
        <div className="story-title">{title || <>Big ideas.<br /><em>Made clear.</em></>}</div>
        <div className="story-rule" />
        <div className="story-diagram"><span><FileText size={17} />Story</span><i /><span><Volume2 size={17} />Voice</span><i /><span><Film size={17} />Video</span></div>
      </div>
      <div className="canvas-bottom"><span>{active ? <><LoaderCircle size={12} className="spin" />{job?.status === 'queued' ? 'Your video is in the queue' : 'Generating your video'}</> : restoring ? 'Restoring your last task…' : 'Illustrative preview · Your video will appear here'}</span><Maximize2 size={13} /></div>
    </div>}

    {result ? <div className="result-details">
      <h3>{result.title}</h3>
      {result.generatedVideo && <p className="field-hint">Seedance 2.0 Fast · {result.generatedVideo.shotCount} clips · {result.generatedVideo.resolution} {result.generatedVideo.coverage === 'full' ? 'full video' : 'source footage'} · {result.generatedVideo.estimatedCostCny == null ? 'Cost unavailable' : `estimated ¥${result.generatedVideo.estimatedCostCny.toFixed(2)}`} in video generation. Actual Ark bill controls.</p>}
      <div className="result-meta"><span><Clock3 size={13} />{formatDuration(result.durationSeconds)}</span><span>{result.width} × {result.height}</span><span>{(result.bytes / 1_000_000).toFixed(1)} MB</span>{job?.request.source === 'sample' && <span>Sample script</span>}</div>
      <div className="result-meta" aria-label="Duration verification">
        <span>Target {formatDuration(result.durationCheck?.targetDurationSec ?? job!.request.durationSeconds)}</span>
        <span>Actual {formatDuration(result.durationSeconds)}</span>
        {result.durationCheck?.minimumDurationSec ? <span>{result.durationCheck.passed === true ? <><Check size={13} />Minimum {formatDuration(result.durationCheck.minimumDurationSec)} · Passed</> : <>Minimum {formatDuration(result.durationCheck.minimumDurationSec)} · Not passed</>}</span> : <span>No minimum required</span>}
      </div>
      <div className="result-actions"><a className="primary-button" href={result.downloadUrl} download><ArrowDownToLine size={16} />Download MP4</a>{result.subtitlesUrl && <a className="secondary-button" href={result.subtitlesUrl} download><FileText size={15} />Subtitles</a>}<button type="button" className="text-button new-video" onClick={onReset}>New video<ArrowUpRight size={15} /></button></div>
    </div> : <div className="preview-caption">
      <span>{active ? 'You can refresh this page. We’ll keep your place.' : restoring ? 'Looking for your previous task.' : 'Animated scenes. A clear voice. Your idea, explained.'}</span>
      {job && <span className="elapsed"><Clock3 size={12} />{elapsedText}</span>}
    </div>}
  </section>;
}
