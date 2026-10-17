import { FormEvent, useEffect, useState } from 'react';
import { api, Booking, Merchant, Resource } from '../api';
import { dateTime, isoDate, label } from '../format';

export default function MerchantConsole() {
  const [merchant, setMerchant] = useState<Merchant | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [newResource, setNewResource] = useState({ name: '', resource_type: 'badminton_court', description: '' });
  const [schedule, setSchedule] = useState({ resourceId: '', from: isoDate(1), to: isoDate(7), start: 9, end: 21 });

  const load = async (m: Merchant) => {
    setResources(await api.resources(m.merchant_id));
    setBookings(await api.merchantBookings(m.merchant_id));
  };

  useEffect(() => {
    api.myMerchant()
      .then((m) => {
        setMerchant(m);
        return load(m);
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error && !merchant) return <p className="error">{error}</p>;
  if (!merchant) return <p className="muted">Loading…</p>;

  const addResource = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      await api.createResource({ merchant_id: merchant.merchant_id, ...newResource });
      setNewResource({ ...newResource, name: '', description: '' });
      await load(merchant);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const publish = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setMessage('');
    try {
      const r = await api.publishSlots(schedule.resourceId, {
        from_date: schedule.from, to_date: schedule.to, start_hour: schedule.start, end_hour: schedule.end,
        skip_existing: true,
      });
      setMessage(`Published ${r.created} slots (${r.skipped_existing} already existed, ${r.skipped_past} in the past).`);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section>
      <h1>{merchant.name}</h1>
      <p className="muted">Merchant console · {merchant.slug}</p>
      {message && <p className="notice">{message}</p>}
      {error && <p className="error">{error}</p>}
      <div className="grid2">
        <article className="card">
          <h2>Resources</h2>
          <ul className="plain">
            {resources.map((r) => (
              <li key={r.resource_id}>{r.name} <span className="tag">{label(r.resource_type)}</span></li>
            ))}
          </ul>
          <form onSubmit={addResource} className="stack">
            <input placeholder="Name, e.g. Court 3" value={newResource.name} required
              onChange={(e) => setNewResource({ ...newResource, name: e.target.value })} />
            <input placeholder="Type, e.g. badminton_court" value={newResource.resource_type} pattern="[a-z0-9_]+" required
              onChange={(e) => setNewResource({ ...newResource, resource_type: e.target.value })} />
            <button type="submit">Add resource</button>
          </form>
        </article>
        <article className="card">
          <h2>Publish one-hour slots</h2>
          <form onSubmit={publish} className="stack">
            <select value={schedule.resourceId} required onChange={(e) => setSchedule({ ...schedule, resourceId: e.target.value })}>
              <option value="">Choose a resource</option>
              {resources.map((r) => <option key={r.resource_id} value={r.resource_id}>{r.name}</option>)}
            </select>
            <div className="row">
              <label>From<input type="date" value={schedule.from} onChange={(e) => setSchedule({ ...schedule, from: e.target.value })} /></label>
              <label>To<input type="date" value={schedule.to} onChange={(e) => setSchedule({ ...schedule, to: e.target.value })} /></label>
            </div>
            <div className="row">
              <label>First hour<input type="number" min={0} max={23} value={schedule.start}
                onChange={(e) => setSchedule({ ...schedule, start: Number(e.target.value) })} /></label>
              <label>Last hour ends<input type="number" min={1} max={24} value={schedule.end}
                onChange={(e) => setSchedule({ ...schedule, end: Number(e.target.value) })} /></label>
            </div>
            <button type="submit">Publish slots</button>
          </form>
        </article>
      </div>
      <article className="card">
        <h2>Bookings <button className="small link" onClick={() => load(merchant)}>refresh</button></h2>
        <table className="table">
          <thead><tr><th>Reference</th><th>When</th><th>Resource</th><th>Customer</th><th>Status</th></tr></thead>
          <tbody>
            {bookings.map((b) => (
              <tr key={b.booking_id} className={b.status === 'CANCELLED' ? 'dim' : ''}>
                <td><code>{b.reference}</code></td>
                <td>{dateTime(b.start_time)}</td>
                <td>{b.resource_name}</td>
                <td>{b.customer_username}</td>
                <td><span className={`status ${b.status.toLowerCase()}`}>{b.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </article>
    </section>
  );
}
