# Shared workers with RabbitMQ

Shared mode runs a fixed number of processes for all admins. Each request/job
binds a validated workspace context; separate existing SQLite databases and OS
keyring namespaces remain in place. Adding an admin does not add a worker process.

This mode is **opt-in**. Installing this release does not switch, stop or move
running jobs. The default `OFFERPATH_WORKER_MODE=legacy` retains the current runtime.

## Requirements

- Python 3.11+, existing OfferPath database schema version 50, and the `shared` extra:
  `python -m pip install -e '.[shared]'`.
- RabbitMQ 4.1+ with quorum queues and at-least-once dead lettering. Use persistent
  broker storage, a dedicated vhost/user, and private networking; use `amqps://`
  when the broker is remote. Do not expose the broker publicly.
- All application processes and SQLite files on the **same host**. The broker may
  be remote. Network filesystem SQLite and multiple gateway coordinators are not
  supported. The shared model limit and account coordination use crash-released
  operating-system file locks, including on Windows.

## Cut over without interrupting admin jobs

1. Leave the current deployment running while installing/testing in a separate
   checkout/environment. Do not run test consumers against its RabbitMQ vhost.
2. Arrange a maintenance window, pause automatic scheduling through the existing
   UI and ask admins to finish their active manual checks, sends and sign-ins.
   Wait until all current workspace jobs complete. Record the original settings
   so the owner can restore the intended schedules after startup.
3. Stop the existing gateway normally after draining. Do not kill active workers.
   Ensure its child workers have exited before starting shared mode. Never run
   Redis consumers and RabbitMQ consumers on the same workspace concurrently.
4. Configure the following variables in the **new server's environment**:

   ```sh
   export OFFERPATH_WORKER_MODE=shared
   export AMQP_URL='amqp://app:REPLACE_WITH_PASSWORD@127.0.0.1:5672/offerpath'
   export OFFERPATH_API_WORKERS=2
   export OFFERPATH_COLLECTION_WORKERS=2
   # Existing HTTPS root, only if Microsoft push subscriptions are wanted:
   export OFFERPATH_PUBLIC_URL=https://your-existing-domain.example
   python -m mailcheck web --no-open
   ```

   Retain existing public host, secure cookie and tunnel options. These examples
   do not change domain or account settings. Keep real broker credentials in the
   service's secure environment configuration, not Git or logs.
5. Verify owner/admin/bidder access, System monitoring, collection, classification
   and browser refresh using a test account before restoring normal scheduling.

The defaults are two API processes, two collection processes and one model/manual
job process, plus the gateway. One collection process also owns a bounded shared
reconciliation coordinator. There is no per-admin collector thread group.

## Data and event paths

```mermaid
flowchart LR
  B[Browser] --> G[Gateway authentication]
  G --> A[Fixed shared API pool]
  A --> D[(Selected workspace SQLite)]
  H[Microsoft webhook] --> Q[RabbitMQ jobs exchange]
  S[Shared reconciliation scheduler] --> Q
  G -->|Manual check + private dispatch reference| Q
  Q --> C[Shared collection consumers]
  Q --> M[Shared model/manual consumer]
  C --> D
  M --> L[One shared model lock]
  L --> O[External model]
  D --> T[Transactional outbox publisher]
  T --> E[RabbitMQ changes exchange]
  E --> V[Gateway exclusive event queue]
  V -->|SSE refresh hint| B
  B -->|Authenticated refetch| G
```

Mail and calendar collection run independently of model classification. Work
messages contain workspace/account identities and fixed job metadata, never mail
bodies, prompts or credentials. Manual request bodies and short-lived authorization
provenance are held in private local runtime files; the broker receives only an
opaque dispatch identity. Manual checks remain usable without realtime opt-in.

## Delivery, recovery and limits

- Persistent jobs, mandatory routing and publisher confirms protect enqueueing.
  Workers acknowledge after database commit. Delivery is at least once; existing
  upserts/checkpoints and manual-decision protection handle redelivery.
- Account collection/classification file locks and commit guards prevent overlap
  and reject writes after workspace/account revocation. Model access uses one
  same-host lock so a draining job can finish without gateway HTTP admission.
- A workspace has separate budgets of 16 outstanding collection hints and 16
  model/schedule hints, so slow classification cannot prevent mail collection.
  Notifications
  coalesce by workspace/account/kind; changes received during a scan request one
  follow-up. Capacity returns a retryable webhook error rather than accepting
  undurable work. Other workspaces retain their own independent allowance.
- Retry tiers are 5, 30, 120 and 600 seconds; there are five application attempts.
  Repeated consumer crashes also have a broker delivery limit. Dead letters remain
  in separate queues. A copied dead-letter notice releases only its matching
  runtime marker, allowing fresh reconciliation without replaying the dead letter.
- SQLite outbox rows remain until publication is confirmed. SSE contains only
  refresh hints. Browser reconnect and gateway broker reconnect trigger a full
  refresh; **Redis cursor replay is not part of this mode**.
- Additional state is under `control_root/shared-runtime`: file locks, bounded
  operational hints, catch-up checkpoints and temporary dispatch provenance. Do
  not delete this directory while jobs are active. No new application DB tables,
  columns or schema version are introduced. Existing older database schemas are
  refused in shared mode rather than migrated automatically. A missing subscription
  registry is initialized as a new file with the existing registry schema; an
  existing registry is not migrated.
- Shared processes request graceful shutdown and finish their in-flight operation;
  the supervisor does not force-kill ready processes. A slow provider/model can
  consequently delay shutdown. Use the drained cutover procedure above.

Monitoring separates global queues/shared processes from per-workspace sync and
outbox evidence. Telemetry is bounded and best effort, not an audit trail. Broker
health does not establish provider or model health.

## Rollback

Pause new work, wait for in-flight operations and stop shared mode gracefully.
Unset `OFFERPATH_WORKER_MODE` (or set it to `legacy`) and start the prior runtime
normally with the original service options. Do not reset databases or credentials.
Pending RabbitMQ hints can remain in the dedicated vhost; they are not a replacement
for application data. Restore the desired existing schedules explicitly. Do not
start legacy mode while shared children are still draining.

## Verification

Use a dedicated disposable RabbitMQ vhost/service:

```sh
OFFERPATH_TEST_AMQP_URL='amqp://test:TEST_PASSWORD@127.0.0.1:5672/test' python -m pytest -q
npm --prefix frontend test -- --maxWorkers=2
npm --prefix frontend run build
```

These tests use temporary databases and fake mail/model providers. They verify
context isolation, schema preservation, real broker delivery/redelivery, confirmed
outbox publication and SSE fanout. They do not prove live mailbox, model, TLS,
tunnel or production broker connectivity.
