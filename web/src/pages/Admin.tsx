import { FormEvent, useCallback, useEffect, useState } from 'react';
import { api, Member, Merchant } from '../api';
import { Alert, Empty, Icon, PageHeader, Pill, Spinner, useToast } from '../ui';

export default function Admin() {
  const toast = useToast();
  const [merchants, setMerchants] = useState<Merchant[]>([]);
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ name: '', slug: '', contact_email: '' });
  const [member, setMember] = useState({ merchantId: '', username: '', role: 'merchant_admin' });
  const [members, setMembers] = useState<Member[]>([]);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState<'' | 'merchant' | 'member'>('');

  const load = useCallback(() => api.allMerchants().then(setMerchants).catch((e) => setError(e.message))
    .finally(() => setLoading(false)), []);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (member.merchantId) api.members(member.merchantId).then(setMembers).catch(() => setMembers([]));
    else setMembers([]);
  }, [member.merchantId]);

  const slugify = (name: string) => name.toLowerCase().trim().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');

  const onboard = async (e: FormEvent) => {
    e.preventDefault();
    setSaving('merchant');
    try {
      const m = await api.onboardMerchant(form);
      toast('ok', `${m.name} is onboarded. It appears in customer search once it publishes slots.`);
      setForm({ name: '', slug: '', contact_email: '' });
      load();
    } catch (err) {
      toast('error', (err as Error).message);
    } finally {
      setSaving('');
    }
  };

  const assign = async (e: FormEvent) => {
    e.preventDefault();
    setSaving('member');
    try {
      const r = await api.assignMember(member.merchantId, member.username, member.role);
      toast('ok', `${r.username} is now ${r.role.replace('_', ' ')}. They must sign in again to get the new role.`);
      setMembers(await api.members(member.merchantId));
      setMember({ ...member, username: '' });
    } catch (err) {
      toast('error', (err as Error).message);
    } finally {
      setSaving('');
    }
  };

  const active = merchants.filter((m) => (m.status ?? 'ACTIVE') === 'ACTIVE').length;

  return (
    <section>
      <PageHeader eyebrow="Platform operator" title="Platform administration"
        lead="Onboard venues and give their staff access. Everything here goes through the same versioned API that partners use." />
      {error && <Alert kind="error">{error}</Alert>}

      <div className="stats">
        <div className="card stat"><span className="s-icon"><Icon name="building" /></span><div><strong>{loading ? '…' : merchants.length}</strong><span>Merchants</span></div></div>
        <div className="card stat"><span className="s-icon blue"><Icon name="checkCircle" /></span><div><strong>{loading ? '…' : active}</strong><span>Active</span></div></div>
      </div>

      <div className="grid2">
        <article className="card">
          <div className="card-header"><div><h2>Onboard a merchant</h2><p>Venues can also join from a YAML file with the onboarding script.</p></div></div>
          <form onSubmit={onboard} className="stack">
            <label className="field">Venue name
              <input placeholder="e.g. Northpoint Arena" value={form.name} required
                onChange={(e) => setForm({ ...form, name: e.target.value, slug: form.slug || '' })}
                onBlur={() => !form.slug && form.name && setForm((f) => ({ ...f, slug: slugify(f.name) }))} />
            </label>
            <label className="field">Slug <span className="help">Lowercase, used in links and the API</span>
              <input placeholder="northpoint-arena" value={form.slug} required pattern="[a-z0-9]+(-[a-z0-9]+)*"
                onChange={(e) => setForm({ ...form, slug: e.target.value })} />
            </label>
            <label className="field">Contact e-mail
              <input placeholder="hello@venue.test" type="email" value={form.contact_email} required
                onChange={(e) => setForm({ ...form, contact_email: e.target.value })} />
            </label>
            <button type="submit" disabled={saving === 'merchant'}>{saving === 'merchant' ? <Spinner /> : <Icon name="plus" size={16} />}Onboard merchant</button>
          </form>
        </article>

        <article className="card">
          <div className="card-header"><div><h2>Assign a merchant user</h2><p>The role is written to the identity provider as a token claim.</p></div></div>
          <form onSubmit={assign} className="stack">
            <label className="field">Merchant
              <select value={member.merchantId} required onChange={(e) => setMember({ ...member, merchantId: e.target.value })}>
                <option value="">Choose a merchant</option>
                {merchants.map((m) => <option key={m.merchant_id} value={m.merchant_id}>{m.name}</option>)}
              </select>
            </label>
            <div className="form-grid">
              <label className="field">Username
                <input placeholder="e.g. owner3" value={member.username} required
                  onChange={(e) => setMember({ ...member, username: e.target.value })} />
              </label>
              <label className="field">Role
                <select value={member.role} onChange={(e) => setMember({ ...member, role: e.target.value })}>
                  <option value="merchant_admin">Merchant admin</option>
                  <option value="merchant_staff">Merchant staff</option>
                </select>
              </label>
            </div>
            <button type="submit" className="btn-secondary" disabled={saving === 'member'}>{saving === 'member' ? <Spinner /> : <Icon name="users" size={16} />}Assign user</button>
          </form>
          {members.length > 0 && (
            <>
              <hr className="divider" />
              <ul className="list">
                {members.map((m) => (
                  <li key={m.username}><span className="avatar">{m.username.slice(0, 2)}</span><span className="grow">{m.username}</span>
                    <span className="tag">{m.role.replace('_', ' ')}</span><Pill tone={m.sync_status.toLowerCase()}>{m.sync_status}</Pill></li>
                ))}
              </ul>
            </>
          )}
        </article>
      </div>

      <article className="card section">
        <div className="card-header"><div><h2>Merchants</h2><p>Every venue on the platform.</p></div></div>
        {loading ? <div className="skeleton" style={{ height: 120 }} /> : merchants.length === 0 ? (
          <Empty icon="building" title="No merchants yet" text="Onboard the first venue with the form above." />
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead><tr><th>Name</th><th>Slug</th><th>Contact</th><th>Status</th></tr></thead>
              <tbody>
                {merchants.map((m) => (
                  <tr key={m.merchant_id}><td><strong>{m.name}</strong></td><td className="mono">{m.slug}</td><td>{m.contact_email}</td>
                    <td><Pill tone={(m.status ?? 'ACTIVE').toLowerCase()}>{m.status ?? 'ACTIVE'}</Pill></td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </article>
    </section>
  );
}
