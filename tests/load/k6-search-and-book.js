// Each measured iteration sends exactly one HTTP request. Prepare a manifest first.
import http from 'k6/http';
import { check } from 'k6';
import exec from 'k6/execution';
import { SharedArray } from 'k6/data';
import { Counter, Rate, Trend } from 'k6/metrics';

const manifest = JSON.parse(open(__ENV.LOAD_MANIFEST || '../../.local/load-manifest.json'));
const slots = new SharedArray('distinct booking slots', () =>
  JSON.parse(open(__ENV.LOAD_SLOTS || '../../.local/load-slots.json')));
const GATEWAY = (__ENV.GATEWAY || manifest.gateway).replace(/\/$/, '');
const API_KEY = __ENV.API_KEY || 'local-loadtest-key';
const phases = manifest.phases;
if (manifest.schema_version !== 2 || GATEWAY !== manifest.gateway || slots.length < manifest.required_booking_slots) {
  throw new Error('Invalid or mismatched load manifest; prepare inventory again.');
}
const requests = new Counter('business_requests');
const searches = new Counter('search_requests');
const bookings = new Counter('booking_requests');
const successfulBookings = new Counter('successful_bookings');
const conflicts = new Counter('booking_conflicts');
const inventoryErrors = new Counter('inventory_errors');
const serverErrors = new Rate('unexpected_errors');
const failures = new Rate('unexpected_responses');
const searchLatency = new Trend('search_latency', true);
const bookingLatency = new Trend('booking_latency', true);
const successfulBookingLatency = new Trend('successful_booking_latency', true);
const scenarios = {};
const peakRate = Math.max(...phases.map((p) => p.rate));
const thresholds = {
  unexpected_errors: ['rate<0.01'], unexpected_responses: ['rate<0.01'],
  dropped_iterations: ['count==0'], inventory_errors: ['count==0'],
};
for (const phase of phases) {
  for (const [op, share] of [['search', 0.8], ['book', 0.2]]) {
    const rate = Math.round(phase.rate * share);
    scenarios[`${phase.name}_${op}`] = {
      executor: 'constant-arrival-rate', exec: op, rate, timeUnit: '1s',
      startTime: `${phase.start_seconds}s`, duration: `${phase.seconds}s`, gracefulStop: '30s',
      // Budget eight seconds of in-flight requests before each phase starts;
      // the first full run saw multi-second ramp responses and dropped arrivals.
      preAllocatedVUs: Math.max(20, rate * 8), maxVUs: Math.max(30, rate * 12),
      tags: { phase: phase.name, op },
    };
  }
  // The proposal's latency criterion applies at peak. Keep every ramp-stage
  // measurement, and enforce the target on every phase at the maximum rate.
  if (phase.rate === peakRate) {
    thresholds[`search_latency{phase:${phase.name}}`] = ['p(95)<500'];
    thresholds[`successful_booking_latency{phase:${phase.name}}`] = ['p(95)<1000'];
    thresholds[`unexpected_errors{phase:${phase.name}}`] = ['rate<0.01'];
    thresholds[`unexpected_responses{phase:${phase.name}}`] = ['rate<0.01'];
  } else {
    // k6 exports tag-specific trends only when they have a submetric selector.
    // These selectors report the ramp values without imposing peak SLOs there.
    thresholds[`search_latency{phase:${phase.name}}`] = ['p(95)>=0'];
    thresholds[`successful_booking_latency{phase:${phase.name}}`] = ['p(95)>=0'];
    thresholds[`unexpected_errors{phase:${phase.name}}`] = ['rate>=0'];
    thresholds[`unexpected_responses{phase:${phase.name}}`] = ['rate>=0'];
  }
  thresholds[`search_requests{phase:${phase.name}}`] = [`count>=${Math.floor(phase.expected_searches * 0.98)}`];
  thresholds[`booking_requests{phase:${phase.name}}`] = [`count>=${Math.floor(phase.expected_bookings * 0.98)}`];
  thresholds[`successful_bookings{phase:${phase.name}}`] = ['count>0'];
}
export const options = { scenarios, thresholds };

export function setup() {
  console.info('K6_MEASUREMENT_START=' + new Date().toISOString());
  if (__ENV.ID_TOKEN) return { token: __ENV.ID_TOKEN };
  const response = http.post(`${GATEWAY}/auth/login`, JSON.stringify({
    username: __ENV.USERNAME || 'loadtester', password: __ENV.PASSWORD || 'Passw0rd!',
  }), { headers: { 'Content-Type': 'application/json' }, tags: { op: 'setup' } });
  if (response.status !== 200) throw new Error('Authentication failed before load measurement.');
  return { token: response.json('id_token') };
}
function phaseForScenario() {
  return phases.find((phase) => exec.scenario.name === `${phase.name}_search` ||
    exec.scenario.name === `${phase.name}_book`);
}
function record(response, tags, expected) {
  requests.add(1, tags);
  serverErrors.add(response.status >= 500 || response.status === 0, tags);
  failures.add(!expected.includes(response.status), tags);
}
function pick(values) { return values[Math.floor(Math.random() * values.length)]; }
export function search() {
  const phase = phaseForScenario();
  // A timer can schedule one extra boundary iteration. Cap both operations at
  // their declared quotas, without reducing the required booking workload.
  if (exec.scenario.iterationInTest >= phase.expected_searches) return;
  const tags = { phase: phase.name, op: 'search' };
  const date = pick(manifest.dates);
  let query = `date=${date}`;
  const merchants = manifest.merchants_by_date[date] || [];
  if (merchants.length && Math.random() < 0.7) query += `&merchant_id=${pick(merchants)}`;
  const response = http.get(`${GATEWAY}/v1/availability/slots?${query}`, {
    headers: { 'x-api-key': API_KEY }, tags,
  });
  searches.add(1, tags);
  searchLatency.add(response.timings.duration, tags);
  record(response, tags, [200]);
  check(response, { 'search 200': (r) => r.status === 200 }, tags);
}
export function book(data) {
  const phase = phaseForScenario();
  const tags = { phase: phase.name, op: 'book' };
  if (exec.scenario.iterationInTest >= phase.expected_bookings) return;
  const index = phase.booking_offset + exec.scenario.iterationInTest;
  if (!slots[index]) {
    inventoryErrors.add(1, tags);
    exec.test.abort('Booking inventory exhausted; this run cannot validate the planned workload.');
    return;
  }
  inventoryErrors.add(0, tags);
  const response = http.post(`${GATEWAY}/v1/bookings`, JSON.stringify({ slot_id: slots[index] }), {
    headers: { 'x-api-key': API_KEY, 'Content-Type': 'application/json',
      Authorization: `Bearer ${data.token}`,
      'Idempotency-Key': `${manifest.run_id}-${phase.name}-${exec.scenario.iterationInTest}` }, tags,
  });
  bookings.add(1, tags);
  bookingLatency.add(response.timings.duration, tags);
  if (response.status === 201) {
    successfulBookings.add(1, tags);
    successfulBookingLatency.add(response.timings.duration, tags);
  }
  if (response.status === 409) conflicts.add(1, tags);
  record(response, tags, [201, 409]);
  check(response, { 'booking 201 or 409': (r) => r.status === 201 || r.status === 409 }, tags);
}
export function handleSummary(data) {
  const ended = Date.now();
  const measurement = {
    started_at: new Date(ended - data.state.testRunDurationMs).toISOString(),
    ended_at: new Date(ended).toISOString(),
    timing_method: 'k6 run duration and handleSummary UTC clock',
  };
  return { 'summary.json': JSON.stringify({ ...data, workload: manifest, measurement }, null, 2) };
}
