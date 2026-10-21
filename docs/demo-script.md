# Demo script

Updated 21 October 2026 (UTC+8). Use the 24-slide Acceptance deck and speaker guide in the workspace `output/项目验收修复` folder. Slides 1–20 form the core presentation; 21–24 are optional evidence. Complete pasteable commands are in the current workspace `答辩当天演示操作单.md`. Older Integrated materials are historical versions.

## Core demonstration 8 minutes

| Time | Action | Evidence and explanation |
| --- | --- | --- |
| 0:00–1:20 | Alice searches 25 October, books City Courts, opens My bookings and Inbox | Same booking reference; asynchronous notification |
| 1:20–2:40 | Owner1 shows the reservation in an independent session; Alice cancels it; inspect and run Northpoint YAML | Merchant view, cancellation and released slot, reusable onboarding. Northpoint has no members entry, so do not claim owner assignment |
| 2:40–4:00 | Partner books 26 October; 100-request race uses 27 October | Independent key plus token; actual success/conflict counts and task distribution |
| 4:00–5:20 | Monitoring and labelled historical scaling evidence | Running task samples, configured limits and account quota are different facts |
| 5:20–6:00 | Open successful Booking workflow 39453602689 and gateway API documentation | Executed jobs and five delivered API specifications |
| 6:00–8:00 | Explain measured results and acceptance scope | Both 200 HTTP/s stages passed; ramp-stage search latency remains visible |

Initialize AWS profile, region, local Terraform paths and private configuration in one PowerShell window. Set `PYTHONUTF8=1` and use Python `-X utf8` to avoid the original GBK decode failure. `scripts/start_demo.ps1` initializes the environment and requests two tasks; then verify that all five ECS services stabilize. Browser console login does not establish valid CLI credentials.

Use the load-test key for the concurrency race and restore the original key in `finally`. The live command is `tests/concurrency/same_slot.py --requests 100 --min-tasks 2 --date 2026-10-27`: require exactly one 201, ninety-nine 409 responses, no final network failures and at least two actual task identities. The separate acceptance race requires at least three. Report actual task distribution and fall back to the saved record if the live check fails.

Use prepared load evidence in the core demonstration. The latest full 35-minute run delivers 277,500 business HTTP requests, 55,500 successful bookings and the actual 80/20 mix, with zero unexpected errors and dropped iterations. Both maximum-rate stages pass the peak latency gates. Search P95 at 50 and 100 HTTP/s remains above 500 ms; do not claim the search budget holds at every ramp stage. Earlier failed measurements remain historical records.

Task loss and independent release are a separate 25 HTTP/s exercise. Only Booking changes task definition; the release updates its image/version marker with business features unchanged. Do not generalize it to a 200 HTTP/s recovery guarantee. Queue tests distinguish normal processing and explicit simulated delivery cost, with only two booking probes per second. Idle scale-in is verified in a separate controlled exercise rather than an uninterrupted extension of the full-load curve.

If a short cloud run is requested after the main demonstration, rehearse first, prepare at least 4,950 distinct free slots, avoid concurrent deployments and calculate CodeBuild date offsets from UTC. A short test cannot replace full acceptance. Repeated seeding does not free booked slots. Check remaining inventory before every repetition.

Notification outage, X-Ray tracing and a new deployment are optional follow-ups after rehearsal, not required in the core sequence. If the cloud stalls, play a labelled local recording. A local fallback stack is useful only if already running and rehearsed.

Actual effort, responsibilities and speaking assignments remain pending team confirmation. Follow [acceptance status](acceptance-status.md); do not present pending tests as complete.
