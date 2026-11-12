# Usable PostgreSQL Microservice Application Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing application with a working native Windows microservice application that imports the complete legacy backup, preserves all supported workflows and stores authoritative business data in service-owned PostgreSQL databases.

**Architecture:** Retain the approved Core/Mail/Intelligence boundaries and existing browser API contract. Core owns identity/business data and explicitly versioned Mail projections; Mail owns accounts, credentials, messages and provider operations; Intelligence owns inference jobs/results. Services communicate through authenticated internal contracts and durable events, never cross-database SQL.

**Tech Stack:** Python/FastAPI, PostgreSQL 17, RabbitMQ 4.1, React, separate Windows services/processes, native PostgreSQL/RabbitMQ (supported Erlang/OTP), and a native static/reverse-proxy edge. Docker is optional tooling, not a runtime prerequisite.

**Spec:** `docs/architecture/SINGLE_HOST_MICROSERVICES.md`, `docs/architecture/REALTIME_MAIL_UPDATES.md`.

## Global Constraints

- User selected **Full PostgreSQL migration**, not a staged SQLite production release.
- Deployment decision updated November 12, 2026: **no Docker or WSL dependency** for the working application. Core, Mail and Intelligence run as native Windows services/processes; PostgreSQL and RabbitMQ are installed directly on Windows. Existing Docker foundation files remain optional and do not satisfy native acceptance gates.
- Preserve accounts, passwords, OAuth connections where exportable, workspace isolation, bidder permissions, sourcing history, classifications, assignments and recorded payments.
- Preserve the existing AI model and its classification behavior initially.
- One Windows 11/i5-12400/16 GB server; target 50 concurrent users; capacity remains a measured acceptance gate.
- Original backup, original SQLite installation and its launch path remain unchanged until verified cutover; no live dual writers.
- OS keyring credentials are absent from portable backups. Imported accounts requiring reconnection must explicitly show that state; never silently reuse unrelated destination credentials.
- The public domain continues to point at the current working deployment until functional parity, import validation and rollback rehearsal pass.
- `business_ready` remains false until all release gates below pass; empty pages, route proxies back to the old app and successful health probes are not functional migration.

## Review Focus

1. Two workspaces can have identical legacy row IDs: keys/authorization/import reports must retain tenant identity everywhere.
2. Import can stop after one database commits: staged import generations must remain inaccessible until validated activation, without pretending a cross-database transaction exists.
3. Retries and restarts must not duplicate receipts, deductions, payments, notifications or outbound email; uncertain sends require reconciliation.
4. Revoked sessions and reassigned bidders must immediately lose inbox/calendar/account access, including existing SSE connections.
5. Windows keyring credentials and copied absolute paths must not silently fall back to the original installation or expose secrets in migration reports.

## Scope inventory

The static census found 154 literal route declarations, 63 literal persisted table definitions and six mount/router registrations requiring runtime review, alongside 151 SQLite-specific references. These counts are a coverage baseline, not a complete runtime API inventory. The work includes the existing `web/gateway.py`, `web/app.py`, `web/sourcing_routes.py`, `control_store.py`, `db.py`, payment/sourcing/calendar/pipeline modules and backup/auth/provider modules. This is a business implementation and data migration, not a launcher/configuration change.

### Task 1: Freeze browser contracts and legacy schema ownership

**Files:** Create `docs/architecture/MIGRATION_PARITY.md`, `tests/services/fixtures/legacy_installation.py`, `tests/services/test_contract_inventory.py`.
**Interfaces:** Fixture `create_legacy_installation(root: Path) -> BackupLayout`; parity manifest records every route, auth role, owning service, mutation/idempotency policy and feature acceptance scenario.

- [ ] Inventory actual registered routes and all persisted tables, including lazy-created sourcing/payment/pipeline tables. Assign authoritative ownership and identify projection fields explicitly.
- [ ] Create representative owner + two-admin fixtures with colliding numeric IDs, disabled users/accounts, bidders, assignments, Done/Undo mail, classifications, sourcing, deductions, recorded payments and calendar/pipeline history.
- [ ] Add tests that fail when any existing browser route/table lacks an ownership/parity disposition. No route may be marked migrated by forwarding to the legacy deployment.
- [ ] Review/commit the contract and fixture baseline before feature ports depend on it.

### Task 2: Domain schemas and repository contracts

**Files:** Create versioned migrations under `mailcheck/services/migrations/`; focused repositories under `mailcheck/services/{core,mail,intelligence}/`; integration tests under `tests/services/`.
**Interfaces:** Every repository operation takes an explicit workspace and import-generation context. Legacy numeric IDs remain stable within that context. Domain event envelopes contain event ID, workspace, dataset/import generation, aggregate/source ID and revision.

- [ ] Test PostgreSQL constraints, tenant collisions, deletion/tombstones, timezone/decimal handling and legacy ID/sequence preservation before implementing repositories.
- [ ] Implement explicit PostgreSQL schemas for the ownership manifest. Core projections carry source/revision watermarks; they are not alternative authoritative Mail tables.
- [ ] Give persistent runtimes only their domain's credentials; test DDL/cross-domain denial and transaction rollback.
- [ ] Commit schema/repository contracts; do not implement a generic remote-SQL service or silently translate arbitrary SQLite SQL.

### Task 3: Validated legacy ZIP import and activation

**Files:** Create `mailcheck/services/migration/{archive,inventory,importer,validation,activation}.py`, migration management CLI and `tests/services/test_import_*`.
**Interfaces:** `plan_import(archive: Path) -> ImportPlan`; `stage_import(plan, targets) -> ImportReport`; `validate_import(import_id) -> ValidationReport`; `activate_import(import_id, expected_active_id)`.

- [ ] Reuse and extend the existing safe archive validation without weakening legacy restore's exact-version policy. The new importer declares supported source schemas/releases explicitly and refuses unknown versions.
- [ ] Stage read-only source extraction and independent domain writes under an immutable import ID; preserve source checksums and never modify the archive/source databases.
- [ ] Validate per-workspace table counts, ID maps, assignments, classified/checked totals, deduction rules, payment values and cross-domain references. Report every unsupported or skipped field as a blocking issue.
- [ ] Keep staged generations unavailable. Activate only a fully validated generation; fence domain work with the active generation/revision. Test interruption between each domain commit and activation.
- [ ] Preserve password hashes and user status; invalidate runtime sessions rather than importing stale session tokens. Mark excluded credentials as reconnect-required.
- [ ] Test repeat invocation, conflicting imports, malformed/oversized archives and rollback to a retained generation; commit importer and reports.

### Task 4: Core identity and authorization

**Files:** Create `mailcheck/services/core/{app,identity,sessions,authorization,admin_routes}.py`; tests for existing auth/admin/bidder API contracts.
**Interfaces:** Browser cookies terminate only at Core. Internal assertions are short-lived, audience-bound and include authorized workspace, account scope and active dataset generation; receivers validate signature/audience/expiry.

- [ ] Preserve existing owner/admin/bidder login, mandatory password change, logout/revocation, workspace switching, admin enable/remove and bidder account restrictions.
- [ ] Test colliding IDs, forged browser internal headers, disabled/deleted identities, concurrent password resets and scoped internal calls before porting routes.
- [ ] Implement shared PostgreSQL sessions/rate limits for both Core web processes; do not rely on per-process identity caches for revocation.
- [ ] Commit after old/new contract fixtures pass against real PostgreSQL and independent Core processes.

### Task 5: Core business APIs and projections

**Files:** `mailcheck/services/core/{sourcing,payments,calendar,pipeline,dashboard,settings,projections,notifications}/`; browser-contract integration tests.
**Interfaces:** Preserve route/response shape from Task 1. Projection consumers apply authoritative Mail facts idempotently in the same transaction as processed-event receipts and client journal entries.

- [ ] Port bidder management/assignments, sourcing/import/export/filter/copy/checked-row operations and search.
- [ ] Port deduction rules, daily totals, completed-weekday eligibility, weekly payment overrides and immutable recorded payment behavior with exact numeric validation.
- [ ] Port calendar/manual corrections, pipeline workflows, invitation/job-link matches, settings and dashboard/header totals.
- [ ] Add fail-before-code tests for every parity scenario, projection revision conflict, duplicate event and payment-history preservation; commit each independently testable feature group.

### Task 6: Mail APIs, credentials and collection

**Files:** `mailcheck/services/mail/{app,authorization,credentials,accounts,inbox,replies,collector,scheduler,provider_watches}.py`; reuse provider adapters through explicit credential/input interfaces.
**Interfaces:** Core calls scoped internal Mail APIs; Mail independently checks assertions. Provider operations use domain-owned durable jobs/outboxes and per-account leases.

- [ ] Implement encrypted Mail-owned credential storage with a separate Windows ACL-protected key file, reconnect flows and explicit imported-account status. Do not assume service accounts can access the interactive user's Windows keyring; explicitly migrate or reconnect credentials.
- [ ] Preserve inbox filters, message/body access, Done/Undo/mark-all-done, account management and manual replies. Replay-safe reply submission has a send ledger and uncertain-send handling.
- [ ] Move provider collection/checkpoints/retention into Mail; preserve classification/receipt semantics and source retention leases for inference jobs.
- [ ] Implement bounded live collection, owner/other workspace checking intervals, provider hint validation and reconnect/backoff. Test provider failures and concurrent same-account checks.
- [ ] Publish durable versioned Mail facts; no collector/model/provider call runs in a Core browser request. Commit after provider-fake integration and real broker tests pass.

### Task 7: Intelligence execution and accepted facts

**Files:** `mailcheck/services/intelligence/{worker,snapshots,classification,calendar,matching}.py` and Mail/Core result acceptance handlers.
**Interfaces:** Fetch immutable scoped snapshots, persist versioned jobs/results before acknowledgement, retain current model/prompt semantics and emit result events. Mail accepts/rejects classification results against current revisions/manual state.

- [ ] Extract existing classification behavior and cache versioning without reintroducing application-count changes.
- [ ] Serialize inference across instances with a PostgreSQL lease; separate live work/backfill and bound snapshots/concurrency.
- [ ] Preserve calendar analysis and invitation-to-sourcing/bidder suggestions through authorized Core candidate APIs.
- [ ] Test model outage, redelivery, stale source/result revisions, manual overrides, deleted inputs and bounded retry/review states; commit accepted-fact flow.

### Task 8: Live browser updates and full native Windows entrypoint

**Files:** Core SSE endpoints/notification dispatcher, frontend API/event adapters as necessary; `deployment/native-windows/{Caddyfile,runtime.example.json,README.md}`; `mailcheck/services/native_runtime.py`; `tools/microservices-native.ps1`.
**Interfaces:** Bootstrap snapshot barrier and durable journal replay use commit-ordered cursors. Authorization changes terminate scoped streams; streams do not hold database connections.

- [ ] Connect real React pages to the migrated API contracts. Preserve saved page filters and a single coherent startup/loading screen.
- [ ] Implement authenticated SSE with bounded buffers, replay/resync, reconnect backoff and cross-process delivery; refresh relevant page queries on committed changes.
- [ ] Serve complete versioned static assets at the edge with old-chunk retention and atomic HTML activation; test deployment during open tabs.
- [ ] Implement native startup/shutdown/status with explicit loopback listeners, dependency probes, bounded process recovery, rotated logs and protected service-account configuration. Native startup must not call Docker/Compose/WSL; reject conflicting ports without killing unrelated processes.
- [ ] Make the native Windows edge URL serve the real application. Keep `business_ready=false` until complete parity/import validation; never expose internal service or database routes publicly.

### Task 9: Acceptance, recovery and production cutover

**Files:** End-to-end browser/load/recovery tests; `docs/architecture/MIGRATION_ACCEPTANCE.md`; explicit import/cutover/rollback management commands.

- [ ] Run all legacy backend/frontend regressions and all migrated parity scenarios using the imported multi-workspace fixture through the native Windows edge.
- [ ] Verify each page and mutation, session revocation, provider/code-email updates, exact data counts/payment totals and absence of runtime SQLite/source-path dependencies and Docker/WSL requirements in native service processes.
- [ ] Kill/restart each service and dependency during work; verify recovery, no duplicate durable effects and no blind resend. Rehearse failed import and rollback.
- [ ] Measure target-host peak model memory, 50-user latency/resource usage and unattended Windows cold boot. Report failures honestly and fix them before migration readiness.
- [ ] Produce a reviewable real-backup import validation report and rollback artifact. Ask for cutover approval only after the complete release is built and tested; then switch the optional tunnel only when authorized.
- [ ] Bump/release once per completed functional delivery; document exact source compatibility and remaining operational limitations. Do not call the foundation a usable replacement before these gates pass.
