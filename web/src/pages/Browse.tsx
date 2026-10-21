import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { api, ApiError, Booking, Merchant, Slot } from '../api';
import { isCustomer, NOTIFICATIONS_CHANGED, useSession } from '../App';
import { dayParts, hourOf, isoDate, label, longDate, newKey, nextDay, time } from '../format';
import { Alert, Dialog, Empty, Icon, Spinner, useToast } from '../ui';

const PERIODS = [
  { key: 'morning', name: 'Morning', icon: 'sunrise', test: (h: number) => h < 12 },
  { key: 'afternoon', name: 'Afternoon', icon: 'sun', test: (h: number) => h >= 12 && h < 17 },
  { key: 'evening', name: 'Evening', icon: 'moon', test: (h: number) => h >= 17 },
];

interface ResourceGroup { id: string; name: string; type: string; slots: Slot[] }
interface VenueGroup { id: string; name: string; resources: ResourceGroup[]; count: number }

export default function Browse() {
  const { user } = useSession();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const date = params.get('date') || isoDate(1);
  const merchantId = params.get('venue') || '';
  const resourceType = params.get('type') || '';

  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Slot | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [booked, setBooked] = useState<Booking | null>(null);

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value); else next.delete(key);
    setParams(next, { replace: true });
  };

  useEffect(() => {
    api.merchants().then(setMerchants).catch(() => {});
    api.resourceTypes().then(setTypes).catch(() => {});
  }, []);

  const search = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const query: Record<string, string> = { date, limit: '500' };
      if (merchantId) query.merchant_id = merchantId;
      if (resourceType) query.resource_type = resourceType;
      setSlots((await api.searchSlots(query)).slots);
    } catch (err) {
      setError((err as Error).message);
      setSlots([]);
    } finally {
      setLoading(false);
    }
  }, [date, merchantId, resourceType]);

  useEffect(() => {
    search();
  }, [search]);

  const venues = useMemo<VenueGroup[]>(() => {
    const byVenue = new Map<string, VenueGroup>();
    for (const s of slots) {
      const venue = byVenue.get(s.merchant_id) ?? { id: s.merchant_id, name: s.merchant_name, resources: [], count: 0 };
      let resource = venue.resources.find((r) => r.id === s.resource_id);
      if (!resource) {
        resource = { id: s.resource_id, name: s.resource_name, type: s.resource_type, slots: [] };
        venue.resources.push(resource);
      }
      resource.slots.push(s);
      venue.count += 1;
      byVenue.set(s.merchant_id, venue);
    }
    const venuesSorted = [...byVenue.values()].sort((a, b) => a.name.localeCompare(b.name));
    for (const v of venuesSorted) {
      v.resources.sort((a, b) => a.name.localeCompare(b.name));
      for (const r of v.resources) r.slots.sort((a, b) => a.start_time.localeCompare(b.start_time));
    }
    return venuesSorted;
  }, [slots]);

  const canBook = !user || isCustomer(user);
  const days = useMemo(() => Array.from({ length: 7 }, (_, i) => isoDate(i)), []);
  const customDate = !days.includes(date);

  // Keep the chosen day visible when the strip scrolls sideways on narrow screens.
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = strip.current;
    const chosen = box?.querySelector<HTMLElement>('.day.selected');
    if (box && chosen) box.scrollLeft = chosen.offsetLeft - box.offsetLeft - (box.clientWidth - chosen.offsetWidth) / 2;
  }, [date]);

  const choose = (slot: Slot) => {
    if (!user) {
      toast('ok', 'Sign in to book. We will bring you back to this search.');
      navigate('/login', { state: { from: location.pathname + location.search } });
      return;
    }
    setBooked(null);
    setSelected(slot);
  };

  const confirm = async () => {
    if (!selected) return;
    setSubmitting(true);
    try {
      const booking = await api.book(selected.slot_id, newKey());
      setBooked(booking);
      setSlots((current) => current.filter((s) => s.slot_id !== selected.slot_id));
      window.setTimeout(() => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED)), 2500);
    } catch (err) {
      const e = err as ApiError;
      setSelected(null);
      toast('error', e.status === 409 ? 'Someone just booked that slot. The list has been refreshed.' : e.message);
      if (e.status === 409) search();
    } finally {
      setSubmitting(false);
    }
  };

  const closeDialog = () => {
    if (submitting) return;
    setSelected(null);
    setBooked(null);
  };

  return (
    <section>
      <div className="hero">
        <h1>Find a court across every venue</h1>
        <p>One search over every participating venue. Choose a time, confirm, and you get a booking reference straight away.</p>
        <div className="hero-stats">
          <div><strong>{merchants.length || '–'}</strong>venues</div>
          <div><strong>{types.length || '–'}</strong>court types</div>
          <div><strong>{loading ? '…' : slots.length}</strong>free slots on {dayParts(date).day} {dayParts(date).month}</div>
        </div>
      </div>

      <div className="card search-panel">
        <div className="date-strip" role="group" aria-label="Choose a date" ref={strip}>
          {days.map((d, i) => {
            const p = dayParts(d);
            return (
              <button key={d} type="button" className={`day${d === date ? ' selected' : ''}`} aria-pressed={d === date}
                onClick={() => setFilter('date', d)}>
                <small>{i === 0 ? 'Today' : p.weekday}</small><span>{p.day}</span><em>{p.month}</em>
              </button>
            );
          })}
          <label className={`day pick${customDate ? ' selected' : ''}`} title="Pick another date">
            <Icon name="calendar" size={20} />
            <small>{customDate ? `${dayParts(date).day} ${dayParts(date).month}` : 'More'}</small>
            <input type="date" aria-label="Date" value={date} min={isoDate(0)} onChange={(e) => e.target.value && setFilter('date', e.target.value)} />
          </label>
        </div>
        <div className="filters">
          <label className="field">Venue
            <select value={merchantId} onChange={(e) => setFilter('venue', e.target.value)}>
              <option value="">All venues</option>
              {merchants.map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name}</option>)}
            </select>
          </label>
          <label className="field">Type
            <select value={resourceType} onChange={(e) => setFilter('type', e.target.value)}>
              <option value="">All types</option>
              {types.map((t) => <option key={t} value={t}>{label(t)}</option>)}
            </select>
          </label>
          <button className="btn-secondary" onClick={search} disabled={loading}>
            {loading ? <Spinner /> : <Icon name="refresh" size={16} />}Refresh
          </button>
        </div>
      </div>

      {user && !canBook && (
        <div className="section"><Alert kind="info">You are signed in as <strong>{user.username}</strong>. Bookings are made by customer accounts, so the times below are read-only.</Alert></div>
      )}
      {error && <div className="section"><Alert kind="error">{error}</Alert></div>}

      <div className="results-bar">
        <h2>{longDate(`${date}T12:00:00+08:00`)}</h2>
        {!loading && <span className="muted">{slots.length} free {slots.length === 1 ? 'slot' : 'slots'} at {venues.length} {venues.length === 1 ? 'venue' : 'venues'}</span>}
        <span className="spacer" />
        <span className="legend"><span><i />Free · 1 hour</span></span>
      </div>

      {loading ? (
        <div className="resource-grid" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card resource">
              <div className="skeleton" style={{ width: 220, height: 18, marginBottom: 16 }} />
              <div className="slots">{Array.from({ length: 8 }, (_, j) => <div key={j} className="skeleton" style={{ width: 96, height: 34 }} />)}</div>
            </div>
          ))}
        </div>
      ) : venues.length === 0 && !error ? (
        <Empty icon="calendar" title="No free slots for these filters"
          text="Every court is taken, or no venue has published times for this day yet."
          action={<button className="btn-secondary" onClick={() => setFilter('date', nextDay(date))}>
            Try the next day<Icon name="arrowRight" size={16} /></button>} />
      ) : (
        venues.map((v) => (
          <section key={v.id} className="venue" aria-label={v.name}>
            <div className="venue-head">
              <span className="venue-icon"><Icon name="building" size={17} /></span>
              <h2>{v.name}</h2>
              <span className="count">{v.count} free</span>
            </div>
            <div className="resource-grid">
              {v.resources.map((r) => (
                <article key={r.id} className="card resource">
                  <div className="resource-top">
                    <h3>{r.name}</h3>
                    <span className="tag">{label(r.type)}</span>
                    <span className="spacer" />
                    <span className="free-count">{r.slots.length} free</span>
                  </div>
                  {PERIODS.map((p) => {
                    const list = r.slots.filter((s) => p.test(hourOf(s.start_time)));
                    if (!list.length) return null;
                    return (
                      <div key={p.key} className="period">
                        <div className="period-label"><Icon name={p.icon} size={15} />{p.name}</div>
                        <div className="slots">
                          {list.map((s) => (
                            <button key={s.slot_id} className="slot" disabled={!canBook} onClick={() => choose(s)}
                              title={canBook ? `Book ${r.name} at ${time(s.start_time)}` : 'Sign in as a customer to book'}>
                              {time(s.start_time)}–{time(s.end_time)}
                            </button>
                          ))}
                        </div>
                      </div>
                    );
                  })}
                </article>
              ))}
            </div>
          </section>
        ))
      )}

      {selected && (
        <Dialog key={booked ? 'done' : 'confirm'} onClose={closeDialog} labelledBy="book-title">
          {booked ? (
            <div>
              <div className="success-mark"><Icon name="check" size={30} /></div>
              <h2 id="book-title">Booking confirmed</h2>
              <p className="sub" style={{ marginBottom: 0 }}>{booked.resource_name} · {longDate(booked.start_time)}, {time(booked.start_time)}–{time(booked.end_time)}</p>
              <div className="reference" aria-label="Booking reference">{booked.reference}</div>
              <p className="muted" style={{ fontSize: '0.85rem' }}>A confirmation is on its way to your inbox.</p>
              <div className="dialog-actions">
                <button className="btn-secondary" onClick={closeDialog}>Book another</button>
                <Link className="button" to="/bookings" data-autofocus>View my bookings<Icon name="arrowRight" size={16} /></Link>
              </div>
            </div>
          ) : (
            <div>
              <h2 id="book-title">Confirm your booking</h2>
              <p className="sub">One hour, held for you as soon as you confirm.</p>
              <dl className="summary">
                <div><dt>Venue</dt><dd>{selected.merchant_name}</dd></div>
                <div><dt>Court</dt><dd>{selected.resource_name}</dd></div>
                <div><dt>Date</dt><dd>{longDate(selected.start_time)}</dd></div>
                <div><dt>Time</dt><dd>{time(selected.start_time)}–{time(selected.end_time)}</dd></div>
                <div><dt>Booked as</dt><dd>{user?.username}</dd></div>
              </dl>
              <div className="dialog-actions">
                <button className="btn-secondary" onClick={closeDialog} disabled={submitting}>Back</button>
                <button onClick={confirm} disabled={submitting} data-autofocus>
                  {submitting ? <Spinner /> : <Icon name="check" size={16} />}Confirm booking
                </button>
              </div>
            </div>
          )}
        </Dialog>
      )}
    </section>
  );
}
