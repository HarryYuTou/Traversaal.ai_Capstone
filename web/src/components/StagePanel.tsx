import { Check, CircleAlert, Clapperboard, FileText, LoaderCircle, Mic, ScanText } from 'lucide-react';
import type { Job, Stage } from '../api';

const STEPS = [
  { stage: 'planning', label: 'Write the story', detail: 'A script shaped around your audience', icon: FileText },
  { stage: 'reviewing', label: 'Refine the script', detail: 'A second pass for clarity and flow', icon: ScanText },
  { stage: 'narrating', label: 'Bring it to voice', detail: 'Natural narration, one line at a time', icon: Mic },
  { stage: 'storyboarding', label: 'Plan the footage', detail: 'Shots matched to the measured narration', icon: FileText },
  { stage: 'generating_video', label: 'Generate the footage', detail: 'Seedance 2.0 Fast · saved clip progress', icon: Clapperboard },
  { stage: 'rendering', label: 'Put it all together', detail: 'Animated scenes, captions and sound', icon: Clapperboard },
] as const;
const ORDER: Stage[] = ['planning', 'reviewing', 'narrating', 'storyboarding', 'generating_video', 'rendering', 'completed'];

export default function StagePanel({ job }: { job: Job | null }) {
  const sample = job?.request.source === 'sample';
  const failed = job?.status === 'failed';
  const completed = job?.status === 'completed';
  const current = job ? ORDER.indexOf(job.stage) : -1;
  return <section className="stages" aria-labelledby="stages-heading">
    <div className="stages-heading"><h3 id="stages-heading">From idea to explainer</h3><span>{completed ? 'All done' : job?.status === 'queued' ? 'In the queue' : failed ? 'Needs attention' : job ? 'In progress' : 'The process'}</span></div>
    <ol className="stage-list">
      {STEPS.filter((step) => job?.request.visualMode === 'seedance' || !['storyboarding', 'generating_video'].includes(step.stage)).map((step, index) => {
        const skipped = (sample && index < 2) || (index === 1 && job && !job.request.review);
        const done = !skipped && (completed || current > ORDER.indexOf(step.stage));
        const active = !failed && !completed && job?.stage === step.stage;
        const detail = step.stage === 'rendering' && job?.request.visualMode === 'seedance' && job.pipelineVersion === 2
          ? 'Generated scenes, captions and sound' : step.detail;
        const Icon = step.icon;
        return <li key={step.stage} className={`stage ${done ? 'done' : ''} ${active ? 'active' : ''} ${skipped ? 'skipped' : ''}`} aria-current={active ? 'step' : undefined}>
          <span className="stage-icon">{done ? <Check size={16} /> : active ? <LoaderCircle size={16} className="spin" /> : <Icon size={16} />}</span>
          <div className="stage-copy"><span>{step.label}</span><small>{skipped ? index === 0 ? 'Using the ready-to-use sample script' : 'Not needed for this video' : active && job?.clipProgress && step.stage === 'generating_video' ? `${job.clipProgress.current} of ${job.clipProgress.total} clips ready` : active && job?.lineProgress && step.stage === 'narrating' ? `${job.lineProgress.current} of ${job.lineProgress.total} lines narrated` : detail}</small></div>
          <span className="stage-status">{done ? 'Done' : active ? 'Working' : skipped ? 'Skipped' : String(index + 1).padStart(2, '0')}</span>
        </li>;
      })}
    </ol>
    {job?.status === 'running' && job.request.visualMode === 'seedance' && <p className="field-hint" role="status">{job.message}</p>}
    {failed && <div className="job-failure" role="alert"><CircleAlert size={18} /><div><strong>We couldn’t finish this video</strong><p>{job.error || job.message || 'An unexpected error interrupted generation. Try again with a new video.'}</p><small>{job.canResume ? 'Resume reuses saved clips and task IDs. A failed shot can be retried once.' : job.request.visualMode === 'seedance' ? 'Check saved task records before starting another paid generation.' : 'Your brief is saved. A retry starts a new generation.'}</small></div></div>}
  </section>;
}
