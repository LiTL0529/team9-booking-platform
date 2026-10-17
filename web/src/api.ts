// API access for the web application. The app knows nothing about individual services:
// it only calls the versioned public API behind the gateway with its own API key.

export interface AppConfig {
  apiBaseUrl: string;
  apiKey: string;
  authMode: 'dev' | 'cognito';
  cognitoRegion: string;
  cognitoClientId: string;
}

export interface Claims {
  sub: string;
  username: string;
  email?: string;
  groups: string[];
  merchantId?: string;
  exp: number;
}

export interface Merchant { merchant_id: string; name: string; slug: string; contact_email?: string; status?: string }
export interface Slot {
  slot_id: string; merchant_id: string; merchant_name: string; resource_id: string; resource_name: string;
  resource_type: string; start_time: string; end_time: string; status: string;
}
export interface Booking {
  booking_id: string; reference: string; status: string; slot_id: string; merchant_id: string; resource_name: string;
  resource_type: string; start_time: string; end_time: string; local_date: string; customer_username: string;
  created_at: string; cancelled_at: string | null;
}
export interface Notification {
  notification_id: string; kind: string; title: string; body: string; created_at: string; read_at: string | null;
}
export interface Resource { resource_id: string; merchant_id: string; name: string; resource_type: string; description: string }
export interface Member { username: string; role: string; sync_status: string }

let config: AppConfig = { apiBaseUrl: '', apiKey: '', authMode: 'dev', cognitoRegion: '', cognitoClientId: '' };
let token: string | null = null;
const TOKEN_KEY = 'courthub.token';

export async function loadConfig(): Promise<void> {
  const res = await fetch('/config.json', { cache: 'no-store' });
  config = await res.json();
  try {
    token = sessionStorage.getItem(TOKEN_KEY);
  } catch {
    token = null;
  }
  if (token && (decode(token)?.exp ?? 0) * 1000 < Date.now()) setToken(null);
}

function setToken(value: string | null) {
  token = value;
  try {
    if (value) sessionStorage.setItem(TOKEN_KEY, value);
    else sessionStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: keep the token in memory only */
  }
}

export function decode(jwt: string): Claims | null {
  try {
    const payload = JSON.parse(atob(jwt.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return {
      sub: payload.sub,
      username: payload['cognito:username'] ?? payload.sub,
      email: payload.email,
      groups: payload['cognito:groups'] ?? [],
      merchantId: payload['custom:merchant_id'],
      exp: payload.exp,
    };
  } catch {
    return null;
  }
}

export function currentClaims(): Claims | null {
  return token ? decode(token) : null;
}

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

async function request<T>(method: string, path: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const res = await fetch(`${config.apiBaseUrl}${path}`, {
    method,
    headers: {
      'x-api-key': config.apiKey,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  const data = text ? JSON.parse(text) : null;
  if (!res.ok) {
    const err = data?.error ?? {};
    throw new ApiError(res.status, err.code ?? 'error', err.message ?? data?.detail ?? `HTTP ${res.status}`);
  }
  return data as T;
}

export async function signIn(username: string, password: string): Promise<Claims> {
  let idToken: string;
  if (config.authMode === 'cognito') {
    const res = await fetch(`https://cognito-idp.${config.cognitoRegion}.amazonaws.com/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-amz-json-1.1',
        'X-Amz-Target': 'AWSCognitoIdentityProviderService.InitiateAuth',
      },
      body: JSON.stringify({
        AuthFlow: 'USER_PASSWORD_AUTH',
        ClientId: config.cognitoClientId,
        AuthParameters: { USERNAME: username, PASSWORD: password },
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new ApiError(res.status, 'auth', data.message ?? 'sign-in failed');
    idToken = data.AuthenticationResult.IdToken;
  } else {
    const data = await request<{ id_token: string }>('POST', '/auth/login', { username, password });
    idToken = data.id_token;
  }
  setToken(idToken);
  return decode(idToken)!;
}

export function signOut() {
  setToken(null);
}

export const api = {
  merchants: () => request<Merchant[]>('GET', '/v1/availability/merchants'),
  resourceTypes: () => request<string[]>('GET', '/v1/availability/resource-types'),
  searchSlots: (params: Record<string, string>) =>
    request<{ date: string; count: number; slots: Slot[] }>('GET', `/v1/availability/slots?${new URLSearchParams(params)}`),
  book: (slotId: string, idempotencyKey: string) =>
    request<Booking>('POST', '/v1/bookings', { slot_id: slotId }, { 'Idempotency-Key': idempotencyKey }),
  myBookings: () => request<Booking[]>('GET', '/v1/bookings'),
  merchantBookings: (merchantId: string) => request<Booking[]>('GET', `/v1/bookings?merchant_id=${merchantId}`),
  cancel: (bookingId: string) => request<Booking>('POST', `/v1/bookings/${bookingId}/cancel`),
  notifications: () => request<Notification[]>('GET', '/v1/notifications'),
  unreadCount: () => request<{ unread: number }>('GET', '/v1/notifications/unread-count'),
  markRead: (id: string) => request<Notification>('POST', `/v1/notifications/${id}/read`),
  myMerchant: () => request<Merchant>('GET', '/v1/merchants/me'),
  allMerchants: () => request<Merchant[]>('GET', '/v1/merchants'),
  onboardMerchant: (body: { name: string; slug: string; contact_email: string }) =>
    request<Merchant>('POST', '/v1/merchants', body),
  assignMember: (merchantId: string, username: string, role: string) =>
    request<Member>('POST', `/v1/merchants/${merchantId}/members`, { username, role }),
  members: (merchantId: string) => request<Member[]>('GET', `/v1/merchants/${merchantId}/members`),
  resources: (merchantId: string) => request<Resource[]>('GET', `/v1/resources?merchant_id=${merchantId}`),
  createResource: (body: { merchant_id: string; name: string; resource_type: string; description: string }) =>
    request<Resource>('POST', '/v1/resources', body),
  publishSlots: (resourceId: string, body: Record<string, unknown>) =>
    request<{ created: number; skipped_existing: number; skipped_past: number }>(
      'POST', `/v1/resources/${resourceId}/slots`, body),
};
