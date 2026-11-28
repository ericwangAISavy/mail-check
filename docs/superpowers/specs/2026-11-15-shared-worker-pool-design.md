# Shared workspace execution with RabbitMQ

## Intent and selected approach

The user subsequently required no existing database changes or interruption of
current admin jobs. Shared mode is opt-in at a drained restart; legacy remains
the default and schema version remains 50. Coordination uses runtime files and
OS locks instead of the initially proposed SQLite lease tables. Shared model
admission also uses one same-host OS lock so draining jobs can finish after the
gateway stops accepting HTTP. See docs/SHARED_WORKERS.md for the final contract.

Replace one long-lived worker process per admin with bounded shared API and job
worker pools. The user selected shared workers after discussing RabbitMQ routing.
Retain separate workspace databases, credential namespaces, authorization and the
existing business behavior. Base: feature/multi-admin-workspaces at 9bfde4d.

Alternatives considered: keeping per-admin workers with a RabbitMQ adapter would
retain process growth and does not meet the request. A shared broker-driven pool
with explicit workspace context meets it. Forking a process per job provides
isolation but adds startup cost and is not the selected steady-state architecture.

## Components

- Gateway: authenticates users, resolves workspace from the server-side session,
  revalidates dispatch, and routes requests to a fixed-size shared API pool. Never
  trusts a browser-supplied workspace ID to select data. Keeps the single shared
  model admission limit. Initial deployment supports one gateway coordinator.
- Shared API processes: reusable FastAPI instances serve different workspaces.
  They start no per-workspace collector threads or worker subprocesses. A bounded
  pool size controls concurrency independently of admin count.
- Shared job processes: consume global mail, calendar and classification queues.
  Each delivery identifies a workspace and account; consumers resolve both against
  the control database before touching workspace data. Separate consumer capacity
  prevents model jobs from blocking collection.
- Scheduler/publisher: bounded coordinator loops enumerate enabled workspaces,
  reconcile account jobs, renew subscriptions, and publish committed outbox hints.
  They do not allocate one persistent runtime/thread group per admin.
- RabbitMQ: durable direct jobs exchange, durable quorum work queues, delayed
  retry tiers and dead-letter queues. Persistent messages, mandatory routing and
  publisher confirms are required. Quorum delivery limits bound poison redelivery.
- Gateway change subscriber: one exclusive queue per gateway instance binds to
  a topic changes exchange, fans out to authorized local SSE connections, and
  forces resync after a broker disconnect. No per-browser broker queue.
- SQLite: existing control and workspace databases remain on the same machine.
  Distributed worker hosts sharing SQLite over a network filesystem are outside
  scope. This is a process architecture migration, not a database migration.

## Explicit workspace execution context

Introduce an immutable WorkspaceContext resolved from trusted control records:
workspace ID, validated root, database/config paths, shared settings path and
credential namespace. Include legacy owner paths explicitly. Invalid identities,
missing roots and mismatched markers fail closed; never fall back to legacy data.

Bind context with ContextVar at request/job entry and reset in finally. Pass it
explicitly across background tasks and thread/executor boundaries; eliminate
process environment mutation as a workspace selector. Audit config, db, keyring,
MSAL caches, file paths, auth helpers and module-level caches. Move mutable API
state into workspace-keyed bounded state or durable storage. Request-scoped state
must not escape into another workspace through app.state or module globals.

## Job and transaction contract

Envelope: schema version, stable job_id, workspace_id, account_id, fixed job kind,
reason and attempt count. Never include credentials, message bodies or prompts.
Malformed/unsupported messages go to dead-letter handling without database writes.
Consumers validate active workspace/account again before committing. Automatic jobs
also require automatic-update opt-in. Manual jobs preserve current behavior for
accounts without that opt-in: they require an enabled account and durable,
server-issued authorization provenance, with initiating session/permission
revocation checked before execution and commit. A message's reason label alone
must never grant manual authorization or bypass automatic-update opt-in.

Use manual acknowledgments after successful database commit. Redelivery is expected:
retain idempotent upserts, mailbox catch-up checkpoints and manual-edit protection.
RabbitMQ delivery ownership does not replace application coordination. Use
workspace/account/lane OS locks and guarded commit fencing. These locks are
crash-released rather than expiring a live writer. Mail/calendar share collection
lane; classification has its own lane. No lease schema or database migration is added.
Fair scheduling caps outstanding work per workspace/account/kind and consumer
prefetch is bounded; one busy admin must not create unbounded queued duplicates.

For transient failure, publish persistent retry with the same logical job_id and
incremented attempt; acknowledge original only after confirmation and routing.
Publish failure leaves original unacknowledged. Retry tiers use fixed queue TTLs
and dead-letter back to jobs, avoiding arbitrary per-message head-of-line delays.
Dead-letter transfer must be configured with quorum at-least-once safety or handled
by a confirmed application republisher. Permanent failures and exhausted budgets
go to the dead-letter queue. Do not automatically replay dead letters.

SQLite triggers and transactional outbox remain. Coalesce topics as today. Mark
only captured outbox identities published after confirmed, routed delivery. Lost
confirmations may duplicate hints; refresh operations tolerate duplicates. Broker
outages preserve outbox data and pause queued processing without corrupting data.

Manual check buttons enqueue durable jobs and return job status; they must no
longer launch workspace-local background threads. Explicit outgoing sends retain
existing user authorization and duplicate-send safeguards, and are never blindly
retried as collection jobs.

## Browser events and monitoring

Keep SSE and ordinary authenticated API reads. Events are invalidation hints; full
resync occurs on connect/reconnect and gateway broker recovery. Remove the promise
of Redis cursor replay: ordinary RabbitMQ queues are not browser replay logs.
Use bounded local subscriber buffers and disconnect/resync slow clients.

Replace worker-per-workspace cards with shared pool/process health plus workspace
backlogs, in-flight jobs, lease ownership and latest sync evidence. Add component
and flow diagrams showing broker routing, collection, classification, outbox and
SSE paths. Distinguish unavailable broker metrics from zero backlog. Telemetry is
bounded and best effort; it never delays business operations or claims a complete
audit history. No message bodies, credentials or raw provider errors in telemetry.

## Compatibility and cutover

Preserve databases, stored statuses, user settings, credentials and existing admins.
Do not run old Redis consumers and new RabbitMQ consumers concurrently. Stop old
consumers, let active work finish or recover via leases/checkpoints, enable the new
runtime, then reconcile. Existing Redis hints need not be copied: they are not
authoritative; database state and fresh provider reconciliation regenerate work.
Unpublished SQLite outbox hints must be retained. Keep a documented explicit legacy
mode for rollback; never silently fall back when RabbitMQ is misconfigured.

Add documented broker configuration and a separate optional Python dependency.
New deployments use the shared architecture when configured. Publish the migration
as a major release because deployment and background job semantics change. No
production account connections, sends, deployment or push during implementation.

## Acceptance and validation

1. More admins than pool slots: OS process count stays bounded by pool settings.
2. Concurrent requests and jobs for two workspaces with identical account IDs:
   databases, credentials, cache entries and events never cross boundaries.
3. Worker death after commit/before ACK: safe redelivery, no duplicate business data.
4. Lease loss, account deletion or suspension fences subsequent commits. Automatic
   jobs also stop on opt-out; manual checks remain usable with automatic updates
   disabled, and revoked initiating authorization prevents manual job execution.
5. Real RabbitMQ tests cover confirms, unroutable publication, retries, consumer
   crash/redelivery, poison messages, broker restart and outbox recovery.
6. SSE fan-out reaches both clients in one workspace, isolates other workspaces,
   and resyncs after reconnect without claiming historical replay.
7. Existing smoke, backend, authorization, frontend and release checks execute;
   production frontend bundles rebuild. Update deployment/runbook instructions.
8. Scheduler and API state remain bounded; collection proceeds when the model is
   slow, and broker outages produce explicit degraded status.

Builder choices: Python AMQP client, internal module boundaries, queue names,
pool defaults, retry intervals and migration implementation sequence. Choose
maintained libraries and verify semantics against a real local RabbitMQ instance.
