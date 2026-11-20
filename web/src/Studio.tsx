import { ArrowUpRight, Check, CircleAlert, CircleHelp, Globe2, History, LoaderCircle, LogOut, MonitorPlay, RotateCcw, UserRound } from 'lucide-react';
import { useEffect, useState } from 'react';
import { isActive, isReady, type User, type VideoRequest } from './api';
import Brand from './components/Brand';
import BriefForm from './components/BriefForm';
import HistoryPanel from './components/HistoryPanel';
import StagePanel from './components/StagePanel';
import VideoPreview from './components/VideoPreview';
import StudioDialog from './components/StudioDialog';
import { useStudio } from './useStudio';

const DEFAULT_BRIEF: VideoRequest = { topic: '', audience: 'Curious adults with no prior knowledge', durationSeconds: 90, review: true, theme: 'light', music: true, draft: false, source: 'topic' };
const briefKey = (userId: string) => `traversaal.studio.brief.v2.${userId}`;
function initialBrief(key: string): VideoRequest {
  try {
    const saved = JSON.parse(localStorage.getItem(key) || 'null') as Partial<VideoRequest> | null;
    if (!saved || typeof saved.topic !== 'string' || typeof saved.audience !== 'string') return DEFAULT_BRIEF;
    return {
      ...DEFAULT_BRIEF, topic: saved.topic.slice(0, 500), audience: saved.audience.slice(0, 200),
      durationSeconds: [30, 60, 90, 120, 180, 300, 420, 600].includes(saved.durationSeconds || 0) ? saved.durationSeconds! : 90,
      source: saved.source === 'sample' ? 'sample' : 'topic', theme: saved.theme === 'night' ? 'night' : 'light',
      review: saved.review !== false, music: saved.music !== false, draft: saved.draft === true,
      visualMode: saved.visualMode === 'seedance' ? 'seedance' : 'animation',
      videoResolution: saved.videoResolution === '720p' ? '720p' : '480p',
    };
  } catch { return DEFAULT_BRIEF; }
}

export default function Studio({ user, onSignOut }: { user: User; onSignOut: () => void }) {
  const studio = useStudio(user.id);
  const [brief, setBrief] = useState(() => initialBrief(briefKey(user.id)));
  const [dialog, setDialog] = useState<'setup' | 'help' | null>(null);
  const [view, setView] = useState<'workspace' | 'history'>('workspace');
  const busy = studio.submitting || studio.restoring || isActive(studio.job);
  const activeBrief = busy && studio.job ? studio.job.request : brief;
  const selectedReady = isReady(studio.health, brief);
  useEffect(() => {
    try { localStorage.setItem(briefKey(user.id), JSON.stringify(brief)); } catch { /* Draft persistence is optional. */ }
  }, [brief, user.id]);

  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to workspace</a>
    <header className="app-header"><div className="header-inner">
      <Brand />
      <nav className="app-nav" aria-label="Studio">
        <button type="button" aria-current={view === 'workspace' ? 'page' : undefined} onClick={() => setView('workspace')}><MonitorPlay size={15} />Video workspace</button>
        <button type="button" aria-current={view === 'history' ? 'page' : undefined} onClick={() => setView('history')}><History size={15} />History</button>
      </nav>
      <div className="header-actions">
        <button type="button" className="help-button" onClick={() => setDialog('help')} aria-label="How it works"><CircleHelp size={16} /><span>How it works</span></button>
        <span className="account-name" title={`Signed in as ${user.username}`}><UserRound size={14} /><span>{user.username}</span></span>
        <button type="button" className="help-button sign-out" onClick={onSignOut} aria-label="Sign out"><LogOut size={15} /><span>Sign out</span></button>
      </div>
    </div></header>

    {view === 'history' ? <main id="main-content" className="workspace">
      <HistoryPanel busy={busy} currentJobId={studio.job?.id ?? null}
        onOpen={(job) => { if (studio.open(job)) setView('workspace'); }}
        onRetry={(job) => { setView('workspace'); void (job.canResume ? studio.resume(job) : studio.submit(job.request)); }}
        onCreate={() => setView('workspace')} />
      <footer className="workspace-footer"><span>A little curiosity. A clearer world.</span><span>Traversaal Capstone <span className="footer-dot">·</span> Studio v1</span></footer>
    </main> : <main id="main-content" className="workspace">
      <div className="workspace-intro"><div><div className="eyebrow"><span className="eyebrow-line" />YOUR NEXT EXPLAINER</div><h1>An idea, made clear.</h1><p>Turn something worth explaining into something worth watching.</p></div>
        <button className={`service-badge ${studio.health?.liveReady ? 'ready' : ''}`} type="button" onClick={() => setDialog('setup')}>
          {studio.checking ? <LoaderCircle size={13} className="spin" /> : studio.health?.liveReady ? <span className="status-dot" /> : <CircleAlert size={14} />}
          {studio.checking ? 'Checking studio' : studio.health?.liveReady ? 'Studio ready' : studio.healthError ? 'Service offline' : 'Setup needed'}<ArrowUpRight size={13} />
        </button>
      </div>
      <div className="workspace-meta"><span><Globe2 size={13} />English narration</span><span className="meta-separator" /><span>30 seconds to 10 minutes</span><span className="meta-separator" /><span>Made on your computer</span></div>

      {!busy && !studio.checking && !selectedReady && <div className="setup-banner"><CircleAlert size={17} /><p>{studio.healthError ? 'Connect to the generation service to start creating.' : brief.visualMode === 'seedance' ? 'Seedance footage needs an Ark API key. Check the setup for this mode.' : brief.source === 'topic' && studio.health?.sampleReady ? 'Your own topic needs a Claude API key. You can try a sample while you set up.' : 'A few setup steps are needed before your first video.'}</p><button type="button" onClick={() => setDialog('setup')}>View setup<ArrowUpRight size={14} /></button></div>}
      {studio.connectionError && <div className="connection-banner" role="status"><LoaderCircle className="spin" size={16} />{studio.connectionError}</div>}

      <div className="studio-grid">
        <BriefForm value={activeBrief} onChange={setBrief} onSubmit={(request) => { void studio.submit(request); }} health={studio.health} disabled={busy} submitting={studio.submitting} error={studio.submitError} onSetup={() => setDialog('setup')} />
        <div className="output-column">
          <VideoPreview job={studio.job} brief={brief} onReset={studio.reset} restoring={studio.restoring} />
          <StagePanel job={studio.job} />
          <div className="task-announcement sr-only" role="status" aria-live="polite" aria-atomic="true">{studio.job ? `${studio.job.stage}: ${studio.job.message}` : ''}</div>
          {studio.job?.status === 'failed' && (studio.job.canResume || studio.job.request.visualMode !== 'seedance') &&
            <button className="secondary-button retry-button" type="button" onClick={() => {
              void (studio.job!.canResume ? studio.resume(studio.job!) : studio.submit(studio.job!.request));
            }} disabled={studio.submitting}><RotateCcw size={15} />{studio.job.canResume ? 'Resume saved video' : 'Try again with this brief'}</button>}
          {studio.job?.status === 'completed' && <p className="completion-note"><Check size={14} />Saved to your history on this computer. Review it before sharing.</p>}
        </div>
      </div>
      <footer className="workspace-footer"><span>A little curiosity. A clearer world.</span><span>Traversaal Capstone <span className="footer-dot">·</span> Studio v1</span></footer>
    </main>}
    {dialog && <StudioDialog kind={dialog} onClose={() => setDialog(null)} health={studio.health} healthError={studio.healthError} checking={studio.checking} onCheck={() => { void studio.checkHealth(); }} />}
  </div>;
}
