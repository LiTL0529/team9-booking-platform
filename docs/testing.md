# Testing and evidence

Latest acceptance update: **21 October 2026 (UTC+8)**. The complete corrected 35-minute workload passed its actual 80/20 delivery and both peak-stage latency gates: 277,500 business HTTP requests, 55,500 successful bookings, no dropped iterations and no unexpected errors. The two 200 HTTP/s phases recorded search/201-booking P95 of 203.6/328.1 ms and 165.9/258.1 ms. Search P95 at the 50 and 100 HTTP/s ramp stages remained above 500 ms; this is not a claim of sub-500-ms latency at every stage.

Current tested task ranges are Availability 2–12, Booking 2–8, Notification 2–5 and Merchant/Catalogue 2–2; Availability and Booking CPU targets are 35%. Tasks use 0.25 vCPU, the current regional Fargate quota is 30 vCPU, and the full-load generator uses a LARGE CodeBuild worker. Earlier quota, ranges, profiles and failed results below are dated historical observations. The full result records actual scaling configuration, task definitions, source/hash identifiers and UTC timing.

See [acceptance status](acceptance-status.md) and the accompanying report for the fixed-capacity comparison, strict multi-task concurrency race, controlled idle scale-in, backlog and queue exercises. The separate 25 HTTP/s recovery/release test passed with 5,400 successful bookings, zero unexpected errors, actual task replacement and an in-measurement rollout of Booking only. It does not establish fault tolerance at 200 HTTP/s.

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

Current core suite: **60 tests** (13 template + 47 service), including the gateway-trace regression added after the earlier 59-test snapshot. Service tests use an isolated PostgreSQL instance. The earlier 57- and 59-test results remain historical snapshots.

The workload and operations tools have **23 additional regression tests** (`python -m pytest -q tests/load/test_tooling.py tests/operations`). A real local k6 run against a controlled HTTP server also verified lower- and peak-stage P95 export, the 80/20 request counts, distinct slots across phases, continued booking requests when searches return no slots, separate 409 reporting, and failure on an unexpected 403. These verify the tools, not AWS capacity.

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

## Results on AWS (ap-southeast-1, 17 October 2026)

Load generated by k6 inside AWS (CodeBuild, same region) with `python scripts/aws_loadtest.py`;
the original iteration-based profile, configured from 25 to 200 iterations/s. The original booking branch also searched and skipped booking when inventory was empty. Run 2 recorded 251,370 searches and 20,676 booking POSTs, approximately **92.4% search / 7.6% booking business HTTP requests**, rather than a sustained 80/20 request mix.
Dataset: 100 merchants, 1,000 resources, 20,000 slots per run. Tasks 0.25 vCPU; account Fargate
quota 6 vCPU, so Availability was capped at 6 tasks.

| Metric | Run 1 (first build) | Run 2 (after fixes) | Target |
|---|---|---|---|
| Requests served | 173,905 | 272,047 | – |
| Average rate (offered ≈ 132/s) | 81.5/s | 127.7/s | – |
| Search median / P95 | 5,382 / 10,012 ms | 23 / 1,896 ms | Whole-run summary; search target not met |
| Booking response median / P95 | 327 / 10,011 ms | 33 / 918 ms | Whole run, including 409; peak success-only target not established |
| Unexpected errors | 25.07% | 0.14% | < 1%: met |
| Bookings made / expected 409s | 18,074 / 595 | 20,140 / 536 | – |
| Peak tasks (avail / booking / notif) | 6 / 3 / 2 | 7 / 5 / 3 | – |

All latency values above are whole-run summaries, not separately measured peak-phase values. Running-task samples can include transient deployment/replacement overlap. At that historical configuration, task ranges were Availability 2–6, Booking 2–5, Notification 2–5 and Merchant/Catalogue 2–2. Account vCPU quota and service MaxCapacity are separate constraints. The brief sample of 7 tasks alone does not establish an autoscaling limit of 7 or a proven root cause of latency.

Fixes between the runs (all shipped as a rolling update with no downtime):
1. Load-balancer health checks use an async `/health/live` (no database), 3 failures, 60 s grace —
   run 1 showed ECS replacing busy-but-working tasks ("death spiral") while RDS CPU stayed < 36%.
2. Cache invalidation per (date, merchant); cross-merchant searches cached with a 5 s TTL — run 1's
   hit rate was ~50% because every booking invalidated the whole date.
3. Uvicorn keep-alive 400 s (above the NLB's 350 s idle timeout) — fast 504s from reused connections.
4. Redis connect timeout 1 s; CPU scaling target 50%; DB pool 10 for Availability and Booking.

Other results on AWS: smoke test passed; 100 concurrent requests for one slot → 1 × 201, 99 × 409
across 2 Booking tasks in 2 AZs; partner client booked with its own API key; merchant onboarding from
YAML in 13 s; 5,000-event backlog cleared 32 s after the burst began; booking succeeded with the
Notification Service at 0 tasks and the confirmation was delivered once after restart; a Booking task
stopped at peak load was replaced automatically.

## Cloud scalability test plan (AWS test environment)

Targets from the proposal; capacity claims are limited to the workload actually tested.

### Corrected workload and evidence

`scripts/aws_loadtest.py` now prepares a read-only snapshot of free slots before measurement, then runs independent search and booking scenarios. Each phase schedules 80% GET searches and 20% POST bookings. Booking uses distinct preselected slots and does not add a measured search request or silently disappear when searches return no inventory. Small scheduler boundary iterations are capped at the declared request quotas.

The short profile requires 4,950 distinct free slots and runs for 3 minutes. The full profile requires 55,500 distinct free slots and runs for 35 minutes; its default six dates allow 60,000 slots with the standard 100 × 10 × 10-hour dataset. These are inventory requirements, not measured capacity claims.

```powershell
# Prepare inventory on dedicated dates first. This changes test data.
.venv\Scripts\python -X utf8 scripts\seed_load_data.py --starts-in-days 9 --days 2
# Run the corrected short profile from CodeBuild; adjust the date offset for the day of execution.
.venv\Scripts\python -X utf8 -u scripts\aws_loadtest.py --profile short --start-day 9 --days 2
```

The runner records per-phase request counts, achieved HTTP/s, success counts, search P95 and **201-only booking P95**. It reports 409 conflicts, unexpected 4xx/5xx/network responses, dropped iterations and inventory errors separately. It saves the summary even when thresholds fail and returns a nonzero exit code. CodeBuild preparation time is explicitly included only in the task-count timeline, not the measured phase duration.

For local k6 use, run `scripts/prepare_load_test.py` first, then set `API_KEY` and `ID_TOKEN` (or local auth credentials) before running `tests/load/k6-search-and-book.js`. Default preparation files are under `.local/` and contain slot identifiers and workload metadata, never credentials.

See [acceptance status](acceptance-status.md) for completed results and remaining tests. Historical data remains unchanged.

| Area | How | Target |
|---|---|---|
| Dataset | `scripts/seed_load_data.py` (100 merchants, 1,000 resources, ≥20,000 slots) | – |
| Load profile | `python scripts/aws_loadtest.py --profile full --days 6` — stepped total HTTP rates 25→200, 5-minute phases, plus 10 minutes at 200; 80/20 request split | Corrected-method cloud result required |
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
| Failed deploy rolls back | deploy a test revision that fails startup or the configured `/health/live` probe; record failure and restored task definition. Readiness-only failure does not trigger the current liveness-based ECS checks. |
| Trace | X-Ray: follow `POST /v1/bookings` → `publish batch` → `process BookingConfirmed` in Notification |
| Durability | restart all services; confirmed bookings remain (`GET /v1/bookings`) |
