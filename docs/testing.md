# Testing and evidence

## Automated test suites (run in every pipeline)

| Suite | Where | What it proves |
|---|---|---|
| Template unit tests | `libs/platform_common/tests` | Circuit breaker states, retries only on transient errors, token verification (expiry, foreign keys, merchant membership), SNS envelope unwrapping |
| Merchant | `services/merchant/tests` | Admin-only onboarding, unique slugs, roles written to the IdP, IdP outage leaves membership `PENDING` until resync, cross-merchant access denied, one merchant per user |
| Catalogue | `services/catalogue/tests` | One event per published slot, overlap rejected by the service **and** by the database (same hour and half-hour offset), past dates rejected, cross-merchant creation denied |
| Availability | `services/availability/tests` | Cross-merchant search and filters, booked slots disappear and come back on cancel, out-of-order events converge, cache hit/miss and invalidation on events |
| Booking | `services/booking/tests` | Booking, 409 on taken slot, idempotent replay, key reuse rejected, only customers book, ownership on read/cancel, merchant-scoped listing, read-through to Catalogue, late events never reset a booked slot, duplicate events ignored, **50 concurrent threads → exactly one booking** |
| Notification | `services/notification/tests` | Inbox per customer, duplicate events ignored, unread count, authentication required |
| Contract tests | every service | Live OpenAPI equals `contracts/openapi/<service>.json`; every emitted event validates against `contracts/events/*.schema.json` |

Result on 2026-10-17 (local, PostgreSQL 16): **57 passed** (11 template + 46 service).

## System tests against a running deployment

| Test | Command | Recorded locally (2026-10-17, native runner, one laptop) |
|---|---|---|
| End-to-end smoke | `python tests/e2e/smoke_test.py` | PASSED: API key and token enforced, booking, idempotent replay, 409 + 403 for a second customer, read model updated from events, confirmation delivered, cancellation released the slot |
| Concurrency | `python tests/concurrency/same_slot.py --requests 100` | `{201: 1, 409: 99}` — exactly one booking |
| Second merchant without code change | `python scripts/onboard_merchant.py merchants/eastside-sports.yaml` | 2 resources, 392 slots, merchant admin synced to IdP, ~3 s, no code change |
| Partner integration | `python partner-client/partner_client.py book --type futsal_pitch` | Booked through the same APIs with its own API key (10 rps usage plan) |
| Notification outage | stop Notification, book, restart | Booking `201` while Notification was down; event waited in the queue; delivered once after restart |
| Dataset seeding | `python scripts/seed_load_data.py` | 100 merchants, 1,000 resources, 20,000 slots created through the API in 83 s |
| Stepped load | `python tests/load/loadgen.py --steps 10,25,50 --step-seconds 15` | 10 and 25 rps met the targets (P95 search 74/170 ms, booking 128/164 ms); 50 rps saturated the single local process per service while moto drained a 20,000-event backlog on the same machine. Not representative of AWS: one process per service, no auto scaling. |

## Cloud scalability test plan (AWS test environment)

Targets from the proposal; capacity claims are limited to the workload actually tested.

| Area | How | Target |
|---|---|---|
| Dataset | `scripts/seed_load_data.py` (100 merchants, 1,000 resources, ≥20,000 slots) | – |
| Load profile | `k6 run -e GATEWAY=<web_url> -e API_KEY=<loadtest key> -e ID_TOKEN=<token> tests/load/k6-search-and-book.js` — 25→200 rps in 5-minute steps, hold 10 min, 80% search / 20% booking | – |
| Per-service scaling | CloudWatch dashboard "Running tasks per service" | Availability scales out more than Booking; Merchant/Catalogue stay at minimum |
| Effect of more tasks | Fix desired count at 1/2/4 for Availability and Booking (`aws ecs update-service --desired-count`, scaling suspended), rerun the short profile | Near-linear throughput until the shared DB limits; report where |
| Latency | k6 thresholds | P95 search < 500 ms, P95 booking < 1 s at peak |
| Errors | k6 `unexpected_errors` | < 1% (409 conflicts reported separately) |
| Correctness | `tests/concurrency/same_slot.py --requests 100` with Booking at ≥3 tasks | exactly one 201 |
| Backlog | `python tests/load/event_backlog.py --aws --events 5000` | Notification scales out on backlog per task, clears without slowing bookings |

## Recovery drills (AWS)

| Drill | Command |
|---|---|
| Kill a Booking task under load | `aws ecs stop-task --cluster booking-test --task $(aws ecs list-tasks --cluster booking-test --service-name booking --query 'taskArns[0]' --output text)` |
| Notification down | `aws ecs update-service --cluster booking-test --service notification --desired-count 0`, book, then set it back to 2 |
| Availability down | same with `--service availability`; booking and cancellation keep working |
| Zero-downtime deploy | push a change to one service during the k6 run and watch errors stay < 1% |
| Failed deploy rolls back | deploy an image whose `/health/ready` fails; the circuit breaker restores the previous task definition |
| Trace | X-Ray: follow `POST /v1/bookings` → `publish batch` → `process BookingConfirmed` in Notification |
| Durability | restart all services; confirmed bookings remain (`GET /v1/bookings`) |
