import { FormEvent, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { ApiError, signIn } from '../api';
import { useSession } from '../App';
import { Alert, Icon, Spinner, useToast } from '../ui';

const DEMO_USERS = [
  { username: 'alice', role: 'Customer' },
  { username: 'bob', role: 'Customer' },
  { username: 'owner1', role: 'City Courts' },
  { username: 'owner2', role: 'Eastside' },
  { username: 'admin', role: 'Platform admin' },
];

export default function Login() {
  const { setUser } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const from = (location.state as { from?: string } | null)?.from;
  const [username, setUsername] = useState('alice');
  const [password, setPassword] = useState('');
  const [show, setShow] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const claims = await signIn(username.trim(), password);
      setUser(claims);
      toast('ok', `Signed in as ${claims.username}`);
      const home = claims.groups.includes('platform_admin') ? '/admin'
        : claims.groups.some((g) => g.startsWith('merchant_')) ? '/merchant' : '/';
      navigate(from && from !== '/' && from !== '/login' ? from : home, { replace: true });
    } catch (err) {
      const status = (err as ApiError).status;
      setError(status === 400 || status === 401 ? 'The username or password is not correct.' : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="auth">
      <aside className="auth-aside">
        <span className="brand-mark" style={{ background: 'rgba(255,255,255,0.16)' }}><Icon name="court" size={20} /></span>
        <h2>Every venue's courts, one place to book them.</h2>
        <ul>
          <li><Icon name="search" />Search free times across all venues at once</li>
          <li><Icon name="zap" />Confirm in one step and get a reference immediately</li>
          <li><Icon name="bell" />Confirmations and cancellations arrive in your inbox</li>
          <li><Icon name="building" />Venue owners manage their own courts and bookings</li>
        </ul>
      </aside>
      <div className="auth-main">
        <h1>Sign in</h1>
        <p className="sub">{from && from !== '/' ? 'Sign in to continue where you left off.' : 'Welcome back to CourtHub.'}</p>
        <form onSubmit={submit} className="stack">
          <label className="field">Username
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
          </label>
          <label className="field">Password
            <span className="input-wrap">
              <input type={show ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password" required style={{ paddingRight: 44 }} />
              <button type="button" className="btn-ghost icon-btn" onClick={() => setShow((s) => !s)}
                aria-label={show ? 'Hide password' : 'Show password'}><Icon name={show ? 'eyeOff' : 'eye'} size={17} /></button>
            </span>
          </label>
          {error && <Alert kind="error">{error}</Alert>}
          <button type="submit" className="btn-lg btn-block" disabled={busy}>
            {busy ? <Spinner /> : <Icon name="arrowRight" size={17} />}Sign in
          </button>
        </form>
        <div className="quick">
          <p>Demo accounts</p>
          <div className="quick-users">
            {DEMO_USERS.map((u) => (
              <button key={u.username} type="button" className={username === u.username ? 'on' : ''}
                onClick={() => setUsername(u.username)}>
                {u.username} <em>· {u.role}</em>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
