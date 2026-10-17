import { ArrowRight, CircleAlert, LoaderCircle } from 'lucide-react';
import { useId, useState } from 'react';
import { api, type User } from '../api';
import Brand from './Brand';

const USERNAME = /^[A-Za-z0-9_.-]{3,32}$/;

type Props = { onSignedIn: (user: User) => void; notice: string };

export default function AuthScreen({ onSignedIn, notice }: Props) {
  const id = useId();
  const [mode, setMode] = useState<'signin' | 'register'>('signin');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [errors, setErrors] = useState<{ username?: string; password?: string; confirm?: string }>({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const register = mode === 'register';

  const switchMode = () => {
    setMode(register ? 'signin' : 'register');
    setErrors({});
    setError('');
    setConfirm('');
  };

  return <div className="app-shell auth-shell">
    <header className="app-header"><div className="header-inner"><Brand /></div></header>
    <main id="main-content" className="auth-page">
      <section className="auth-card" aria-labelledby="auth-heading">
        <div className="eyebrow"><span className="eyebrow-line" />{register ? 'NEW ACCOUNT' : 'WELCOME BACK'}</div>
        <h1 id="auth-heading">{register ? 'Create your studio account.' : 'Sign in to your studio.'}</h1>
        <p className="auth-intro">{register ? 'Your videos and their history stay with your account.' : 'Pick up where you left off. Your past videos are waiting.'}</p>
        {notice && !error && <div className="connection-banner" role="status">{notice}</div>}
        <form noValidate onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          const name = username.trim();
          const next: typeof errors = {};
          if (!USERNAME.test(name)) next.username = 'Use 3–32 letters, numbers, dots, dashes or underscores.';
          if (password.length < 8 || password.length > 128) next.password = 'Use 8–128 characters.';
          if (register && confirm !== password) next.confirm = 'The passwords do not match.';
          setErrors(next);
          setError('');
          if (Object.keys(next).length) return;
          setBusy(true);
          try {
            onSignedIn(await (register ? api.register(name, password) : api.login(name, password)));
          } catch (failure) {
            setError((failure as Error).message);
            setBusy(false);
          }
        }}>
          <div className="field">
            <label htmlFor={`${id}-username`}>Username</label>
            <input id={`${id}-username`} value={username} maxLength={32} autoComplete="username" autoCapitalize="none" spellCheck={false}
              aria-invalid={Boolean(errors.username)} aria-describedby={errors.username ? `${id}-username-error` : undefined}
              onChange={(event) => { setUsername(event.target.value); setErrors((current) => ({ ...current, username: undefined })); }} />
            {errors.username && <p className="field-error" id={`${id}-username-error`}>{errors.username}</p>}
          </div>
          <div className="field">
            <label htmlFor={`${id}-password`}>Password</label>
            <input id={`${id}-password`} type="password" value={password} maxLength={128} autoComplete={register ? 'new-password' : 'current-password'}
              aria-invalid={Boolean(errors.password)} aria-describedby={errors.password ? `${id}-password-error` : register ? `${id}-password-hint` : undefined}
              onChange={(event) => { setPassword(event.target.value); setErrors((current) => ({ ...current, password: undefined })); }} />
            {errors.password ? <p className="field-error" id={`${id}-password-error`}>{errors.password}</p> : register && <p className="field-hint" id={`${id}-password-hint`}>At least 8 characters.</p>}
          </div>
          {register && <div className="field">
            <label htmlFor={`${id}-confirm`}>Confirm password</label>
            <input id={`${id}-confirm`} type="password" value={confirm} maxLength={128} autoComplete="new-password"
              aria-invalid={Boolean(errors.confirm)} aria-describedby={errors.confirm ? `${id}-confirm-error` : undefined}
              onChange={(event) => { setConfirm(event.target.value); setErrors((current) => ({ ...current, confirm: undefined })); }} />
            {errors.confirm && <p className="field-error" id={`${id}-confirm-error`}>{errors.confirm}</p>}
          </div>}
          {error && <div className="inline-error auth-error" role="alert"><CircleAlert size={15} />{error}</div>}
          <button className="primary-button auth-submit" type="submit" disabled={busy}>
            {busy ? <><LoaderCircle size={17} className="spin" />{register ? 'Creating account…' : 'Signing in…'}</> : <>{register ? 'Create account' : 'Sign in'}<ArrowRight size={17} /></>}
          </button>
        </form>
        <p className="auth-switch">{register ? 'Already have an account?' : 'New to the studio?'}<button type="button" className="text-button" onClick={switchMode} disabled={busy}>{register ? 'Sign in' : 'Create an account'}</button></p>
      </section>
      <p className="auth-footnote">Accounts live on the computer running this studio. Nothing is sent to an outside sign-in service.</p>
    </main>
  </div>;
}
