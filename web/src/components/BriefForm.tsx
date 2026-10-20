import { ArrowRight, ChevronDown, Clock3, FlaskConical, LoaderCircle, Sparkles } from 'lucide-react';
import { useId, useRef, useState } from 'react';
import type { Health, VideoRequest } from '../api';

const IDEAS = [
  { label: 'How GPS works', topic: 'How does GPS know where you are?' },
  { label: 'The Silk Road', topic: 'How did the Silk Road connect different cultures?' },
  { label: 'Leap years', topic: 'Why do we have leap years?' },
];

type Props = {
  value: VideoRequest;
  onChange: (value: VideoRequest) => void;
  onSubmit: (value: VideoRequest) => void;
  health: Health | null;
  disabled: boolean;
  submitting: boolean;
  error: string;
  onSetup: () => void;
};

export default function BriefForm({ value, onChange, onSubmit, health, disabled, submitting, error, onSetup }: Props) {
  const id = useId();
  const topicRef = useRef<HTMLTextAreaElement>(null);
  const audienceRef = useRef<HTMLInputElement>(null);
  const [errors, setErrors] = useState<{ topic?: string; audience?: string }>({});
  const sample = value.source === 'sample';
  const ready = sample ? health?.sampleReady : health?.liveReady;
  const update = (patch: Partial<VideoRequest>) => onChange({ ...value, ...patch });
  const changeSource = (source: VideoRequest['source']) => {
    setErrors({});
    update({ source });
  };

  return <section className="brief-panel" aria-labelledby="brief-heading">
    <div className="panel-heading"><span className="section-number">01</span><h2 id="brief-heading">The brief</h2><span className="panel-hint">Start with a little curiosity</span></div>
    <form noValidate onSubmit={(event) => {
      event.preventDefault();
      if (disabled) return;
      const next: typeof errors = {};
      if (!sample && !value.topic.trim()) next.topic = 'Add a topic for your video.';
      if (!sample && !value.audience.trim()) next.audience = 'Tell us who this video is for.';
      setErrors(next);
      if (next.topic) return topicRef.current?.focus();
      if (next.audience) return audienceRef.current?.focus();
      if (!ready) return onSetup();
      onSubmit(sample ? {
        ...value,
        topic: health?.sample.topic || 'How does a message travel across the internet?',
        audience: health?.sample.audience || 'Curious adults with no networking background',
        durationSeconds: health?.sample.durationSeconds || 45,
        review: false,
      } : { ...value, topic: value.topic.trim(), audience: value.audience.trim() });
    }}>
      <fieldset disabled={disabled} className="form-fields">
        <legend className="sr-only">Video brief and settings</legend>
        <div className="source-switch" aria-label="Script source">
          <button type="button" aria-pressed={!sample} onClick={() => changeSource('topic')}><Sparkles size={15} />Your topic</button>
          <button type="button" aria-pressed={sample} onClick={() => changeSource('sample')}><FlaskConical size={15} />Try a sample</button>
        </div>

        {sample ? <div className="sample-brief">
          <span className="eyebrow">A READY-TO-USE SCRIPT</span>
          <h3>{health?.sample.title || 'How a Message Crosses the Internet'}</h3>
          <p>Watch a message travel from your laptop through the network to a receiver. Moving packets and a narrated story show how the pieces connect.</p>
          <div className="sample-note"><FlaskConical size={14} />No AI script request or API usage</div>
        </div> : <>
          <div className="field">
            <label htmlFor={`${id}-topic`}>What would you like to explain?</label>
            <div className={`textarea-wrap ${errors.topic ? 'has-error' : ''}`}>
              <textarea ref={topicRef} id={`${id}-topic`} value={value.topic} maxLength={500} rows={4}
                placeholder="An idea, a question, a story worth explaining…"
                aria-invalid={Boolean(errors.topic)} aria-describedby={errors.topic ? `${id}-topic-error` : `${id}-topic-hint`}
                onChange={(event) => { update({ topic: event.target.value }); setErrors((current) => ({ ...current, topic: undefined })); }} />
              <span className="character-count" aria-hidden="true">{value.topic.length}/500</span>
            </div>
            {errors.topic ? <p className="field-error" id={`${id}-topic-error`}>{errors.topic}</p> : <p className="field-hint" id={`${id}-topic-hint`}>A specific question makes a better story.</p>}
          </div>
          <div className="inspiration"><span>Try</span>{IDEAS.map((idea) => <button key={idea.label} type="button" onClick={() => { update({ topic: idea.topic }); setErrors({}); topicRef.current?.focus(); }}>{idea.label}<ArrowRight size={12} /></button>)}</div>
          <div className="field audience-field">
            <label htmlFor={`${id}-audience`}>Who’s watching?</label>
            <input ref={audienceRef} id={`${id}-audience`} value={value.audience} maxLength={200}
              placeholder="e.g. Curious adults, no prior knowledge"
              aria-invalid={Boolean(errors.audience)} aria-describedby={errors.audience ? `${id}-audience-error` : undefined}
              onChange={(event) => { update({ audience: event.target.value }); setErrors((current) => ({ ...current, audience: undefined })); }} />
            {errors.audience && <p className="field-error" id={`${id}-audience-error`}>{errors.audience}</p>}
          </div>
          <div className="field">
            <label htmlFor={`${id}-duration`}>Target length</label>
            <div className="select-wrap"><Clock3 size={16} aria-hidden="true" /><select id={`${id}-duration`} value={value.durationSeconds} onChange={(event) => update({ durationSeconds: Number(event.target.value) })}>
              {[30, 60, 90, 120, 180, 300, 420, 600].map((seconds) => <option key={seconds} value={seconds}>{seconds < 60 ? `${seconds} seconds` : seconds % 60 ? `${Math.floor(seconds / 60)} min ${seconds % 60} sec` : `${seconds / 60} minute${seconds === 60 ? '' : 's'}`}{seconds === 90 ? ' · Recommended' : ''}</option>)}
            </select><ChevronDown size={15} aria-hidden="true" /></div>
            <p className="field-hint">{value.durationSeconds > 180 ? 'Longer videos are planned chapter by chapter.' : 'The final length follows the narration and may vary.'}</p>
          </div>
        </>}

        <details className="video-settings">
          <summary><span>Video settings</span><span className="settings-summary">{value.theme === 'night' ? 'Night' : 'Light'} · {value.draft ? 'Draft' : '1080p'}<ChevronDown size={15} /></span></summary>
          <div className="settings-content">
            <div className="setting-row"><span id={`${id}-theme`}>Visual style</span><div className="theme-picker" role="group" aria-labelledby={`${id}-theme`}>
              <button type="button" aria-pressed={value.theme === 'light'} onClick={() => update({ theme: 'light' })}><span className="theme-dot light" />Light</button>
              <button type="button" aria-pressed={value.theme === 'night'} onClick={() => update({ theme: 'night' })}><span className="theme-dot night" />Night</button>
            </div></div>
            <label className="toggle-row"><span>Background music<small>A soft soundtrack under the narration</small></span><input type="checkbox" checked={value.music} onChange={(event) => update({ music: event.target.checked })} /><span className="toggle-track" aria-hidden="true" /></label>
            {!sample && <label className="toggle-row"><span>Review the script<small>Check clarity and flow before narration</small></span><input type="checkbox" checked={value.review} onChange={(event) => update({ review: event.target.checked })} /><span className="toggle-track" aria-hidden="true" /></label>}
            <label className="toggle-row"><span>Quick draft<small>540p for a faster first look</small></span><input type="checkbox" checked={value.draft} onChange={(event) => update({ draft: event.target.checked })} /><span className="toggle-track" aria-hidden="true" /></label>
          </div>
        </details>
      </fieldset>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <button className="primary-button generate-button" type="submit" disabled={disabled}>
        {submitting ? <><LoaderCircle size={18} className="spin" />Starting your video…</> : disabled ? <><LoaderCircle size={18} className="spin" />Generation in progress</> : <>{sample ? 'Generate sample video' : 'Generate video'}<ArrowRight size={18} /></>}
      </button>
      <p className="submission-note">{sample ? 'Uses the sample script with real narration and rendering.' : 'Uses your configured Claude API. API charges apply.'}</p>
    </form>
  </section>;
}
