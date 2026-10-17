import { useEffect, useState } from 'react';
import { api, Booking } from '../api';
import { dateTime, label } from '../format';

export default function MyBookings() {
  const [bookings, setBookings] = useState<Booking[]>([]);
  const [error, setError] = useState('');

  const load = () => api.myBookings().then(setBookings).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const cancel = async (b: Booking) => {
    if (!confirm(`Cancel ${b.reference}?`)) return;
    try {
      await api.cancel(b.booking_id);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const upcoming = (b: Booking) => b.status === 'CONFIRMED' && new Date(b.start_time) > new Date();

  return (
    <section>
      <h1>My bookings</h1>
      {error && <p className="error">{error}</p>}
      {bookings.length === 0 && <p className="muted">No bookings yet.</p>}
      <table className="table">
        <thead>
          <tr><th>Reference</th><th>When</th><th>Resource</th><th>Status</th><th /></tr>
        </thead>
        <tbody>
          {bookings.map((b) => (
            <tr key={b.booking_id} className={b.status === 'CANCELLED' ? 'dim' : ''}>
              <td><code>{b.reference}</code></td>
              <td>{dateTime(b.start_time)}</td>
              <td>{b.resource_name} <span className="tag">{label(b.resource_type)}</span></td>
              <td><span className={`status ${b.status.toLowerCase()}`}>{b.status}</span></td>
              <td>{upcoming(b) && <button className="small danger" onClick={() => cancel(b)}>Cancel</button>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
