import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { api, ApiError, Merchant, Slot } from '../api';
import { useSession } from '../App';
import { isoDate, label, newKey, time } from '../format';

export default function Browse() {
  const { user } = useSession();
  const navigate = useNavigate();
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [date, setDate] = useState(isoDate(1));
  const [merchantId, setMerchantId] = useState('');
  const [resourceType, setResourceType] = useState('');
  const [slots, setSlots] = useState<Slot[]>([]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    api.merchants().then(setMerchants).catch(() => {});
    api.resourceTypes().then(setTypes).catch(() => {});
  }, []);

  const search = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, string> = { date, limit: '500' };
      if (merchantId) params.merchant_id = merchantId;
      if (resourceType) params.resource_type = resourceType;
      setSlots((await api.searchSlots(params)).slots);
    } catch (err) {
      setMessage({ kind: 'error', text: (err as Error).message });
    } finally {
      setLoading(false);
    }
  }, [date, merchantId, resourceType]);

  useEffect(() => {
    search();
  }, [search]);

  const grouped = useMemo(() => {
    const map = new Map<string, Slot[]>();
    for (const s of slots) {
      const key = `${s.merchant_name} · ${s.resource_name}`;
      map.set(key, [...(map.get(key) ?? []), s]);
    }
    return [...map.entries()];
  }, [slots]);

  const book = async (slot: Slot) => {
    if (!user) return navigate('/login');
    setPending(slot.slot_id);
    setMessage(null);
    try {
      const booking = await api.book(slot.slot_id, newKey());
      setMessage({ kind: 'ok', text: `Booked ${booking.resource_name} at ${time(booking.start_time)} — reference ${booking.reference}` });
      setSlots((current) => current.filter((s) => s.slot_id !== slot.slot_id));
    } catch (err) {
      const e = err as ApiError;
      setMessage({
        kind: 'error',
        text: e.status === 409 ? 'Someone just booked that slot. The list has been refreshed.' : e.message,
      });
      if (e.status === 409) search();
    } finally {
      setPending(null);
    }
  };

  const canBook = !user || user.groups.includes('customer');

  return (
    <section>
      <div className="hero">
        <h1>Find a court across every venue</h1>
        <p>One search over all participating merchants. Pick a slot and it is yours in one click.</p>
      </div>
      <div className="filters card">
        <label>Date<input type="date" value={date} min={isoDate(0)} onChange={(e) => setDate(e.target.value)} /></label>
        <label>Venue
          <select value={merchantId} onChange={(e) => setMerchantId(e.target.value)}>
            <option value="">All venues</option>
            {merchants.map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name}</option>)}
          </select>
        </label>
        <label>Type
          <select value={resourceType} onChange={(e) => setResourceType(e.target.value)}>
            <option value="">All types</option>
            {types.map((t) => <option key={t} value={t}>{label(t)}</option>)}
          </select>
        </label>
        <button onClick={search} disabled={loading}>{loading ? 'Searching…' : 'Refresh'}</button>
      </div>
      {message && <p className={message.kind === 'ok' ? 'notice' : 'error'}>{message.text}</p>}
      {!loading && slots.length === 0 && <p className="muted center">No available slots for these filters.</p>}
      <div className="resource-list">
        {grouped.map(([name, items]) => (
          <article key={name} className="card resource">
            <header>
              <h3>{name}</h3>
              <span className="tag">{label(items[0].resource_type)}</span>
            </header>
            <div className="slots">
              {items.map((s) => (
                <button
                  key={s.slot_id}
                  className="slot"
                  disabled={!canBook || pending === s.slot_id}
                  onClick={() => book(s)}
                  title={canBook ? 'Book this slot' : 'Sign in as a customer to book'}
                >
                  {time(s.start_time)}–{time(s.end_time)}
                </button>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
