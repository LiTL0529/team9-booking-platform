const zone = 'Asia/Singapore';

export const time = (iso: string) =>
  new Date(iso).toLocaleTimeString('en-SG', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: zone });

export const dateTime = (iso: string) =>
  new Date(iso).toLocaleString('en-SG', {
    weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false, timeZone: zone,
  });

export const longDate = (iso: string) =>
  new Date(iso).toLocaleDateString('en-SG', { weekday: 'long', day: 'numeric', month: 'long', timeZone: zone });

/** Hour of day (0-23) in the venue time zone. */
export const hourOf = (iso: string) =>
  Number(new Intl.DateTimeFormat('en-GB', { hour: '2-digit', hour12: false, timeZone: zone }).format(new Date(iso)));

/** Calendar parts of an ISO timestamp in the venue time zone, for date badges. */
export function dateParts(iso: string) {
  const d = new Date(iso);
  const part = (o: Intl.DateTimeFormatOptions) => new Intl.DateTimeFormat('en-SG', { ...o, timeZone: zone }).format(d);
  return { weekday: part({ weekday: 'short' }), day: part({ day: 'numeric' }), month: part({ month: 'short' }) };
}

/** Parts of a YYYY-MM-DD calendar date, read as a day in the venue time zone. */
export const dayParts = (day: string) => dateParts(`${day}T12:00:00+08:00`);

export function relative(iso: string): string {
  const seconds = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return dateTime(iso);
}

export const label = (resourceType: string) =>
  resourceType.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());

export function isoDate(offsetDays: number): string {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(d);
}

/** The calendar day after a YYYY-MM-DD date. */
export function nextDay(day: string): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

export const newKey = () =>
  (crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`);

export const initials = (name: string) => name.slice(0, 2);
