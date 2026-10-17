// Scripted load test (k6). 80% availability searches, 20% booking operations.
// Raises the load from 25 to 200 requests per second in five-minute steps, then holds the
// peak for 10 minutes, as defined in the proposal.
//
//   k6 run tests/load/k6-search-and-book.js                        # full profile (~35 min)
//   k6 run -e PROFILE=short tests/load/k6-search-and-book.js       # 3-minute rehearsal
//   docker run --rm -i --network host grafana/k6:0.55.0 run - < tests/load/k6-search-and-book.js
//
// Env: GATEWAY, API_KEY, USERNAME, PASSWORD (dev-auth) or ID_TOKEN (Cognito), DAYS (dates to spread over)
import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const GATEWAY = __ENV.GATEWAY || 'http://127.0.0.1:8080';
const API_KEY = __ENV.API_KEY || 'local-loadtest-key';
const DAYS = parseInt(__ENV.DAYS || '2', 10);
const PROFILE = __ENV.PROFILE || 'full';

const unexpectedErrors = new Rate('unexpected_errors');
const bookingConflicts = new Counter('booking_conflicts');
const bookingsMade = new Counter('bookings_made');
const searchLatency = new Trend('search_latency', true);
const bookingLatency = new Trend('booking_latency', true);

const stagesFull = [
  { target: 25, duration: '30s' },
  { target: 25, duration: '5m' },
  { target: 50, duration: '5m' },
  { target: 100, duration: '5m' },
  { target: 150, duration: '5m' },
  { target: 200, duration: '5m' },
  { target: 200, duration: '10m' },
];
const stagesShort = [
  { target: 25, duration: '30s' },
  { target: 100, duration: '1m' },
  { target: 200, duration: '1m' },
  { target: 200, duration: '30s' },
];

export const options = {
  scenarios: {
    mixed: {
      executor: 'ramping-arrival-rate',
      startRate: 5,
      timeUnit: '1s',
      preAllocatedVUs: 100,
      maxVUs: 600,
      stages: PROFILE === 'short' ? stagesShort : stagesFull,
    },
  },
  thresholds: {
    search_latency: ['p(95)<500'],
    booking_latency: ['p(95)<1000'],
    unexpected_errors: ['rate<0.01'],
  },
};

function isoDate(offsetDays) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return d.toISOString().slice(0, 10);
}

export function setup() {
  let token = __ENV.ID_TOKEN;
  if (!token) {
    const res = http.post(`${GATEWAY}/auth/login`, JSON.stringify({
      username: __ENV.USERNAME || 'loadtester',
      password: __ENV.PASSWORD || 'Passw0rd!',
    }), { headers: { 'Content-Type': 'application/json' } });
    token = res.json('id_token');
  }
  const merchants = http.get(`${GATEWAY}/v1/availability/merchants`, { headers: { 'x-api-key': API_KEY } }).json();
  return { token, merchants: merchants.map((m) => m.merchant_id) };
}

function pick(list) {
  return list[Math.floor(Math.random() * list.length)];
}

function search(data) {
  const params = { date: isoDate(1 + Math.floor(Math.random() * DAYS)) };
  if (data.merchants.length && Math.random() < 0.7) params.merchant_id = pick(data.merchants);
  const qs = Object.entries(params).map(([k, v]) => `${k}=${v}`).join('&');
  const res = http.get(`${GATEWAY}/v1/availability/slots?${qs}`, {
    headers: { 'x-api-key': API_KEY },
    tags: { op: 'search' },
  });
  searchLatency.add(res.timings.duration);
  unexpectedErrors.add(res.status >= 500 || res.status === 0);
  check(res, { 'search 200': (r) => r.status === 200 });
  return res.status === 200 ? res.json('slots') : [];
}

function book(data) {
  const slots = search(data);
  if (!slots || slots.length === 0) return;
  const slot = pick(slots);
  const res = http.post(`${GATEWAY}/v1/bookings`, JSON.stringify({ slot_id: slot.slot_id }), {
    headers: {
      'x-api-key': API_KEY,
      'Content-Type': 'application/json',
      Authorization: `Bearer ${data.token}`,
      'Idempotency-Key': `${__VU}-${__ITER}-${Date.now()}`,
    },
    tags: { op: 'book' },
  });
  bookingLatency.add(res.timings.duration);
  // 409 is an expected business outcome (the read model lags slightly); report it separately.
  if (res.status === 409) bookingConflicts.add(1);
  if (res.status === 201) bookingsMade.add(1);
  unexpectedErrors.add(res.status >= 500 || res.status === 0);
  check(res, { 'booking 201 or 409': (r) => r.status === 201 || r.status === 409 });
}

export default function (data) {
  if (Math.random() < 0.8) {
    search(data);
  } else {
    book(data);
  }
}
