import { FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import { api, Booking, Merchant, Resource } from '../api';
import { dateTime, isoDate, label } from '../format';
import { Alert, Empty, Icon, PageHeader, Pill, Spinner, useToast } from '../ui';

type Filter = 'upcoming' | 'all' | 'cancelled';

const dayCount = (from: string, to: string) =>
  Math.floor((new Date(`${to}T00:00:00Z`).getTime() - new Date(`${from}T00:00:00Z`).getTime()) / 86400000) + 1;

export default function MerchantConsole() {
  const toast = useToast();
  const [merchant, setMerchant] = useState<Merchant | null>(null);
  const [resources, setResources] = useState<Resource[]>([]);
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [types, setTypes] = useState<string[]>([]);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [filter, setFilter] = useState<Filter>('upcoming');
  const [query, setQuery] = useState('');
  const [newResource, setNewResource] = useState({ name: '', resource_type: 'badminton_court', description: '' });
  const [schedule, setSchedule] = useState({ resourceId: '', from: isoDate(1), to: isoDate(7), start: 9, end: 21 });
  const [saving, setSaving] = useState<'' | 'resource' | 'slots'>('');

  const load = useCallback(async (m: Merchant) => {
    setRefreshing(true);
    try {
      const [r, b] = await Promise.all([api.resources(m.merchant_id), api.merchantBookings(m.merchant_id)]);
      setResources(r);
      setBookings(b);
    } catch (e) {
      toast('error', (e as Error).message);
    } finally {
      setRefreshing(false);
    }
  }, [toast]);

  useEffect(() => {
    api.myMerchant().then((m) => { setMerchant(m); return load(m); }).catch((e) => setError(e.message));
    api.resourceTypes().then(setTypes).catch(() => {});
  }, [load]);

  const now = Date.now();
  const today = isoDate(0);
  const stats = useMemo(() => ({
    upcoming: bookings.filter((b) => b.status === 'CONFIRMED' && new Date(b.start_time).getTime() > now).length,
    today: bookings.filter((b) => b.status === 'CONFIRMED' && b.local_date === today).length,
    cancelled: bookings.filter((b) => b.status === 'CANCELLED').length,
  }), [bookings, now, today]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return bookings
      .filter((b) => filter === 'all' ? true : filter === 'cancelled' ? b.status === 'CANCELLED'
        : b.status === 'CONFIRMED' && new Date(b.start_time).getTime() > now)
      .filter((b) => !q || [b.reference, b.customer_username, b.resource_name].some((v) => v.toLowerCase().includes(q)))
      .sort((a, b) => (filter === 'upcoming' ? a.start_time.localeCompare(b.start_time) : b.start_time.localeCompare(a.start_time)));
  }, [bookings, filter, query, now]);

  if (error && !merchant) return <Alert kind="error">{error}</Alert>;
  if (!merchant) return <div className="stack"><div className="skeleton" style={{ height: 60 }} /><div className="skeleton" style={{ height: 240 }} /></div>;

  const hours = Math.max(0, schedule.end - schedule.start);
  const days = Math.max(0, dayCount(schedule.from, schedule.to));
  const scheduleError = schedule.end <= schedule.start ? 'The last hour must end after the first hour.'
    : days <= 0 ? 'The end date must be on or after the start date.' : '';

  const addResource = async (e: FormEvent) => {
    e.preventDefault();
    setSaving('resource');
    try {
      const r = await api.createResource({ merchant_id: merchant.merchant_id, ...newResource });
      toast('ok', `${r.name} added. Publish slots so customers can book it.`);
      setNewResource({ ...newResource, name: '', description: '' });
      setSchedule((s) => ({ ...s, resourceId: r.resource_id }));
      await load(merchant);
    } catch (err) {
      toast('error', (err as Error).message);
    } finally {
      setSaving('');
    }
  };

  const publish = async (e: FormEvent) => {
    e.preventDefault();
    if (scheduleError) return;
    setSaving('slots');
    try {
      const r = await api.publishSlots(schedule.resourceId, {
        from_date: schedule.from, to_date: schedule.to, start_hour: schedule.start, end_hour: schedule.end,
        skip_existing: true,
      });
      toast('ok', `Published ${r.created} slots (${r.skipped_existing} already existed, ${r.skipped_past} in the past).`);
    } catch (err) {
      toast('error', (err as Error).message);
    } finally {
      setSaving('');
    }
  };

  const FILTERS: [Filter, string][] = [['upcoming', 'Upcoming'], ['all', 'All'], ['cancelled', 'Cancelled']];

  return (
    <section>
      <PageHeader eyebrow="Merchant console" title={merchant.name}
        lead={<>You see and manage only <strong>{merchant.name}</strong>'s courts and bookings · <span className="mono">{merchant.slug}</span></>}
        actions={<button className="btn-secondary" onClick={() => load(merchant)} disabled={refreshing}>
          {refreshing ? <Spinner /> : <Icon name="refresh" size={16} />}Refresh</button>} />

      <div className="stats">
        <div className="card stat"><span className="s-icon"><Icon name="calendar" /></span><div><strong>{stats.today}</strong><span>Bookings today</span></div></div>
        <div className="card stat"><span className="s-icon blue"><Icon name="ticket" /></span><div><strong>{stats.upcoming}</strong><span>Upcoming bookings</span></div></div>
        <div className="card stat"><span className="s-icon amber"><Icon name="x" /></span><div><strong>{stats.cancelled}</strong><span>Cancelled</span></div></div>
        <div className="card stat"><span className="s-icon"><Icon name="court" /></span><div><strong>{resources.length}</strong><span>Courts listed</span></div></div>
      </div>

      <article className="card">
        <div className="card-header">
          <div><h2>Bookings</h2><p>Customer bookings for your venue, updated from booking events.</p></div>
        </div>
        <div className="toolbar">
          <div className="tabs" role="tablist" aria-label="Filter bookings">
            {FILTERS.map(([key, name]) => (
              <button key={key} role="tab" aria-selected={filter === key} className={filter === key ? 'on' : ''} onClick={() => setFilter(key)}>{name}</button>
            ))}
          </div>
          <span className="spacer" />
          <input type="search" placeholder="Search reference, customer or court" value={query}
            onChange={(e) => setQuery(e.target.value)} aria-label="Search bookings" />
        </div>
        {rows.length === 0 ? (
          <Empty icon="ticket" title={bookings.length ? 'No bookings match' : 'No bookings yet'}
            text={bookings.length ? 'Try another filter or search.' : 'Bookings appear here as soon as customers reserve your courts.'} />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Reference</th><th>When</th><th>Court</th><th>Customer</th><th>Status</th></tr></thead>
              <tbody>
                {rows.map((b) => (
                  <tr key={b.booking_id} className={b.status === 'CANCELLED' ? 'dim' : ''}>
                    <td className="mono">{b.reference}</td>
                    <td>{dateTime(b.start_time)}</td>
                    <td>{b.resource_name}</td>
                    <td>{b.customer_username}</td>
                    <td><Pill tone={b.status.toLowerCase()}>{b.status}</Pill></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>

      <div className="grid2 section">
        <article className="card">
          <div className="card-header"><div><h2>Courts</h2><p>Each court is booked in one-hour slots.</p></div></div>
          {resources.length > 0 ? (
            <ul className="list">
              {resources.map((r) => (
                <li key={r.resource_id}><Icon name="court" size={16} /><span className="grow">{r.name}</span><span className="tag">{label(r.resource_type)}</span></li>
              ))}
            </ul>
          ) : <p className="muted" style={{ marginBottom: 16 }}>No courts yet. Add your first one below.</p>}
          <form onSubmit={addResource} className="stack">
            <div className="form-grid">
              <label className="field">Court name
                <input placeholder="e.g. Court 3" value={newResource.name} required
                  onChange={(e) => setNewResource({ ...newResource, name: e.target.value })} />
              </label>
              <label className="field">Type
                <input list="court-types" placeholder="badminton_court" value={newResource.resource_type} pattern="[a-z0-9_]+" required
                  title="Lowercase letters, numbers and underscores"
                  onChange={(e) => setNewResource({ ...newResource, resource_type: e.target.value })} />
                <datalist id="court-types">{types.map((t) => <option key={t} value={t}>{label(t)}</option>)}</datalist>
              </label>
            </div>
            <button type="submit" className="btn-secondary" disabled={saving === 'resource'}>
              {saving === 'resource' ? <Spinner /> : <Icon name="plus" size={16} />}Add court
            </button>
          </form>
        </article>

        <article className="card">
          <div className="card-header"><div><h2>Publish one-hour slots</h2><p>Existing slots are kept; only missing hours are added.</p></div></div>
          <form onSubmit={publish} className="stack">
            <label className="field">Court
              <select value={schedule.resourceId} required onChange={(e) => setSchedule({ ...schedule, resourceId: e.target.value })}>
                <option value="">Choose a court</option>
                {resources.map((r) => <option key={r.resource_id} value={r.resource_id}>{r.name}</option>)}
              </select>
            </label>
            <div className="form-grid">
              <label className="field">From<input type="date" value={schedule.from} min={isoDate(0)} onChange={(e) => setSchedule({ ...schedule, from: e.target.value })} /></label>
              <label className="field">To<input type="date" value={schedule.to} min={schedule.from} onChange={(e) => setSchedule({ ...schedule, to: e.target.value })} /></label>
              <label className="field">First hour<input type="number" min={0} max={23} value={schedule.start}
                onChange={(e) => setSchedule({ ...schedule, start: Number(e.target.value) })} /></label>
              <label className="field">Last hour ends<input type="number" min={1} max={24} value={schedule.end}
                onChange={(e) => setSchedule({ ...schedule, end: Number(e.target.value) })} /></label>
            </div>
            {scheduleError ? <Alert kind="error">{scheduleError}</Alert>
              : <Alert kind="info">Up to <strong>{days * hours}</strong> slots: {days} {days === 1 ? 'day' : 'days'} × {hours} {hours === 1 ? 'hour' : 'hours'}, {String(schedule.start).padStart(2, '0')}:00–{String(schedule.end).padStart(2, '0')}:00.</Alert>}
            <button type="submit" disabled={saving === 'slots' || !!scheduleError || !schedule.resourceId}>
              {saving === 'slots' ? <Spinner /> : <Icon name="calendar" size={16} />}Publish slots
            </button>
          </form>
        </article>
      </div>
    </section>
  );
}
