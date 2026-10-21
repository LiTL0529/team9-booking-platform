// FitPal is a fictional third-party app. It talks to CourtHub only through the public /v1 API,
// with its own application key (its own usage plan) and its own identity-provider app client.
// Every call is recorded so the page can show the integration live.

export interface PartnerConfig {
  apiBaseUrl: string;
  apiKey: string;
  authMode: 'dev' | 'cognito';
  cognitoRegion: string;
  cognitoClientId: string;
}

export interface Slot {
  slot_id: string; merchant_id: string; merchant_name: string; resource_id: string; resource_name: string;
  resource_type: string; start_time: string; end_time: string;
}
export interface Booking {
  booking_id: string; reference: string; status: string; resource_name: string; resource_type: string;
  start_time: string; end_time: string; merchant_id: string; created_at: string;
}
export interface Merchant { merchant_id: string; name: string }

export interface CallRecord {
  id: number; method: string; path: string; status: number | 'ERR'; ms: number; at: string; auth: boolean;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

let config: PartnerConfig = { apiBaseUrl: '', apiKey: '', authMode: 'dev', cognitoRegion: '', cognitoClientId: '' };
let token: string | null = null;
let seq = 1;
const listeners = new Set<(c: CallRecord) => void>();
const TOKEN_KEY = 'fitpal.token';

export const onCall = (fn: (c: CallRecord) => void) => {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
};
const record = (c: Omit<CallRecord, 'id' | 'at'>) => {
  const full = { ...c, id: seq++, at: new Date().toISOString() };
  listeners.forEach((fn) => fn(full));
};

export async function loadConfig(): Promise<void> {
  const res = await fetch('/partner-config.json', { cache: 'no-store' });
  config = await res.json();
  try {
    token = sessionStorage.getItem(TOKEN_KEY);
  } catch {
    token = null;
  }
  if (token && (claims()?.exp ?? 0) * 1000 < Date.now()) setToken(null);
}

export const maskedKey = () => (config.apiKey ? `••••${config.apiKey.slice(-4)}` : '(none)');

function setToken(value: string | null) {
  token = value;
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* memory only */
  }
}

export function claims(): { username: string; exp: number } | null {
  if (!token) return null;
  try {
    const p = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return { username: p['cognito:username'] ?? p.sub, exp: p.exp };
  } catch {
    return null;
  }
}

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const started = performance.now();
  let res: Response;
  try {
    res = await fetch(`${config.apiBaseUrl}${path}`, {
      method,
      headers: {
        'x-api-key': config.apiKey,
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    record({ method, path, status: 'ERR', ms: Math.round(performance.now() - started), auth: !!token });
    throw err;
  }
  record({ method, path, status: res.status, ms: Math.round(performance.now() - started), auth: !!token });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) throw new ApiError(res.status, data?.error?.message ?? data?.detail ?? `HTTP ${res.status}`);
  return data as T;
}

export async function signIn(username: string, password: string): Promise<void> {
  let idToken: string;
  if (config.authMode === 'cognito') {
    const started = performance.now();
    const res = await fetch(`https://cognito-idp.${config.cognitoRegion}.amazonaws.com/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth' },
      body: JSON.stringify({ AuthFlow: 'USER_PASSWORD_AUTH', ClientId: config.cognitoClientId, AuthParameters: { USERNAME: username, PASSWORD: password } }),
    });
    record({ method: 'POST', path: 'Cognito InitiateAuth (FitPal app client)', status: res.status, ms: Math.round(performance.now() - started), auth: false });
    const data = await res.json();
    if (!res.ok) throw new ApiError(res.status, data.message ?? 'sign-in failed');
    idToken = data.AuthenticationResult.IdToken;
  } else {
    idToken = (await request<{ id_token: string }>('POST', '/auth/login', { username, password })).id_token;
  }
  setToken(idToken);
}

export const signOut = () => setToken(null);

export const partnerApi = {
  merchants: () => request<Merchant[]>('GET', '/v1/availability/merchants'),
  resourceTypes: () => request<string[]>('GET', '/v1/availability/resource-types'),
  slots: (date: string, type: string) =>
    request<{ slots: Slot[] }>('GET', `/v1/availability/slots?${new URLSearchParams({ date, limit: '500', ...(type ? { resource_type: type } : {}) })}`),
  book: (slotId: string, key: string) => request<Booking>('POST', '/v1/bookings', { slot_id: slotId }, { 'Idempotency-Key': key }),
  myBookings: () => request<Booking[]>('GET', '/v1/bookings'),
  cancel: (id: string) => request<Booking>('POST', `/v1/bookings/${id}/cancel`),
};
