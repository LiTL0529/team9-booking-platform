# Multi Merchant Appointment Booking Platform

Team 9 · Practice Module, Graduate Certificate in Architecting Scalable Systems (SE34FT, NUS-ISS)

A cloud native booking platform built from five independently scalable microservices. Merchants
publish bookable resources and one-hour time slots; customers search across every merchant and
book, cancel and get notified in one application; partners integrate through the same versioned
API. The first business scenario is sports facility booking.

| Ecosystem role | In this platform |
|---|---|
| Seed | Bookable resources and their time slots (sports courts) |
| Producers | Merchants / venue operators (Merchant console, onboarding config) |
| Consumers | Customers (web app) and partner applications (partner client) |
| Platform operator | Platform admin: onboarding, access, operations |

## Repository layout

The deployed site includes [API documentation](docs/api-documentation.md) at `/api-docs.html`, with versioned specifications served through the gateway.

```
libs/platform_common/   Shared service template: token checks, logging, tracing, health checks,
                        DB access + migrations, transactional outbox, idempotent SQS consumers,
                        timeouts/retries/circuit breaker
services/
  merchant/             Merchant onboarding, merchant users and roles      (publishes MerchantOnboarded)
  catalogue/            Resources and non-overlapping one-hour slots        (publishes SlotPublished)
  availability/         Slot search: CQRS read model + Redis cache          (consumes all events)
  booking/              Slot inventory, booking/cancel, idempotency, outbox (publishes BookingConfirmed/Cancelled)
  notification/         In-app inbox from booking events                    (consumes booking events)
contracts/              OpenAPI document per service + JSON Schemas for every event (contract tests)
web/                    React web app (customer, merchant console, platform admin)
partner-client/         Separate API client with its own API key and usage plan
merchants/              Merchant onboarding files (a new merchant = a new YAML file, no code)
infra/terraform/        AWS: VPC, ECS Fargate, RDS, ElastiCache, SNS/SQS, Cognito, API Gateway,
                        CloudFront+S3, CloudWatch/X-Ray, GitHub OIDC deploy role
  modules/ecs-service/  Shared module: one ECS service with IAM, SG, NLB target, auto scaling
.github/workflows/      One DevSecOps pipeline per service (+ infra and web)
local/                  Local stand-ins: dev-auth (Cognito), gateway (API Gateway), moto bootstrap
tests/                  e2e smoke test, concurrency test, load tests (k6 + Python), backlog test
scripts/                Onboarding, data seeding, OpenAPI export, native runner, AWS bootstrap
docs/                   Architecture, decisions, testing, demo script, runbooks
```

## Run locally

### Option A — Docker Compose (mirrors AWS)

```bash
docker compose up --build -d
```

```bash
docker compose up -d --scale booking=3 --scale availability=2
```

| URL | What |
|---|---|
| http://localhost:3000 | Web app (nginx, same-origin `/v1` proxy like CloudFront) |
| http://localhost:8080 | API gateway stand-in (API key + token checks, rate limits) |
| http://localhost:16686 | Jaeger traces (X-Ray locally) |

### Option B — without Docker

Uses an embedded PostgreSQL (`pgserver`), moto for SNS/SQS and a local `redis-server` if present.

```bash
python -m venv .venv
```

```bash
.venv/Scripts/pip install -e libs/platform_common -r requirements-dev.txt "moto[server]==5.0.26" pgserver==0.1.4 pyyaml==6.0.2
```

```bash
.venv/Scripts/python scripts/dev_native.py up --scale booking=2 --scale notification=2
```

```bash
npm --prefix web install && npm --prefix web run dev
```

Web app on http://127.0.0.1:5173, gateway on http://127.0.0.1:8080. (Use `.venv/bin/` on macOS/Linux.)

### Load demo data and try it

```bash
python scripts/onboard_merchant.py merchants/city-courts.yaml
```

```bash
python scripts/onboard_merchant.py merchants/eastside-sports.yaml
```

```bash
python tests/e2e/smoke_test.py
```

Local accounts (all `Passw0rd!`, local only): `admin` (platform admin), `alice`, `bob` (customers),
`owner1`, `owner2` (become merchant admins when their merchant is onboarded), `partner`, `loadtester`.

## Tests

```bash
cd services/booking && ../../.venv/Scripts/python -m pytest -q
```

Each service has unit, database integration and contract tests (OpenAPI + event schemas). They need
PostgreSQL on `localhost:55432` (started by either local option) or `TEST_PG_URL`.

| Check | Command |
|---|---|
| 100 concurrent bookings of one slot | `python tests/concurrency/same_slot.py --requests 100` |
| Corrected stepped HTTP load, 80/20 mix | `python scripts/aws_loadtest.py --profile full --days 6` (requires at least 55,500 free slots) |
| Short cloud rehearsal | `python scripts/aws_loadtest.py --profile short --days 2` (requires 4,950 free slots) |
| Load-tool regression checks | `python -m pytest -q tests/load/test_tooling.py` |
| 5,000-event backlog | `python tests/load/event_backlog.py --events 5000` |
| Partner integration | `python partner-client/partner_client.py book --type futsal_pitch` |
| Seed 100 merchants / 1,000 resources / 20,000 slots | `python scripts/seed_load_data.py` |

See [docs/testing.md](docs/testing.md) for what each test proves and the results recorded so far.
See [docs/acceptance-status.md](docs/acceptance-status.md) for implemented features, verified evidence and remaining proposal acceptance. Historical whole-run load summaries do not establish peak-stage successful-booking targets.

## Deploy to AWS

See [docs/deployment.md](docs/deployment.md). In short: `python scripts/aws_deploy.py all` (images are
built in AWS CodeBuild, no local Docker needed), then every push to `main`
runs the per-service pipeline: lint → tests → SAST/secrets/dependencies → image build + Trivy →
push to ECR → rolling ECS deployment → smoke test + OWASP ZAP baseline.

## Documentation

- [Architecture and key decisions](docs/architecture.md)
- [Testing and evidence](docs/testing.md)
- [Deployment and operations](docs/deployment.md)
- [Demo script for the presentation](docs/demo-script.md)
