# Demo script (8 + 2 minutes)

Follows section 6 of the presentation guidelines. Prepare beforehand: AWS environment up, data
seeded, k6 installed, the CloudWatch dashboard and X-Ray open in browser tabs, two terminals.

| Time | Show | Commands / clicks | Point to make |
|---|---|---|---|
| 0:00 | Customer workflow | Web app → search across venues → book → My bookings → Inbox | One app over all merchants; notification arrives asynchronously |
| 1:30 | Merchant view | Sign in as `owner1` → resources, publish slots, bookings | Merchants see only their own data (token claim + server checks) |
| 2:30 | Platform reuse | `python scripts/onboard_merchant.py merchants/eastside-sports.yaml`, then the new venue appears in search | New merchant by configuration, no code change |
| 3:15 | Partner client | `python partner-client/partner_client.py book --type futsal_pitch` | Separate API key/usage plan, reuses booking rules, login, storage, notifications |
| 4:00 | Correctness | `python tests/concurrency/same_slot.py --requests 100` | Exactly one 201 across several Booking tasks |
| 4:45 | Scalability | Start `k6 run -e PROFILE=short ...`; dashboard: Availability task count rises, Merchant/Catalogue stay at 2 | Each service scales on its own load |
| 6:00 | Resilience | `aws ecs update-service ... notification --desired-count 0`, book in the web app, scale back to 2, inbox fills | Event-driven decoupling, queued events processed once |
| 6:45 | Tracing | X-Ray trace of one booking through gateway → Booking → Notification | OpenTelemetry in the template |
| 7:15 | DevOps | Push a one-line change to one service; show only that workflow running; ECS rolling update while k6 runs | Independent pipelines, zero-downtime deploy, auto rollback |

Fallback if the cloud is unavailable: run the same steps on the local stack
(`docker compose up` or `scripts/dev_native.py up`) — everything except auto scaling and X-Ray
(Jaeger at http://localhost:16686 instead).
