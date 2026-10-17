import { LoaderCircle } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { api, ApiError, onSignedOut, type User } from './api';
import AuthScreen from './components/AuthScreen';
import Studio from './Studio';

/** Checks the session cookie, then shows sign-in or the signed-in studio. */
export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(true);
  const [notice, setNotice] = useState('');

  const check = useCallback(async () => {
    setChecking(true);
    try {
      setUser(await api.me());
      setNotice('');
    } catch (error) {
      setUser(null);
      if (!(error instanceof ApiError && error.status === 401)) setNotice((error as Error).message);
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => { void check(); }, [check]);
  useEffect(() => {
    onSignedOut(() => { setUser(null); setNotice('Your session has ended. Sign in again to continue.'); });
    return () => onSignedOut(null);
  }, []);

  if (checking) return <div className="auth-loading" role="status"><LoaderCircle size={20} className="spin" />Opening your studio…</div>;
  if (!user) return <AuthScreen notice={notice} onSignedIn={(signedIn) => { setNotice(''); setUser(signedIn); }} />;
  return <Studio key={user.id} user={user} onSignOut={async () => {
    try { await api.logout(); } catch { /* If the server is unreachable, its session still ends when the cookie expires. */ }
    setNotice('');
    setUser(null);
  }} />;
}
