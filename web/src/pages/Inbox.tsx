import { useEffect, useState } from 'react';
import { api, Notification } from '../api';
import { dateTime } from '../format';

export default function Inbox() {
  const [items, setItems] = useState<Notification[]>([]);

  const load = () => api.notifications().then(setItems).catch(() => {});
  useEffect(() => {
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, []);

  const read = async (n: Notification) => {
    if (!n.read_at) {
      await api.markRead(n.notification_id);
      load();
    }
  };

  return (
    <section>
      <h1>Inbox</h1>
      <p className="muted">Delivered asynchronously by the Notification Service from booking events.</p>
      {items.length === 0 && <p className="muted">Nothing here yet.</p>}
      <ul className="inbox">
        {items.map((n) => (
          <li key={n.notification_id} className={n.read_at ? 'read' : 'unread'} onClick={() => read(n)}>
            <span className={`dot ${n.kind === 'BOOKING_CANCELLED' ? 'cancel' : 'ok'}`} />
            <div>
              <strong>{n.title}</strong>
              <p>{n.body}</p>
              <small>{dateTime(n.created_at)}</small>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
