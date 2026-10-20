# Acceptance status

Updated 20 October 2026. Proposed acceptance criteria are kept separate from implemented features and observed results.

| Item | Status | Evidence / next action |
| --- | --- | --- |
| Core application and contracts | Verified locally | 59 passing core tests; five services running in AWS |
| Revised load tools | Verified locally | 8 regression checks and a controlled real k6 run |
| AWS business workflow | Verified historical run | Booking workflow 39050921193 includes smoke and scan steps |
| Historical AWS load | Recorded, method limited | Run 2 was about 92.4/7.6 business HTTP requests; P95 is whole-run, booking includes conflicts |
| Corrected short AWS workload | Failed rehearsal | 20 October: peak 139.8 HTTP/s, search P95 10,013 ms, 201-only booking P95 8,539 ms; 6,151 dropped iterations. Concurrent deployments prevent steady-state interpretation |
| Full peak performance acceptance | Open | Corrected 35-minute cloud run with peak-stage 201-only booking latency |
| Fixed 1/2/4 task capacity comparison | Open | Save original scaling settings, suspend dynamic scaling for controlled runs, then restore settings |
| Four remaining service pipelines | Partly verified | OIDC and image push passed. Catalogue/Notification deploy passed; Merchant/Availability waiter timed out, then ECS converged. All four smoke/DAST jobs skipped; complete verification remains open |
| Recovery / rollback evidence | Partly open | Record Availability outage, restart persistence and an actual liveness/startup failure rollback |
| Public API documentation delivery | Verified in AWS | `/api-docs.html` displays all five services; `/v1/docs/<service>/openapi.json` matches repository contracts; missing API key returns 403 |
| Team effort and speaking assignments | Pending team confirmation | User explicitly requested this status; do not invent actual effort |
| Final report | Drafting remains | Use formal template and include presentation feedback before the recorded 16 November deadline |

Source identifiers and raw logs are recorded in `.local/review/` and `.local/defense-build/`. Do not publish credentials or private raw infrastructure state as evidence.

The current ECS deployment probes use `/health/live`. A readiness-only failure is not a valid demonstration that these probes trigger rollback. Application tasks span two AZs; the RDS and Redis test instances remain in a single AZ each.
