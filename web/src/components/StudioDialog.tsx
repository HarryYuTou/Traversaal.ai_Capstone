import { Check, CircleAlert, LoaderCircle, X } from 'lucide-react';
import { useEffect, useRef } from 'react';
import type { Health } from '../api';

export default function StudioDialog({ kind, onClose, health, healthError, checking, onCheck }: { kind: 'setup' | 'help'; onClose: () => void; health: Health | null; healthError: string; checking: boolean; onCheck: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    dialog.showModal();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => { dialog.close(); document.body.style.overflow = previousOverflow; };
  }, []);
  return <dialog ref={ref} className="studio-dialog" aria-labelledby="dialog-title" onCancel={onClose} onClick={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="dialog-content"><button className="icon-button close-dialog" onClick={onClose} aria-label="Close dialog"><X size={20} /></button>
      <span className="eyebrow">TRAVERSAAL STUDIO</span><h2 id="dialog-title">{kind === 'setup' ? 'Ready when you are.' : 'An idea in. A video out.'}</h2>
      {kind === 'setup' ? <>
        <p>Your studio runs on this computer. These checks make sure everything is in place before you start.</p>
        {healthError && <div className="inline-error" role="alert">{healthError}</div>}
        <ul className="setup-checks">{health?.checks.map((check) => <li key={check.id}><span className={check.ok ? 'check-ok' : 'check-needed'}>{check.ok ? <Check size={17} /> : <CircleAlert size={17} />}</span><div><strong>{check.label}</strong><p>{check.detail}</p></div></li>)}</ul>
        <p className="setup-note">An animated sample needs no API key. Seedance footage, including samples, uses your Ark key and incurs video charges. Your own topic also uses Claude for planning. Keep credentials out of the browser.</p>
        <button className="primary-button" type="button" disabled={checking} onClick={onCheck}>{checking && <LoaderCircle className="spin" size={16} />}{checking ? 'Checking…' : 'Check again'}</button>
      </> : <>
        <p>Start with a question you’d like to explain. Your audience and target length help shape the story.</p>
        <ol className="help-steps"><li><strong>Make it specific.</strong><p>“How does GPS find my location?” works better than “Technology.”</p></li><li><strong>Let the story take shape.</strong><p>We plan the scenes, review the script, create English narration and render the video. Longer videos take more time.</p></li><li><strong>Watch, then share.</strong><p>Play your finished video here, download the MP4, or take the subtitles with you. Check facts and pronunciation before publishing.</p></li></ol>
        <p className="setup-note">Want to explore first? Choose “Try a sample” to generate a video from a ready-to-use script, without an AI script request.</p>
        <button className="primary-button" type="button" onClick={onClose}>Let’s make a video</button>
      </>}
    </div>
  </dialog>;
}
