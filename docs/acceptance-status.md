# Acceptance status

Updated 21 October 2026 (UTC+8). Planned criteria, implementation and observed results are distinct.

| Item | Status | Evidence / scope |
| --- | --- | --- |
| Core application and contracts | Verified | 60 core tests; five AWS services |
| Workload / operations tools | Verified | 23 regressions; controlled real k6; five concurrent cloud smoke journeys |
| Complete per-service delivery | Verified | All five source-63cc57ea runs executed tests, security, push, exact rollout, smoke and web/API ZAP |
| Public API documentation | Verified | /api-docs.html; five gateway specs match contracts; no key returns 403 |
| Full 35-minute workload | Passed | Actual 80/20 HTTP; per-phase search/201-only booking P95; dropped arrivals retained |
| Fixed 1/2/4 capacity comparison | Completed | Compare achieved rate and P95 under the same offered profile; not unrestricted capacity |
| 100-request multi-task race | Verified | Require 1x201, 99x409, zero network failures and at least three task identities |
| Automatic idle scale-in | Verified | Controlled 4-to-2 tasks for Availability and Booking; successful AlarmLow activities; no manual reduction after resuming scaling |
| Availability / Notification outages | Verified facts | Booking/cancel with search off; booking with inbox off; one confirmation after restart |
| Persistence and startup rollback | Verified separately | Reservation after every task replaced; ECS ROLLBACK_SUCCESSFUL for actual startup failure |
| Gateway to Booking to Notification trace | Verified | One trace includes the nested Notification consumer span |
| Task replacement / independent release under load | Verified | 25 HTTP/s controlled workload; other four service revisions must remain unchanged |
| 5,000-event burst | See dated result appendix | Normal and optional simulated processing cost remain separate; 2/s booking probes |
| Real queue retry / DLQ / duplicates | Verified | Dedicated synthetic malformed/duplicate messages; existing DLQ evidence preserved |
| Final baseline and smoke | Verified | All five services at two healthy tasks, normal notification processing and original scaling policies; final end-to-end smoke |
| Actual team effort / responsibilities / speakers | Pending team confirmation | Confirm actual effort, responsibilities and speaking assignments from team records |
| Final report | Template draft prepared | Team records and presentation feedback remain required before recorded 16 Nov deadline |

Peak SLOs apply to both 200 HTTP/s phases. Search P95 during the 50 and 100 HTTP/s ramp stages exceeded 500 ms and remains visible in the phase table; passing peak SLOs does not establish sub-500-ms search latency at every ramp stage.


Complete pipeline IDs: Merchant 39434349553; Catalogue 39434349573; Availability 39434349609; Booking 39434349616; Notification 39434349589. Initial Booking/Catalogue smoke conflicts and serial retries remain recorded. Scanner warnings are not described as zero vulnerabilities.

The original combined recovery harness failed a stale fixed-count wait after normal autoscaling. Outage facts and independent persistence verification are recorded separately; the failed raw result is preserved. Trace verification includes nested consumer subsegments.

The test environment has single-AZ RDS/cache. Task/service recovery does not demonstrate database failover or multi-region recovery. Failed historical/short measurements remain historical evidence and are not overwritten.

Machine-readable measurements: [acceptance-results.json](acceptance-results.json). Detailed report: [project-report-draft.md](project-report-draft.md). Editable slides and PDF deliverables are in the local workspace folder `../output/项目验收修复/`. Private raw records remain under `.local/acceptance` and `.local/loadtest-v2-*.json`; credentials and Terraform state are excluded from shared evidence.
