import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Booking } from '../api';
import { NOTIFICATIONS_CHANGED } from '../App';
import { dateParts, label, longDate, time } from '../format';
import { Alert, Dialog, Empty, Icon, PageHeader, Pill, Spinner, useToast } from '../ui';

type Tab = 'upcoming' | 'past';

export default function MyBookings() {
  const toast = useToast();
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [venues, setVenues] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('upcoming');
  const [cancelling, setCancelling] = useState<Booking | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => api.myBookings()
    .then((b) => { setBookings(b); setError(''); })
    .catch((e) => setError(e.message))
    .finally(() => setLoading(false)), []);

  useEffect(() => {
    load();
    api.merchants().then((ms) => setVenues(Object.fromEntries(ms.map((m) => [m.merchant_id, m.name])))).catch(() => {});
  }, [load]);

  const isUpcoming = (b: Booking) => b.status === 'CONFIRMED' && new Date(b.start_time) > new Date();
  const upcoming = useMemo(() => bookings.filter(isUpcoming)
    .sort((a, b) => a.start_time.localeCompare(b.start_time)), [bookings]);
  const past = useMemo(() => bookings.filter((b) => !isUpcoming(b))
    .sort((a, b) => b.start_time.localeCompare(a.start_time)), [bookings]);
  const shown = tab === 'upcoming' ? upcoming : past;

  const cancel = async () => {
    if (!cancelling) return;
    setBusy(true);
    try {
      await api.cancel(cancelling.booking_id);
      toast('ok', `${cancelling.reference} cancelled. The slot is free for others again.`);
      setCancelling(null);
      await load();
      window.setTimeout(() => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED)), 2500);
    } catch (e) {
      toast('error', (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section>
      <PageHeader eyebrow="Your account" title="My bookings"
        lead="Upcoming bookings can be cancelled until they start. Cancelling frees the court for other players straight away."
        actions={<Link to="/" className="button"><Icon name="plus" size={16} />Book a court</Link>} />

      <div className="toolbar">
        <div className="tabs" role="tablist" aria-label="Booking list">
          <button role="tab" aria-selected={tab === 'upcoming'} className={tab === 'upcoming' ? 'on' : ''} onClick={() => setTab('upcoming')}>
            Upcoming <span className="n">{upcoming.length}</span>
          </button>
          <button role="tab" aria-selected={tab === 'past'} className={tab === 'past' ? 'on' : ''} onClick={() => setTab('past')}>
            Past and cancelled <span className="n">{past.length}</span>
          </button>
        </div>
      </div>

      {error && <Alert kind="error">{error}</Alert>}

      {loading ? (
        <div className="booking-list">
          {[0, 1].map((i) => <div key={i} className="card booking"><div className="skeleton" style={{ height: 64 }} /><div className="skeleton" style={{ height: 40 }} /></div>)}
        </div>
      ) : shown.length === 0 ? (
        tab === 'upcoming'
          ? <Empty icon="ticket" title="No upcoming bookings" text="Find a free court at any venue and it will show up here."
              action={<Link to="/" className="button">Find a slot<Icon name="arrowRight" size={16} /></Link>} />
          : <Empty icon="clock" title="Nothing here yet" text="Past and cancelled bookings will be listed here." />
      ) : (
        <div className="booking-list">
          {shown.map((b) => {
            const p = dateParts(b.start_time);
            const active = isUpcoming(b);
            const tone = b.status === 'CANCELLED' ? 'cancelled' : active ? 'confirmed' : 'past';
            return (
              <article key={b.booking_id} className={`card booking${active ? '' : ' dim'}`}>
                <div className="date-block" aria-hidden><small>{p.weekday}</small><strong>{p.day}</strong><span>{p.month}</span></div>
                <div>
                  <h3>{b.resource_name}</h3>
                  <div className="meta">
                    {venues[b.merchant_id] && <span><Icon name="building" size={14} />{venues[b.merchant_id]}</span>}
                    <span><Icon name="clock" size={14} />{time(b.start_time)}–{time(b.end_time)}</span>
                    <span className="tag">{label(b.resource_type)}</span>
                    <span className="mono">{b.reference}</span>
                  </div>
                </div>
                <div className="actions row">
                  <Pill tone={tone}>{b.status === 'CONFIRMED' && !active ? 'COMPLETED' : b.status}</Pill>
                  {active && <button className="btn-danger-soft btn-sm" onClick={() => setCancelling(b)}>Cancel</button>}
                </div>
              </article>
            );
          })}
        </div>
      )}

      {cancelling && (
        <Dialog title="Cancel this booking?" onClose={() => !busy && setCancelling(null)}>
          <p className="sub">The court becomes available to other players immediately. This cannot be undone.</p>
          <dl className="summary">
            <div><dt>Reference</dt><dd className="mono">{cancelling.reference}</dd></div>
            <div><dt>Court</dt><dd>{cancelling.resource_name}</dd></div>
            <div><dt>When</dt><dd>{longDate(cancelling.start_time)}, {time(cancelling.start_time)}</dd></div>
          </dl>
          <div className="dialog-actions">
            <button className="btn-secondary" onClick={() => setCancelling(null)} disabled={busy} data-autofocus>Keep booking</button>
            <button className="btn-danger" onClick={cancel} disabled={busy}>{busy && <Spinner />}Cancel booking</button>
          </div>
        </Dialog>
      )}
    </section>
  );
}
