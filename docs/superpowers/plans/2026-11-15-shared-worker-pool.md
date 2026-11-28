# Shared Worker Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox syntax for tracking.

**Goal:** Introduce opt-in RabbitMQ execution with bounded shared processes and unchanged application database schemas.

**Architecture:** Explicit context selects workspace paths and credentials per operation. Shared API processes and shared RabbitMQ consumers replace per-admin processes when enabled; the current runtime remains the default until an intentional drained restart.

**Tech Stack:** Python, FastAPI, pika/AMQP, local filesystem locks, existing SQLite, React/SSE.

**Spec:** docs/superpowers/specs/2026-11-15-shared-worker-pool-design.md

## Global Constraints

- Do not migrate, rewrite, or touch existing user databases during implementation or validation.
- Do not stop, restart, or interrupt existing services/jobs. Use temporary fixture databases only in tests.
- Latest user constraint supersedes SQLite lease tables: use same-host process locks outside databases.
- No process-global environment mutation for workspace dispatch. Existing separate databases and credential namespaces remain.
- New runtime requires explicit configuration; no automatic live cutover.

## Review Focus

- Identical account IDs/labels across admins must never select another database or keyring entry.
- Context must follow asynchronous/thread boundaries and reset on exceptions.
- Broker failure during confirmed retry/outbox publication must preserve original work.
- Worker crashes and disabled workspaces must not allow unauthorized commits.
- Shared API caches and scheduler state must not become cross-admin globals.

### Task 1: Explicit workspace context

Files: mailcheck/workspaces.py, config.py, maintenance.py; tests/test_workspace_context.py.
Interfaces: WorkspaceContext, bind_workspace(context), current_workspace(), start_workspace_thread().
- [x] Add failing context/path/credential isolation tests; run them RED.
- [x] Implement immutable context and path resolution without environment mutation; pass GREEN.

### Task 2: RabbitMQ transport and runtime locks

Files: mailcheck/shared/{broker,state}.py; tests/test_shared_broker.py.
Interfaces: RabbitBroker.enqueue/claim/ack/fail/publish, same-host operation locks, file-backed job status.
- [x] Test envelope validation, confirmed routing, retry ownership and lock exclusion RED.
- [x] Implement durable queues, confirms, bounded retry tiers, dead letters and external runtime state; verify GREEN.

### Task 3: Shared API execution

Files: mailcheck/shared/{api,pool}.py; mailcheck/web/app.py; gateway.py; tests/test_shared_api.py.
Interfaces: shared ASGI dispatcher and WorkerPool-compatible fixed-size API pool.
- [x] Test concurrent workspace API reads, per-workspace mutable state and bounded process allocation RED.
- [x] Implement context binding, worker authentication, isolated API state and thread propagation; verify GREEN.

### Task 4: Shared job execution and gateway events

Files: mailcheck/shared/{runtime,events}.py; realtime/runtime.py; gateway.py; tests/test_shared_runtime.py.
Interfaces: coordinator, fixed consumer pool, authenticated manual job dispatch, change fan-out.
- [x] Test automatic opt-in versus manual dispatch, outbox confirmation and reconnect resync RED.
- [x] Implement consumers/coordinator and opt-in gateway integration without starting per-admin runtimes; verify GREEN.

### Task 5: Deployment, release and verification

Files: docs/SHARED_WORKERS.md, deployment examples, pyproject.toml, release metadata, frontend bundles.
- [x] Document drained cutover/rollback and no-schema-change constraints.
- [x] Run new and existing backend/frontend checks against temporary state and local test broker only.
- [x] Add required release entry, build bundles and obtain independent code review.

## Execution ledger

Ruling: user has authorized implementation; proceed without another approval round.
Ruling: retain current runtime as default and gate shared mode explicitly to avoid interrupting active jobs.
Ruling: replace proposed database lease changes with existing same-host file lock primitives; no schema changes.

Ruling: delegate isolated transport, context, API-pool, event and test modules under
the subagent-driven-development skill; root integrates and independent reviewers
check cross-module failure behavior.

Ruling: shared model admission uses one OS file lock rather than gateway HTTP
admission, so a multi-batch operation can finish while the gateway drains. The
single-model limit and same-host deployment constraint remain; legacy is unchanged.

Progress: tasks 1–4 implemented. Actual gateway/shared process startup and two-admin
HTTP isolation passed. Five real-RabbitMQ end-to-end checks passed, including
connection-close redelivery and unchanged schema fixtures. Task 5 completed: final full backend suite 1161 passed, 17 skipped, 102 subtests passed; frontend 546 passed; production build, release consistency and dependency checks passed. Independent review findings were fixed and verified with regression tests.

Final review: independent review identified terminal manual status, calendar sync alias and reconciliation fairness defects. Regression tests reproduced the defects and verified the fixes. No remaining confirmed critical/important findings; final edits were verified by regression tests rather than a second independent review.

Completion: real RabbitMQ delayed retry and persistent-message survival across restart passed using the isolated test broker. Existing application schema remains version 50. No deployment, merge or push performed; existing services were not restarted.
