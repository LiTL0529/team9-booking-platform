import { FormEvent, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { signIn } from '../api';
import { useSession } from '../App';

const DEMO_USERS = [
  { username: 'alice', role: 'Customer' },
  { username: 'bob', role: 'Customer' },
  { username: 'owner1', role: 'Merchant admin (City Courts)' },
  { username: 'owner2', role: 'Merchant admin (Eastside)' },
  { username: 'admin', role: 'Platform admin' },
];

export default function Login() {
  const { setUser } = useSession();
  const navigate = useNavigate();
  const [username, setUsername] = useState('alice');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const claims = await signIn(username, password);
      setUser(claims);
      if (claims.groups.includes('platform_admin')) navigate('/admin');
      else if (claims.groups.some((g) => g.startsWith('merchant_'))) navigate('/merchant');
      else navigate('/');
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section className="card narrow">
      <h1>Sign in</h1>
      <form onSubmit={submit} className="stack">
        <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
        {error && <p className="error">{error}</p>}
        <button type="submit">Sign in</button>
      </form>
      <details className="hint">
        <summary>Local demo accounts</summary>
        <ul>
          {DEMO_USERS.map((u) => (
            <li key={u.username}>
              <button className="link" type="button" onClick={() => setUsername(u.username)}>{u.username}</button> — {u.role}
            </li>
          ))}
        </ul>
        <p className="muted">Passwords are in <code>local/dev-auth/users.json</code>. Merchant roles appear after onboarding.</p>
      </details>
    </section>
  );
}
