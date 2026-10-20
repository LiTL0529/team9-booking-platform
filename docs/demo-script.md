# Demo script

Use the revised 20-slide Integrated deck and speaker guide in the workspace `output/答辩修订版` folder. The customer flow and commands are detailed in the workspace `答辩当天演示操作单.md`.

## Core demonstration 8 minutes

| Time | Action | Evidence and explanation |
| --- | --- | --- |
| 0:00–1:20 | Alice searches 25 October, books City Courts, opens My bookings and Inbox | Same booking reference; asynchronous notification |
| 1:20–2:40 | Owner1 shows the reservation in an independent session; inspect and run Northpoint YAML | Merchant-scoped view; reusable onboarding. Northpoint has no members entry, so do not claim owner assignment |
| 2:40–4:00 | Partner books 26 October; 100-request race uses 27 October | Independent key plus token; actual success/conflict counts and task distribution |
| 4:00–5:20 | Monitoring and labelled historical scaling evidence | Running task samples, configured limits and account quota are different facts |
| 5:20–6:00 | Open successful Booking workflow 39050921193 or a newer verified run | Show executed jobs, not just workflow configuration |
| 6:00–8:00 | Explain measured results and open acceptance | Historical whole-run values do not prove peak-stage success-only acceptance |

Use prepared load evidence in the core demonstration. Do not run load concurrently with deployment. The 20 October short rehearsal failed thresholds and overlapped pipeline retries. Prepare at least 4,950 distinct free slots on dedicated dates. The 29–30 October dates correspond to `--start-day 5` on 24 October and `--start-day 9` on 20 October. Check remaining inventory before every repetition.

Notification outage, X-Ray tracing and a new deployment are optional follow-ups after rehearsal, not required in the core sequence. If the cloud stalls, play a labelled local recording. A local fallback stack is useful only if already running and rehearsed.

Actual effort, responsibilities and speaking assignments remain pending team confirmation. Follow [acceptance status](acceptance-status.md); do not present pending tests as complete.
