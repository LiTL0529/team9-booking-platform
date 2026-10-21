import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api, Notification } from '../api';
import { NOTIFICATIONS_CHANGED } from '../App';
import { dateTime, relative } from '../format';
import { Empty, Icon, PageHeader, Spinner } from '../ui';

export default function Inbox() {
  const [items, setItems] = useState<Notification[]>([]);
  const [loading, setLoading] = useState(true);
  const [marking, setMarking] = useState(false);

  const load = useCallback(() => api.notifications().then(setItems).catch(() => {}).finally(() => setLoading(false)), []);
  useEffect(() => {
    load();
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
  }, [load]);

  const unread = items.filter((n) => !n.read_at);
  const changed = () => window.dispatchEvent(new Event(NOTIFICATIONS_CHANGED));

  const read = async (n: Notification) => {
    if (n.read_at) return;
    setItems((list) => list.map((x) => (x.notification_id === n.notification_id ? { ...x, read_at: new Date().toISOString() } : x)));
    await api.markRead(n.notification_id).catch(() => {});
    changed();
  };

  const readAll = async () => {
    setMarking(true);
    await Promise.all(unread.map((n) => api.markRead(n.notification_id).catch(() => {})));
    await load();
    changed();
    setMarking(false);
  };

  return (
    <section>
      <PageHeader eyebrow="Notifications" title="Inbox"
        lead="Booking confirmations and cancellations arrive here a moment after you book, delivered by the Notification Service from booking events."
        actions={unread.length > 0 && (
          <button className="btn-secondary" onClick={readAll} disabled={marking}>
            {marking ? <Spinner /> : <Icon name="check" size={16} />}Mark all as read
          </button>
        )} />

      {loading ? (
        <div className="inbox">{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 74 }} />)}</div>
      ) : items.length === 0 ? (
        <Empty icon="bell" title="No messages yet" text="Book a court and the confirmation will appear here within seconds."
          action={<Link to="/" className="button">Find a slot<Icon name="arrowRight" size={16} /></Link>} />
      ) : (
        <ul className="inbox">
          {items.map((n) => {
            const cancelled = n.kind === 'BOOKING_CANCELLED';
            return (
              <li key={n.notification_id}>
                <button className={`message${n.read_at ? '' : ' unread'}`} onClick={() => read(n)}
                  aria-label={`${n.read_at ? '' : 'Unread: '}${n.title}`}>
                  <span className={`m-icon ${cancelled ? 'cancel' : 'ok'}`}><Icon name={cancelled ? 'x' : 'check'} size={18} /></span>
                  <span className="m-body">
                    <strong>{n.title}</strong>
                    <span className="m-text">{n.body}</span>
                    <small title={dateTime(n.created_at)}>{relative(n.created_at)}</small>
                  </span>
                  {!n.read_at && <span className="new">New</span>}
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
