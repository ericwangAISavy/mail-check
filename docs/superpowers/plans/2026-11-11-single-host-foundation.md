# Single-host microservice foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Deliver a separately startable, tested service foundation and host preflight without migrating production accounts or pretending the business migration is complete.

**Architecture:** Independent Core, Mail and Intelligence entry points share transport primitives, not business tables. PostgreSQL has distinct domain owners/runtime roles; RabbitMQ has domain queues and topic permissions. Docker Compose publishes only a loopback edge. Current legacy startup and data remain intact.

**Tech Stack:** Python/FastAPI, psycopg3, aio-pika, PostgreSQL 17, RabbitMQ 4, nginx, Docker Compose, Windows PowerShell launcher.

**Spec:** docs/architecture/SINGLE_HOST_MICROSERVICES.md and REALTIME_MAIL_UPDATES.md.

## Global Constraints

- Windows 11/i5-12400/16 GB; Linux containers under WSL2; preserve current AI model.
- No production cutover, credential export or data mutation during this foundation phase.
- Separate service DB credentials, no published DB/broker/model ports, file-based local secrets.
- Commit-ordered journal positions; transactions release connections before streaming waits.
- Broker queues reject overflow rather than discard accepted work; service groups receive independent deliveries.
- Foundation endpoints must declare business readiness false; no anonymous fake inbox or successful placeholder business actions.

## Review Focus

- Secrets missing, weak or symlinked: fail closed without printing values.
- Dependency outages: liveness survives; dependency readiness returns sanitized failure.
- Concurrent journal writes: committed barriers cannot skip late transactions; duplicate events do not increment counts.
- Wrong DB/broker credentials: cross-domain operations must fail against real containers.
- Existing local deployment and secrets: bootstrap never overwrites them; edge remains loopback and migration state explicit.

### Task 1: Service runtime and configuration

**Files:** Create mailcheck/services/{__init__,settings,app,__main__}.py; tests/test_service_foundation.py.
**Interfaces:** ServiceSettings.load(role, environ); create_service_app(settings, probe); roles core/mail/intelligence; /health/live, /health/dependencies, business routes return 503 migration_not_ready.
- [x] Write failing config/health tests, including missing secrets, invalid role, sanitized dependency errors and explicit business readiness.
- [x] Implement bounded probes and service entry points without importing the legacy web app.
- [x] Verify focused tests and commit with a ledger entry.

### Task 2: PostgreSQL ownership, migrations and event journal

**Files:** Create mailcheck/services/{database,journal}.py, migrations/*.sql, mailcheck/services/provision.py; tests/test_service_postgres.py.
**Interfaces:** migrate_domain(connection); Journal.append(workspace_id,event_id,account_id,kind,payload), barrier(workspace_id), replay(workspace_id,after,limit); runtime role has DML only.
- [x] Write failure-first integration tests against isolated temporary PostgreSQL databases.
- [x] Add transactional versioned migrations, owner/runtime separation, per-workspace head locking and unique source-event deduplication.
- [x] Prove rollback, duplicate and reverse-commit behavior plus cross-domain isolation with real SQL; commit.

### Task 3: Durable broker topology

**Files:** Create mailcheck/services/{broker,bootstrap}.py; tests/test_service_broker.py.
**Interfaces:** build_definitions(secrets); BrokerProbe; persistent event publication with confirms/mandatory routing and service-owned queues.
- [x] Write tests for independent consumer groups, topic permissions and queue overflow policy.
- [x] Implement generated salted password-hash definitions and bounded queues, with no public management port.
- [x] Verify real delivery, unroutable publication and wrong-domain access against RabbitMQ; commit.

### Task 4: Local deployment, secrets and Windows preflight

**Files:** Create deployment/microservices/{compose.yaml,Dockerfile,nginx.conf,rabbitmq.conf,README.md}, mailcheck/services/{manage,preflight}.py, tools/microservices.ps1, .dockerignore; update .gitignore and optional service dependencies in pyproject.toml.
**Interfaces:** python -m mailcheck.services.manage init|migrate|verify; doctor emits nonsecret JSON and never declares hardware/boot gates passed without measurements.
- [x] Write bootstrap-preservation, network/config and preflight tests.
- [x] Implement separate role images/commands, restricted service networks, named volumes, memory ceilings, health checks and one-shot migrations.
- [x] Keep secrets under ignored .local directory; never overwrite initialized credentials. Loopback edge uses a different port from legacy 52400.
- [x] Run compose config, build images and bring up the isolated foundation; verify health, dependency failure/recovery and non-ready business paths.
- [x] Document actual Windows/model/cold-boot gates still requiring the user's host; commit.

### Task 5: Release, regression and independent review

**Files:** release metadata, implementation status/ledger, CI/test instructions.
- [x] Record a minor foundation release once; production runtime remains legacy until later phases.
- [x] Run full backend/frontend suites and production build; run real PostgreSQL/RabbitMQ integration tests and container smoke tests.
- [x] Get one fresh whole-change review, fix important findings with regression tests and update completed task evidence.
- [x] Commit and push the new branch; state precisely which migration phases are still unimplemented.

## Subsequent implementation plans

After the foundation is verified: Core auth/business persistence and SQLite importer; Mail credential/provider extraction; durable scheduling and Intelligence extraction; authenticated SSE/browser updates; actual-host capacity/cold-boot rehearsal; data migration and cutover. These are not silently represented as completed by foundation health checks.


## Verification evidence — 2026-11-11

- Release 2.28.0; full backend: 971 passed, 98 subtests passed; frontend: 523 passed; production frontend build passed (existing bundle-size warning).
- Real PostgreSQL/RabbitMQ tests exercised role isolation, repeatable migrations, event replay ordering/deduplication, transactional rollback, outbox retry/identity validation and broker routing/permissions.
- Final Docker images built and the isolated Compose stack passed all domain dependency probes and loopback edge verification; Core reports version 2.28.0 and business_ready=false.
- PostgreSQL and RabbitMQ were stopped individually: edge/Core liveness remained available, readiness returned sanitized 503, then recovered without API restart.
- Independent whole-change review found unexpected PostgreSQL role memberships and divergent outbox event identity. Both were reproduced before fixes and covered by passing real-database regression tests.
- Windows 11 ACLs, unattended cold boot, model peak memory and 50-user capacity were not tested on this Linux executor. No production data migration or public-domain cutover was performed.
