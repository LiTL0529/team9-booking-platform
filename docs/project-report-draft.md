# Project Report: Multi Merchant Appointment Booking Platform

Practice Module for Graduate Certificate in Architecting Scalable Systems, SE34FT

Team 9: CHEN YINLING, HE JIACHANG, LUO RUNZHOU, SANG HAOXIANG, ZHANG YUZHAO

Working draft, 21 October 2026 (UTC+8). This draft follows the supplied Project Report Template. Actual individual effort, responsibilities and presentation assignments are **pending team confirmation**. Presentation feedback must be incorporated after the presentation; the recorded final-report deadline is 16 November 2026. Planned targets are distinguished from observed results throughout.

## 1. Introduction

### 1.1 Background

Small sports venues often maintain separate booking channels. Customers must search several merchants, while every merchant repeats account, availability, reservation and notification development. Our project provides one shared booking platform, initially for sports courts with fixed one-hour slots and one active reservation per slot.

The implementation contains a React application, five Python FastAPI microservices and an AWS test environment. A customer can find availability across venues, reserve a slot, see the reservation and confirmation, cancel a future reservation and receive a cancellation message. Merchant and platform-administrator views expose the corresponding management operations.

### 1.2 Business Needs

Merchants need repeatable onboarding, resource publication and access to their own bookings. Customers need cross-merchant discovery and a reliable reservation decision. Partner developers need stable documented APIs and application-specific usage limits. The platform operator needs consistent access controls, monitoring and repeatable delivery.

Platform reuse is demonstrated through a merchant configuration file and a separate partner API client. A second complete user interface is outside this integration demonstration. Payment processing is outside the agreed implementation scope.

### 1.3 Stakeholders

| Stakeholder | Need | Implemented interaction |
| --- | --- | --- |
| Venue operator / merchant | Publish bookable supply and manage its bookings | Merchant and Catalogue APIs; merchant console |
| Customer | Discover, reserve and cancel appointments | Shared web application; private bookings and inbox |
| Partner developer | Reuse the platform's capabilities | Independent API key, usage plan and client |
| Platform administrator | Onboard and govern merchants | Administrator role; onboarding script and management API |
| Operations team | Deploy, observe and recover services | Terraform, per-service workflows, CloudWatch and X-Ray |

### 1.4 Project Scope

#### 1.4.1 Functionality in scope

The eight proposal use cases are merchant onboarding, resource and slot publication, availability discovery, booking creation, booking cancellation, merchant-scoped booking management, customer inbox notifications and partner integration. Slots are fixed at one hour. Resource ownership, valid future dates, booking state transitions and concurrent reservation correctness are enforced on the server and, where applicable, by database constraints.

The implementation scope also includes independently deployable services, a database and login per service, event contracts, gateway controls, reusable service and Terraform modules, automated tests and recorded cloud experiments. Public API documentation is now delivered through the deployed gateway and the `/api-docs.html` page.

#### 1.4.2 Functionality out of scope

The proposal excludes payments, refunds, recurring appointments, variable-duration bookings, multi-resource reservations, external calendars, SMS delivery, recommendations, multi-region disaster recovery and a service mesh. Production database failover and multi-region recovery are outside the demonstrated recovery scope. These exclusions are not counted as missing implemented features.

## 2. Project Conduct

### 2.1 Project Plan

The revised proposal estimated 50 person-days, approximately 10 per member. This is an estimate, not actual effort. The work breakdown covers requirements and contracts (6), shared template (3), AWS infrastructure (5), Merchant (2), Catalogue (3), Booking (6), Availability (3), Notification (2), web application (4), gateway and partner integration (2), monitoring (2), pipelines (4), quality tests (4), report and presentation (3), and contingency (1).

Planned milestones were revised proposal on 9 October, contracts and first deployment on 10-12 October, application completion on 13-17 October, integration and quality experiments on 18-20 October, and fixes and rehearsal on 21-22 October. Team 9's recorded presentation slot is 24 October 2026, 14:35-15:15 (UTC+8). Presentation feedback is to be incorporated before final submission.

### 2.2 Project Status

The core booking application is deployed. Verification on 20 October recorded 59 passing core tests; the added gateway-trace regression brings the current core suite to 60 tests (13 shared and 47 service tests). The corrected load and deployment tools have 23 additional regression checks, recorded separately from core business tests. Cloud acceptance status and evidence are maintained in `docs/acceptance-status.md`; the latest measured results are in the accompanying acceptance appendix.

Implemented functionality does not imply that every proposed quality target has passed. Earlier load results used a different request mix, and the 20 October afternoon rehearsal overlapped deployments. Those measurements remain historical evidence with limitations. The corrected runner now records the actual search/booking split, distinct booking inventory, successful-booking latency, conflicts, unexpected responses and dropped arrivals per phase.

### 2.3 Project Metrics

| Member | Actual effort | Main responsibility | Presentation assignment |
| --- | --- | --- | --- |
| CHEN YINLING | Pending team confirmation | Pending team confirmation | Pending team confirmation |
| HE JIACHANG | Pending team confirmation | Pending team confirmation | Pending team confirmation |
| LUO RUNZHOU | Pending team confirmation | Pending team confirmation | Pending team confirmation |
| SANG HAOXIANG | Pending team confirmation | Pending team confirmation | Pending team confirmation |
| ZHANG YUZHAO | Pending team confirmation | Pending team confirmation | Pending team confirmation |

Measured execution dates and identifiers should be taken from the evidence manifest. Fortnightly progress submissions, individual work attribution and actual total effort require team records and have not been inferred from the amount of source code.

## 3. Solution Overview

### 3.1 Logical Architecture and Design

The presentation layer consists of the shared web application and separate partner client. Both call versioned HTTPS endpoints through the gateway. The five business contexts are Merchant, Catalogue, Availability, Booking and Notification. Each context owns its database and communicates through APIs or versioned events, without reading another service's tables.

#### 3.1.1 Key Architectural Decisions

| ID | Decision | Rationale and cost |
| --- | --- | --- |
| AD-01 | Split into five business services | Search and booking can scale and release independently; more deployment and operational components |
| AD-02 | Database and login per service on one RDS instance | Clear ownership and low test cost; shared infrastructure remains a bottleneck and failure domain |
| AD-03 | Availability uses an event-built read model and Redis | Low-cost discovery; search may be stale and Booking must decide final availability |
| AD-04 | Booking uses one local transaction | Inventory claim, booking and outbox commit together; avoids a distributed transaction |
| AD-05 | Transactional outbox and consumer deduplication | Recovers from publish/consumer failures under at-least-once delivery; adds relay and event-state storage |
| AD-06 | Events carry a full slot snapshot and version | Out-of-order delivery converges; larger event payloads |
| AD-07 | Shared service template | Consistent token checks, tracing, health, retries and event handling; shared-library changes require multiple service checks |

#### 3.1.2 Tiers and Layers

The user interface calls a gateway that handles application keys, request limits, authentication and routing. FastAPI routers implement the business API. Domain operations use the owning database through SQLAlchemy. Background relays publish committed outbox events to SNS; SQS consumers update projections and inboxes. Redis is an optional acceleration layer: a cache failure falls back to database search through a circuit breaker.

#### 3.1.3 Nodes and Subsystems

Merchant owns merchants and memberships and publishes MerchantOnboarded. Catalogue owns resources and time slots and publishes SlotPublished. Booking owns slot inventory, reservations and its outbox and publishes BookingConfirmed and BookingCancelled. Availability consumes these events into MerchantView and SlotView. Notification consumes booking events into a customer-scoped inbox and records processed event IDs.

The Booking context can read a missing slot through Catalogue with bounded timeout, transient retries and a circuit breaker. Normal reservation decisions stay inside Booking. The Merchant service writes authorised role and merchant claims into Cognito; users sign in again to obtain changed claims.

#### 3.1.4 Platform Design

The platform's seed is bookable resource and slot data. Merchants are producers, customers and partner applications are consumers, and the administrator is the operator. Reuse is visible in configuration-based merchant onboarding, documented `/v1` endpoints, an independent partner key and usage plan, reusable booking rules and the shared runtime and Terraform modules.

The main aggregate invariants are one merchant per merchant user, valid non-overlapping one-hour slots per resource, at most one confirmed booking per slot, and cancellation only by an authorised owner before the appointment begins. Contracts are stored in `contracts/openapi` and `contracts/events` and checked against live application schemas in automated tests.

### 3.2 Physical Architecture and Design

#### 3.2.1 Key Architectural Decisions

| ID | Decision | Rationale and cost |
| --- | --- | --- |
| AD-08 | ECS Fargate, one service and task definition per context | Stateless tasks support independent scale and rolling release; sidecars share task resources |
| AD-09 | API Gateway REST, VPC link and internal NLB | Supports usage plans and application keys while keeping tasks private |
| AD-10 | S3 and CloudFront for web delivery | One HTTPS browser origin; API responses are forwarded to the gateway |
| AD-11 | SNS topics with subscriber queues and DLQs | Slow consumers do not block a reservation; operators must monitor retries and poison messages |
| AD-12 | GitHub OIDC deployment role | Avoids static AWS deployment credentials in the workflow |
| AD-13 | Small 0.25-vCPU tasks | Makes saturation observable within the test budget; resource contention must be measured |

#### 3.2.2 Technology and Services

The stack is React, Python FastAPI, SQLAlchemy, PostgreSQL, Docker and Terraform. AWS services include Cognito, CloudFront, S3, API Gateway, ECS Fargate, Service Connect, RDS, ElastiCache, SNS, SQS, Secrets Manager, CloudWatch, X-Ray, ECR and CodeBuild. Application tasks use private subnets across two availability zones. The current test RDS and Redis instances remain single-AZ; this is a material availability limit.

Every task has an application container and ADOT collector, plus the managed Service Connect proxy. The October tuning explicitly assigns CPU shares to the application, reduces tracing to a 10% parent-based sample and gives probes enough startup time. Sampled parent traces are retained. Task size remains 0.25 vCPU and 512 MB; adding explicit shares changes contention within that budget.

#### 3.2.3 Persistence Design

Merchant and membership data, resources and slots, reservations and inventory, search projections, notification inbox entries, outbox records and processed-event records survive process restarts. Separate database credentials and network controls enforce ownership. TLS and encryption at rest protect storage and transport. Secrets Manager holds database connection secrets. The proposal does not establish a production retention/deletion policy; that requires a separate product decision before real customer use.

Reservation correctness uses a conditional update from AVAILABLE to BOOKED, an incremented slot version and a partial unique constraint for confirmed bookings. A booking and outbox event are written in the same transaction. Duplicate request keys replay the original result for the same customer and intent; conflicting reuse is rejected. Cancelling increments the slot version and releases inventory in the same service.

The event stream is at least once. Each consumer's local transaction combines its projection/inbox update and processed-event record. This prevents a duplicate delivery from creating another notification. Version comparisons prevent older slot events from overwriting newer reservation state. Redis entries are disposable and can be rebuilt from persistent projections.

#### 3.2.4 Detailed Design

On reservation creation the gateway verifies access, Booking verifies the token and role again, checks idempotency, resolves inventory, atomically claims the slot and commits the booking and outbox. The API returns 201 with a reference. The outbox relay subsequently publishes the event. Availability updates search state and Notification adds an inbox entry. A customer whose search was stale can receive 409, which is reported separately from unexpected failures.

Cancellation verifies ownership and the future appointment time, changes the confirmed booking to CANCELLED, releases inventory and appends BookingCancelled. Consumers update their state asynchronously. A slow consumer can delay visibility; no fixed recovery bound is promised during an outage.

### 3.3 Other Architectural Decisions

Popular cross-merchant search JSON uses a short TTL instead of being invalidated by every reservation. Merchant-specific cache entries use date/merchant generation keys. This trades bounded staleness for a useful cache hit rate while Booking remains the final authority. Health checks use asynchronous liveness to avoid killing a busy task because synchronous database work is queued. Readiness remains available for diagnostics and smoke checks.

Container image tags include the source commit and workflow attempt. This permits retries without overwriting an immutable ECR tag. Deployment verification requires the intended revision, completed rollout and nonzero healthy task count; a successful automatic rollback is not misreported as a successful deployment of the failed version.

### 3.4 Architectural Limitations

| Issue | Impact | Resolution / status |
| --- | --- | --- |
| Shared single-AZ RDS | Shared capacity and failure domain | Report measured load; production multi-AZ and sizing remain future work |
| Single-AZ cache | Cache outage increases database search load | Circuit-breaker fallback implemented; production replica design remains future work |
| Small tasks and proxy/collector overhead | CPU contention and uneven task load affect latency | Explicit shares and sampling implemented; capacity validated by experiments |
| Eventual search and notification consistency | Briefly stale search or delayed inbox | Booking authority, versioned events, deduplication, retries and monitoring |
| Role claims cached in a token | Changed membership requires new login | Documented administrator workflow and reauthentication |
| Test-only operating configuration | No demonstrated database failover or multi-region recovery | Keep capacity and reliability claims within recorded evidence |

## 4. Quality Attributes

### 4.1 Performance

The proposal requires 100 merchants, 1,000 resources and at least 20,000 future slots; an approximately 80/20 search/booking workload from 25 to 200 HTTP requests per second in five-minute steps; ten additional minutes at peak; search P95 below 500 ms; successful-booking P95 below 1,000 ms; and unexpected errors below 1%. It also requests a fixed 1/2/4-task comparison and a 5,000-event notification burst.

The corrected runner prepares distinct free slots before measurement and schedules independent search and booking requests. One booking iteration sends one POST and cannot disappear because search returned no inventory. Success-only booking latency, expected 409 conflicts, other unexpected responses and dropped arrivals are separate metrics. It checks actual request counts for each phase and saves failing results. A short rehearsal is not the full-duration acceptance test.

The stable pre-tuning short baseline failed. After task resource tuning, the short rehearsal reached about 199.5 HTTP/s at peak with search P95 900 ms and successful-booking P95 490 ms, but had 43 dropped iterations. The first complete 35-minute run had zero unexpected errors and a clean final peak plateau (search 158 ms, booking 558 ms), but its first 200 HTTP/s stage had booking P95 1,119 ms and the run dropped 206 scheduled arrivals. Those failed records remain unchanged.

The next configuration lowers the Booking CPU target from 50% to 35%, reserves eight seconds of generator concurrency and uses a larger CodeBuild worker. Ramp-stage latency is explicitly exported without applying peak SLOs to the ramp. Workload rates and peak acceptance gates are unchanged.

Latest full-workload result: all measured acceptance gates passed.

Build: booking-test-images:1dfa98a1-e46d-4013-a3fa-f1a478049cea. Generator source: 186f0121c53c7cb97a48e3d8b87be31a4575a9d8. Measurement: 2026-10-20T15:19:46.535Z to 2026-10-20T15:54:46.662Z. Preparation traffic is excluded. The following P95 values use each phase; booking values include HTTP 201 only.

| Phase | Target HTTP/s | Actual HTTP/s | Search P95 ms | 201 booking P95 ms |
| --- | --- | --- | --- | --- |
| r25 | 25 | 25.0 | 342.8 | 275.4 |
| r50 | 50 | 50.0 | 1156.5 | 557.8 |
| r100 | 100 | 100.0 | 756.5 | 766.4 |
| r150 | 150 | 150.0 | 307.9 | 588.1 |
| r200 | 200 | 200.0 | 203.6 | 328.1 |
| peak200 | 200 | 200.0 | 165.9 | 258.1 |

Dropped iterations: 0. Unexpected server/network error rate: 0. Deployment overlap observed: False. Actual task definitions and scaling settings are retained with the raw result. The two maximum-rate phases are both checked; a passing final plateau does not hide a failing earlier peak stage. Search P95 exceeded 500 ms at the 50 and 100 HTTP/s ramp stages, so this result does not establish that search budget at every traffic level. Latency is measured by k6 from the CodeBuild client (sending, waiting and receiving), not from geographically distributed end users.

The fixed-capacity comparison suspends dynamic scaling for Availability and Booking, measures the same offered profile at one, two and four tasks each, then restores the previous scaling policy and limits.

| Tasks each | Sent HTTP/s | Successful HTTP/s | Peak errors % | Search P95 ms | 201 booking P95 ms | Run dropped |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 199.3 | 32.1 | 83.90 | 7421.0 | 7375.0 | 133 |
| 2 | 199.2 | 113.1 | 43.22 | 10013.0 | 9483.8 | 77 |
| 4 | 200.0 | 200.0 | 0.01 | 1134.3 | 990.5 | 0 |

These runs have an offered peak of 200 HTTP/s. Successful HTTP/s counts search 200 and booking 201 responses; sent HTTP/s includes failed responses, and the error column includes server/network failures. Dropped counts cover the complete short run. Reaching the offered ceiling does not establish maximum capacity. The accelerated three-minute profile can also capture cold-cache and saturation effects; it does not replace the full sustained workload. Low-capacity saturation and failures are retained; unrestricted linear growth is not assumed.

The strict 100-request same-slot race returned {'201': 1, '409': 99} across 4 identified Booking tasks. Network failures are not counted as conflicts.

The separate controlled four-to-two automatic idle scale-in exercise remains pending.

Each queue exercise sends exactly 5,000 synthetic booking events, checks SNS batch failures, records visible/in-flight depth and actual running tasks, and verifies the final synthetic-customer inbox count through a read-only query. Two-per-second booking probes record the baseline and burst period separately.

Run: 2026-10-20T16:35:29.725763+00:00. Per-event simulated processing cost: 0 ms. Queue quiet in 307.0 s; persisted notifications: 5000; actual queue-policy worker scale-out while work remained: False. Overall recorded gate: False.

| Booking probe period | Requests | Status counts | 201 P95 ms |
| --- | --- | --- | --- |
| baseline | 61 | {'201': 61} | 488.4 |
| burst | 601 | {'201': 601} | 411.7 |

Run: 2026-10-20T16:49:10.779790+00:00. Per-event simulated processing cost: 500 ms. Queue quietness not confirmed before the 904.7-second measurement ended; persisted notifications: 5000; actual queue-policy worker scale-out while work remained: True. Overall recorded gate: False.

| Booking probe period | Requests | Status counts | 201 P95 ms |
| --- | --- | --- | --- |
| baseline | 62 | {'201': 62} | 387.6 |
| burst | 1764 | {'201': 1764} | 395.0 |

A nonzero per-event cost is an explicit stress configuration, not the normal processing speed. If normal processing clears the burst before extra workers run, this is reported as delivery success without observed queue scale-out. The first cost-simulation run persisted all 5,000 events and scaled workers, but continuous booking probes kept a small queue tail alive, so its original quietness gate remains failed. The corrected runner stops probes when no visible backlog remains with at most two in flight, then still requires three quiet samples and exactly 5,000 persisted synthetic notifications. Low-rate probes check their latency budget and disclose the baseline/burst difference; they do not prove zero impact at the 200 HTTP/s peak.

### 4.2 Availability

Application services normally run at least two tasks, with health checks, replacement, rolling release and deployment rollback. SNS/SQS separates booking from search projections and notification delivery. The controlled recovery runner records booking and cancellation with Availability stopped, booking with Notification stopped and catch-up after restart, and reservation durability after all service tasks are replaced. It records the intended failed revision and this run's circuit-breaker events for an actual startup failure rollback.

Recorded AWS exercises confirmed booking and cancellation while Availability had zero tasks, booking while Notification had zero tasks, and exactly one confirmation after Notification restarted. A separate verification confirmed the reservation remained CONFIRMED after every service task was replaced. The first combined harness timed out because it incorrectly required the original autoscaled task count; its failed raw record is preserved and the durability evidence identifies this limitation.

The startup-failure exercise deployed Merchant revision 6 with an immediate exit. ECS deployment history recorded ROLLBACK_SUCCESSFUL at 13:48:51 UTC, automatically restoring revision 5; final convergence was verified at 13:51:27 UTC. Healthy old tasks remained available. The failed revision was deregistered after the exercise.

One X-Ray trace contains an API Gateway stage segment, a Booking HTTP 201 segment and the nested Notification BookingConfirmed consumer span. The corrected validator inspects nested spans; the first top-level-name-only harness result is retained.

Passing task/service recovery checks does not demonstrate RDS failover. Queue/DLQ configuration and local duplicate/retry tests are separate from real cloud execution.

The independent-release exercise uses a separate 25 HTTP/s, 80/20 workload. One Booking task is stopped, a healthy replacement is observed and only the Booking workflow is dispatched. Other four service task definitions must remain unchanged, and the new Booking revision must complete while measurement remains active. The controlled version release changes the version marker and image release; business features are unchanged.

| Event | Elapsed seconds |
| --- | --- |
| booking task stopped | 66.3 |
| booking task replaced | 256.7 |
| independent release dispatched | 256.7 |
| rolling deployment observed | 429.9 |
| rolling release completed under load | 826.3 |

Recorded recovery/release gate: True. This controlled workload does not establish a 200 HTTP/s fault-tolerance guarantee.

Real retry/DLQ and duplicate-message evidence remains pending its dedicated synthetic-message exercise.

### 4.3 Security

Cognito authentication, role checks, merchant membership and resource ownership protect operations. Customers can access only their own bookings and inbox; merchant users manage only their merchant. Services verify tokens independently of the gateway. Application API keys identify clients and enforce usage plans; user tokens establish user identity and authority. API keys do not replace user authentication.

Other controls are HTTPS, input validation, private task networking, service security groups, database-specific logins, storage encryption, Secrets Manager and scoped task IAM policies. Automated checks cover unauthorised and cross-merchant access, static analysis, secret detection, dependency and image vulnerabilities and a ZAP baseline. A green scanner job means the configured gate passed; it does not prove the absence of all vulnerabilities.

### 4.4 Extensibility and Maintainability

New merchants reuse the existing APIs and configuration. A new partner reuses identity, discovery, booking consistency, persistence and notifications through a distinct key and usage plan. Shared modules reduce repetition across services. A future capability should declare its owned data and events, publish a versioned contract, use the shared runtime and infrastructure module, and receive its own tests and release workflow.

Payments would require an explicit compensation design, such as a reservation/payment saga; it cannot safely be added as an unbounded synchronous call inside the existing inventory transaction. Moving a service database to another RDS instance changes its connection secret rather than granting cross-service table access.

## 5. DevOps and Development Lifecycle

### 5.1 Source Control Strategy

The monorepository separates services, shared code, contracts, Terraform, web, partner client, tests and operational scripts. Feature branches and pull requests provide a reviewable change set. Service path filters avoid deploying unrelated services for a service-only change; changes to shared runtime or pipeline definitions appropriately validate all consumers. Secrets and private infrastructure state are excluded from source control.

### 5.2 Continuous Integration

Each service workflow runs linting, shared and service tests, database integration and OpenAPI/event contracts, then secret/static/dependency checks, container build and image scanning. Pull-request runs execute checks without cloud deployment credentials. Infrastructure formatting/validation and the web build have their own checks. The workload tooling has additional regression checks and a controlled real-k6 verification.

### 5.3 Continuous Delivery

Main-branch workflows assume a scoped AWS role through OIDC, push an immutable versioned image, read the service's current task definition, register the updated image and perform a rolling test-environment deployment. The waiter verifies the exact intended revision, nonzero desired count and completed task convergence. Smoke tests and ZAP follow successful deployment; verification cannot be silently disabled by the previous skip variable.

The current scope has one cloud test environment. No production promotion process is claimed. All five workflows for source 63cc57ea completed the tests, security checks, image build/push, intended-revision rollout, smoke and both web/API ZAP steps on 20 October. Run IDs are Merchant 39434349553, Catalogue 39434349573, Availability 39434349609, Booking 39434349616 and Notification 39434349589. Booking and Catalogue verification initially collided on shared inventory; serial retries passed. The smoke selector now shuffles candidates and retries explicit 409 conflicts only; five concurrent complete cloud smoke journeys passed. Permission/server failures still fail immediately. Scanner warnings remain disclosed; configured scan gates are not a guarantee of zero vulnerabilities.

## 6. Demonstration and Follow-up

The live demonstration should show one coherent customer journey: discovery, reservation, confirmation, merchant visibility, cancellation and slot release. A second merchant configuration and the partner client demonstrate reuse. Use separate customer and merchant sessions and separate future inventory dates. Never display passwords, bearer tokens, API key values or raw Terraform state.

Quality claims should use dated evidence: the 100-request same-slot test, per-phase cloud measurements, task counts, recovery records and complete executed workflow jobs. The prepared presentation contains genuine application, pipeline and ECS screenshots. If the live environment fails, switch to those dated records and explain their limits.

Before submission the team must confirm actual member effort, responsibility and presentation allocation; review the final experiment results; record presentation feedback and responses; and verify the institution's submission instructions. These human records remain open rather than being estimated from the proposal.

## References and Evidence

- Revised proposal: `Team 9 Revised.docx`, 9 October 2026.
- Supplied report template and presentation guidelines in the project brief directory.
- Source: https://github.com/LiTL0529/team9-booking-platform
- Deployed application: https://d171mok9krptzk.cloudfront.net
- API documentation: https://d171mok9krptzk.cloudfront.net/api-docs.html
- Repository architecture and decisions: `docs/architecture.md`.
- Test method and historical results: `docs/testing.md`.
- Current status: `docs/acceptance-status.md` and dated acceptance appendix.
- Private raw experiment records: `.local/acceptance` and `.local/loadtest-v2-*.json`; publish only sanitised results.
