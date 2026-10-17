const zone = 'Asia/Singapore';

export const time = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-SG', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: zone });

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-SG', {
    weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: zone,
  });

export const label = (resourceType: string) =>
  resourceType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export function isoDate(offsetDays: number): string {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(d);
}

export const newKey = () =>
  (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);
