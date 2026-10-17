import { FormEvent, useEffect, useState } from 'react';
import { api, Member, Merchant } from '../api';

export default function Admin() {
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [form, setForm] = useState({ name: '', slug: '', contact_email: '' });
  const [member, setMember] = useState({ merchantId: '', username: '', role: 'merchant_admin' });
  const [members, setMembers] = useState<Member[]>([]);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  const load = () => api.allMerchants().then(setMerchants).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    if (member.merchantId) api.members(member.merchantId).then(setMembers).catch(() => setMembers([]));
  }, [member.merchantId]);

  const onboard = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const m = await api.onboardMerchant(form);
      setMessage(`Onboarded ${m.name}. It appears in customer search as soon as it publishes slots.`);
      setForm({ name: '', slug: '', contact_email: '' });
      load();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const assign = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    try {
      const r = await api.assignMember(member.merchantId, member.username, member.role);
      setMessage(`${r.username} is now ${r.role} (identity sync: ${r.sync_status}). They must sign in again.`);
      setMembers(await api.members(member.merchantId));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <section>
      <h1>Platform administration</h1>
      {message && <p className="notice">{message}</p>}
      {error && <p className="error">{error}</p>}
      <div className="grid2">
        <article className="card">
          <h2>Onboard a merchant</h2>
          <form onSubmit={onboard} className="stack">
            <input placeholder="Name" value={form.name} required onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input placeholder="slug (lowercase-with-dashes)" value={form.slug} required pattern="[a-z0-9]+(-[a-z0-9]+)*"
              onChange={(e) => setForm({ ...form, slug: e.target.value })} />
            <input placeholder="Contact e-mail" type="email" value={form.contact_email} required
              onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            <button type="submit">Onboard</button>
          </form>
        </article>
        <article className="card">
          <h2>Assign a merchant user</h2>
          <form onSubmit={assign} className="stack">
            <select value={member.merchantId} required onChange={(e) => setMember({ ...member, merchantId: e.target.value })}>
              <option value="">Choose a merchant</option>
              {merchants.map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name}</option>)}
            </select>
            <input placeholder="Username" value={member.username} required
              onChange={(e) => setMember({ ...member, username: e.target.value })} />
            <select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value })}>
              <option value="merchant_admin">Merchant admin</option>
              <option value="merchant_staff">Merchant staff</option>
            </select>
            <button type="submit">Assign</button>
          </form>
          {members.length > 0 && (
            <ul className="plain">
              {members.map((m) => <li key={m.username}>{m.username} · {m.role} · {m.sync_status}</li>)}
            </ul>
          )}
        </article>
      </div>
      <article className="card">
        <h2>Merchants ({merchants.length})</h2>
        <table className="table">
          <thead><tr><th>Name</th><th>Slug</th><th>Contact</th><th>Status</th></tr></thead>
          <tbody>
            {merchants.map((m) => (
              <tr key={m.merchant_id}><td>{m.name}</td><td>{m.slug}</td><td>{m.contact_email}</td><td>{m.status}</td></tr>
            ))}
          </tbody>
        </table>
      </article>
    </section>
  );
}
