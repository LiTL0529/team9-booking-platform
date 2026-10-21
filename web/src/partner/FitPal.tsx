import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, Booking, CallRecord, claims, maskedKey, onCall, partnerApi, signIn, signOut, Slot } from './partnerApi';
import { dayParts, isoDate, label, longDate, newKey, time } from '../format';
import { Icon } from '../ui';

type Tab = 'book' | 'mine';

function ApiPanel() {
  const [calls, setCalls] = useState<CallRecord[]>([]);
  useEffect(() => onCall((c) => setCalls((list) => [c, ...list].slice(0, 30))), []);
  return (
    <aside className="fp-api" aria-label="Live CourtHub API calls">
      <div className="fp-api-head">
        <span className="fp-live"><i />LIVE</span>
        <strong>CourtHub API calls from FitPal</strong>
        {calls.length > 0 && <button className="fp-link" onClick={() => setCalls([])}>Clear</button>}
      </div>
      <dl className="fp-api-meta">
        <div><dt>API key</dt><dd className="mono">{maskedKey()} · FitPal plan</dd></div>
        <div><dt>Usage plan</dt><dd>10 req/s · 50,000 per day</dd></div>
        <div><dt>Identity</dt><dd>FitPal's own Cognito app client</dd></div>
        <div><dt>Endpoints</dt><dd>Same /v1 API as the CourtHub web app</dd></div>
      </dl>
      {calls.length === 0 ? (
        <p className="fp-api-empty">Calls appear here as you use FitPal.</p>
      ) : (
        <ol className="fp-calls">
          {calls.map((c) => (
            <li key={c.id}>
              <span className={`fp-method ${c.method.toLowerCase()}`}>{c.method}</span>
              <span className="fp-path mono" title={c.path}>{c.path.split('?')[0]}</span>
              <span className={`fp-status s${String(c.status)[0]}`}>{c.status}</span>
              <span className="fp-ms">{c.ms} ms</span>
              {c.auth && <span className="fp-auth" title="Sent with the member's sign-in token"><Icon name="key" size={12} /></span>}
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}

function SignIn({ onDone }: { onDone: () => void }) {
  const [username, setUsername] = useState('partner');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await signIn(username.trim(), password);
      onDone();
    } catch (err) {
      const s = (err as ApiError).status;
      setError(s === 400 || s === 401 ? 'Username or password is not correct.' : (err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="fp-card fp-signin">
      <div className="fp-signin-art"><Icon name="zap" size={30} /></div>
      <h1>Welcome to FitPal</h1>
      <p className="fp-muted">Track your workouts and book a court at any partner venue, without leaving the app.</p>
      <form onSubmit={submit} className="fp-form">
        <label>Member name<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required /></label>
        <label>Password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required /></label>
        {error && <p className="fp-error">{error}</p>}
        <button className="fp-btn" disabled={busy}>{busy ? 'Signing in…' : 'Sign in to FitPal'}</button>
      </form>
      <p className="fp-fine">Demo member: partner</p>
    </section>
  );
}

function BookCourts() {
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => isoDate(i)), []);
  const [date, setDate] = useState(isoDate(1));
  const [types, setTypes] = useState<string[]>([]);
  const [type, setType] = useState('');
  const [slots, setSlots] = useState<Slot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [chosen, setChosen] = useState<Slot | null>(null);
  const [busy, setBusy] = useState(false);
  const [booked, setBooked] = useState<Booking | null>(null);

  useEffect(() => { partnerApi.resourceTypes().then(setTypes).catch(() => {}); }, []);
  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      setSlots((await partnerApi.slots(date, type)).slots);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [date, type]);
  useEffect(() => { load(); }, [load]);

  const courts = useMemo(() => {
    const map = new Map<string, { venue: string; court: string; type: string; slots: Slot[] }>();
    for (const s of slots) {
      const c = map.get(s.resource_id) ?? { venue: s.merchant_name, court: s.resource_name, type: s.resource_type, slots: [] };
      c.slots.push(s);
      map.set(s.resource_id, c);
    }
    return [...map.values()].sort((a, b) => (a.venue + a.court).localeCompare(b.venue + b.court));
  }, [slots]);

  const confirm = async () => {
    if (!chosen) return;
    setBusy(true);
    try {
      const b = await partnerApi.book(chosen.slot_id, newKey());
      setBooked(b);
      setSlots((list) => list.filter((s) => s.slot_id !== chosen.slot_id));
    } catch (err) {
      setChosen(null);
      setError((err as ApiError).status === 409 ? 'Someone just took that time. Pick another one.' : (err as Error).message);
      load();
    } finally {
      setBusy(false);
    }
  };
  const close = () => { if (!busy) { setChosen(null); setBooked(null); } };

  return (
    <>
      <div className="fp-days" role="group" aria-label="Choose a day">
        {days.map((d, i) => {
          const p = dayParts(d);
          return (
            <button key={d} className={`fp-day${d === date ? ' on' : ''}`} onClick={() => setDate(d)} aria-pressed={d === date}>
              <small>{i === 0 ? 'Today' : p.weekday}</small><strong>{p.day}</strong>
            </button>
          );
        })}
      </div>
      <div className="fp-chips" role="group" aria-label="Sport">
        <button className={`fp-chip${type === '' ? ' on' : ''}`} onClick={() => setType('')}>All sports</button>
        {types.map((t) => <button key={t} className={`fp-chip${type === t ? ' on' : ''}`} onClick={() => setType(t)}>{label(t)}</button>)}
      </div>
      {error && <p className="fp-error">{error}</p>}
      <p className="fp-count">{loading ? 'Finding courts…' : `${slots.length} open times · ${longDate(`${date}T12:00:00+08:00`)}`}</p>
      {!loading && courts.length === 0 && <div className="fp-card fp-empty">No open courts for this day. Try another day or sport.</div>}
      <div className="fp-courts">
        {courts.map((c) => (
          <article key={c.venue + c.court} className="fp-card fp-court">
            <div className="fp-court-head">
              <span className="fp-sport"><Icon name="court" size={18} /></span>
              <div><strong>{c.court}</strong><small>{c.venue} · {label(c.type)}</small></div>
            </div>
            <div className="fp-times">
              {c.slots.map((s) => <button key={s.slot_id} className="fp-time" onClick={() => { setBooked(null); setChosen(s); }}>{time(s.start_time)}</button>)}
            </div>
          </article>
        ))}
      </div>

      {chosen && (
        <div className="fp-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close()}>
          <div className="fp-sheet" role="dialog" aria-modal="true" aria-labelledby="fp-sheet-title">
            {booked ? (
              <>
                <div className="fp-done"><Icon name="check" size={28} /></div>
                <h2 id="fp-sheet-title">You're booked!</h2>
                <p className="fp-muted">{booked.resource_name} · {longDate(booked.start_time)}, {time(booked.start_time)}</p>
                <div className="fp-ref">{booked.reference}</div>
                <p className="fp-fine">Booked through CourtHub. The venue sees this booking in its own console.</p>
                <button className="fp-btn" onClick={close} autoFocus>Done</button>
              </>
            ) : (
              <>
                <h2 id="fp-sheet-title">Book this court?</h2>
                <dl className="fp-summary">
                  <div><dt>Court</dt><dd>{chosen.resource_name}</dd></div>
                  <div><dt>Venue</dt><dd>{chosen.merchant_name}</dd></div>
                  <div><dt>When</dt><dd>{longDate(chosen.start_time)}, {time(chosen.start_time)}–{time(chosen.end_time)}</dd></div>
                </dl>
                <div className="fp-actions">
                  <button className="fp-btn ghost" onClick={close} disabled={busy}>Not now</button>
                  <button className="fp-btn" onClick={confirm} disabled={busy} autoFocus>{busy ? 'Booking…' : 'Book with FitPal'}</button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function MyBookings() {
  const [list, setList] = useState<Booking[] | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => partnerApi.myBookings().then(setList).catch((e) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);
  const cancel = async (b: Booking) => {
    if (!window.confirm(`Cancel ${b.reference}?`)) return;
    try {
      await partnerApi.cancel(b.booking_id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };
  if (error) return <p className="fp-error">{error}</p>;
  if (!list) return <p className="fp-count">Loading…</p>;
  const sorted = [...list].sort((a, b) => b.created_at.localeCompare(a.created_at));
  if (!sorted.length) return <div className="fp-card fp-empty">No bookings yet. Book a court and it shows up here.</div>;
  return (
    <div className="fp-courts">
      {sorted.map((b) => {
        const upcoming = b.status === 'CONFIRMED' && new Date(b.start_time) > new Date();
        return (
          <article key={b.booking_id} className={`fp-card fp-booking${upcoming ? '' : ' dim'}`}>
            <div className="fp-court-head">
              <span className="fp-sport"><Icon name="ticket" size={18} /></span>
              <div><strong>{b.resource_name}</strong><small>{longDate(b.start_time)}, {time(b.start_time)} · <span className="mono">{b.reference}</span></small></div>
            </div>
            <div className="fp-booking-side">
              <span className={`fp-pill ${b.status.toLowerCase()}`}>{b.status}</span>
              {upcoming && <button className="fp-link" onClick={() => cancel(b)}>Cancel</button>}
            </div>
          </article>
        );
      })}
    </div>
  );
}

export default function FitPal() {
  const [user, setUser] = useState(claims());
  const [tab, setTab] = useState<Tab>('book');
  return (
    <div className="fp-shell">
      <header className="fp-top">
        <div className="fp-brand"><span className="fp-logo"><Icon name="zap" size={18} /></span>FitPal<small>Stay active</small></div>
        <span className="fp-powered">Courts powered by <strong>CourtHub</strong> API</span>
        {user && (
          <div className="fp-user">
            <span>{user.username}</span>
            <button className="fp-link" onClick={() => { signOut(); setUser(null); }}>Sign out</button>
          </div>
        )}
      </header>
      <div className="fp-layout">
        <main className="fp-main">
          {!user ? <SignIn onDone={() => setUser(claims())} /> : (
            <>
              <h1 className="fp-hello">Ready to play, {user.username}?</h1>
              <div className="fp-tabs" role="tablist">
                <button role="tab" aria-selected={tab === 'book'} className={tab === 'book' ? 'on' : ''} onClick={() => setTab('book')}>Book a court</button>
                <button role="tab" aria-selected={tab === 'mine'} className={tab === 'mine' ? 'on' : ''} onClick={() => setTab('mine')}>My FitPal bookings</button>
              </div>
              {tab === 'book' ? <BookCourts /> : <MyBookings />}
            </>
          )}
          <p className="fp-fine fp-disclaimer">FitPal is a fictional partner app built for the Team 9 demonstration. It holds no booking logic or data of its own.</p>
        </main>
        <ApiPanel />
      </div>
    </div>
  );
}
