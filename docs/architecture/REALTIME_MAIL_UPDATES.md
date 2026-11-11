# Live mailbox collection and browser updates

Status: proposed extension to the single-host microservice design. Architecture only; not implemented in the current v2.27.17 application.

Target: one Windows 11/i5-12400/16 GB server, 10–50 concurrent users, existing local AI model, optional Cloudflare Tunnel. This extends [the main architecture](SINGLE_HOST_MICROSERVICES.md).

## Required behavior

An enabled connected mailbox is watched independently of browser activity. When provider changes are detected, collect and durably store new mail promptly, then update authorized open browsers without a page reload or manual refresh. AI classification runs afterward and produces a second update when its results are ready.

Keep provider collection, browser delivery and human notifications distinct:

- Collection retrieves authoritative mail using the account's provider credentials.
- Live data events tell browsers that permitted data changed.
- User notifications are selected alerts with their own read/unread and popup policy. Every mail-list invalidation must not create a desktop notification.

The existing Mail service and the Core live-delivery module implement this. No new service, Redis instance or browser-to-provider connection is required.

```mermaid
sequenceDiagram
  participant Provider as Outlook / IMAP mailbox
  participant Watch as Mail watcher / scheduler
  participant Mail as Mail database + outbox
  participant Queue as RabbitMQ
  participant Core as Core event consumer + live journal
  participant UI as Browser
  participant AI as Intelligence worker
  Provider-->>Watch: Change hint, or due incremental poll
  Watch->>Provider: Fetch authoritative changes
  Watch->>Mail: Commit messages, source revisions, cursor and outbox
  Mail->>Queue: Publish mail-change event; confirm delivery
  Queue->>Core: Consume event, deduplicate, commit live update
  Core-->>UI: Authorized SSE invalidation
  UI->>Core: Refetch affected inbox data through existing API
  Core-->>UI: Latest permitted mail; pending analysis where applicable
  Queue->>AI: Background classification job
  AI->>Queue: Versioned classification result
  Queue->>Mail: Apply result without overwriting newer/manual state
  Mail->>Queue: Publish committed classified-mail revision
  Queue->>Core: Update reporting projections and eligible alerts
  Core-->>UI: Inbox/report update and optional notification
```

Arrows from databases to the broker represent service-owned outbox dispatchers, not database connections to RabbitMQ. Browser access remains through Core; the Mail API stays private.

## Provider detection

### Outlook / Microsoft Graph

Use folder-scoped delta synchronization as the durable collection mechanism. Preserve the current Outlook coverage of Inbox and Junk Email; do not silently narrow it to Inbox alone. Persist provider nextLink/deltaLink state and message upserts transactionally. Complete pagination before treating a synchronization round as complete, and resume a partial round after a crash.

Where a stable public HTTPS callback is available, Graph change-notification subscriptions accelerate detection. A webhook is a hint to run delta collection, not proof that an email exists or permission to trust its body. Subscription renewal and lifecycle handling belong to Mail and continue when browsers are closed.

Subscriptions are optional because the system must also operate without public ingress or Cloudflare. With no callback, expired subscriptions or missed delivery, the same incremental polling path continues. Use the provider-returned subscription expiration and the actual account's supported permissions; verify personal Outlook and organizational account support during the connector spike, without silently requesting broader scopes.

The edge may expose exactly the dedicated Microsoft callback route to Mail's webhook handler. This is a narrow exception to private Mail routing; it must never expose the general Mail API. Echo validated subscription challenges as plain text within Microsoft's deadline. Validate subscription identity and clientState, bound payload sizes, reject unknown accounts, redact callback secrets from logs and acknowledge promptly after durable enqueue. Fetch message content with the stored OAuth credentials rather than from untrusted notification fields.

If a delta cursor expires, perform a bounded resynchronization with deduplication. Do not delete historical classifications, recorded payment facts or messages merely because a cursor must be rebuilt. Stable provider IDs are essential; any move to Graph immutable IDs requires a tested legacy-ID mapping so old messages do not become duplicate receipts or alerts.

### Folder coverage and moves

Persist an explicit watched-folder policy per account. Outlook initially covers Inbox and Junk Email, matching the current collector; IMAP initially covers its configured folder. Additional folders are opt-in after an authorized account owner reviews coverage. Discover folder changes periodically and surface coverage status, but do not automatically ingest Sent, Drafts or every newly created folder. If provider rules move arriving mail into an unwatched folder, it is outside live coverage until that folder is enabled; make this visible rather than promising mailbox-wide collection.

A move between watched folders is an update to the same logical mail item, subject to the tested provider-ID mapping, not a second receipt or new-mail popup. Removed/deleted/moved-out items produce a view/availability change and retained tombstones as appropriate; they do not implicitly retract a historical received-application fact or alter a recorded payment. Reconcile folder deletion/rename and UID epochs without discarding preserved history.

### Gmail and other IMAP accounts

Use one IMAP IDLE watch per account/folder where supported. IDLE signals trigger an incremental UID fetch; they are not an additional mailbox or a connection per browser. Refresh/reconnect IDLE sessions with bounded backoff and reconcile after every reconnect.

Start with the existing IMAP connector in a dedicated, bounded watcher thread pool, separate from both the Mail API and the fetch executor. IDLE waits must not occupy fetch slots or the web server's shared thread pool. Use finite waits and explicit stop/reconnect handling; validate the 16-watch memory/shutdown budget on the actual host before increasing it. Start with at most 16 simultaneous IDLE watches on this host, subject to provider quotas and memory measurement; other accounts use incremental polling with fair scheduling. Active accounts can take priority without starving other connected accounts. Review this limit against the actual number of mailboxes, not just the number of users.

Track UIDVALIDITY and UID checkpoints. A UID epoch change must trigger reconciliation with the existing logical/provider identity mapping, not indiscriminate creation of new messages. Preserve current deduplication/counting semantics; an RFC Message-ID alone is not a universal unique identifier for every mailbox.

Do not introduce Google Cloud Pub/Sub as a required dependency. Gmail can continue using the existing IMAP-based account connection.

### Polling and scheduling policy

Initial fallback cadence: about 15 seconds for accounts with active authorized inbox viewers and 60 seconds for other live-enabled accounts, with jitter and per-provider/account backoff. Reconciliation also runs periodically while push/IDLE appears healthy, to recover missed hints. Respect provider Retry-After, connection limits and OAuth failures; do not promise a fixed interval while throttled.

Core derives active-view interest from authenticated subscriptions and sends expiring account-interest hints to Mail. A browser cannot activate arbitrary accounts by choosing an account ID. An account is collected once on the server regardless of whether one user or fifty users are watching it. Closing every browser does not stop the baseline live collection schedule. When an account becomes actively viewed, schedule one coalesced catch-up if its stored state is stale; many viewers opening the same account do not each launch another fetch.

Live incremental collection and scheduled historical/full checks are separate controls. The Accounts/Checking UI must clearly distinguish live updates, scheduled reconciliation and manual checks. Disabled/removed accounts and suspended workspaces stop watches, leases and queued collection work; the system must not continue polling under a misleading "off" label. Migration must explicitly map the old auto-check preference to the new controls and document when live collection is enabled.

## Collection and event correctness

- Keep one fenced collection lease per account. Coalesce repeated IDLE/webhook/poll hints into one active or pending collection job.
- A hint arriving while collection is active marks the account dirty. On completion, compare the dirty generation and schedule another pass when needed. Simply dropping a hint because a job already exists can miss mail indefinitely.
- Prioritize fresh changes throughout outbox dispatch, broker lanes and Core consumption, not just during provider fetch. Use bounded, weighted-fair live/backfill lanes within each consuming service group. Coalesce browser invalidations during imports without dropping durable business facts; background work still receives capacity. Out-of-order source positions caused by prioritization follow the gap/commit rules below.
- Reserve one of the four initial fetch slots for live incremental work. Historical imports use bounded pages and yield; they cannot monopolize all slots. Inference has its own queue and concurrency limit.
- In one Mail transaction, upsert authoritative message changes, append source revisions and outbox events, and advance the safe provider checkpoint. Never advance a cursor beyond data/events that were not committed.
- Use provider identity plus account/workspace and revision for idempotency, retaining explicit legacy-ID mappings. Retries, repeated hints, webhook redelivery, folder moves and resyncs must not inflate message totals, receipts or notifications.
- Emit versioned `mail.message.created`, `mail.message.updated`, `mail.message.removed` and `mail.sync.state.changed` facts, with correlation IDs and minimal references. Distinguish a genuine new message from an update or backfill.
- Store normalized and original message data before sending classification work. Preserve the snapshot/retention protections in the main architecture so queued work cannot lose its inputs.
- Core consumes committed Mail changes into a short-lived, durable account-scoped client-event journal. Store one data-change event per account/entity revision, not one row per browser. It contains references and versions, not an extra copy of every email body. Consume/commit before acknowledging broker delivery.
- The event bus is at least once and consumers can run concurrently. Compare entity revisions; handle gaps through authoritative snapshots/catch-up rather than assuming all queues deliver globally ordered events.
- Mail must first accept the Intelligence result against the current input revision and manual overrides, commit its authoritative classified-message revision, and emit `mail.message.classified`. Core derives receipt/report totals and classification-based alerts only from that accepted Mail fact, after its own projection commits. A direct Intelligence completion is not authoritative for inbox counts or alerts; it may be stale or rejected. Core-owned matching/pipeline suggestions remain separately validated against their source revisions. Changes to receipt/report totals are published only after these commits. An incoming raw message is not automatically an application receipt or an extra payment count.

## Revision and commit-order rules

Use distinct revisions rather than treating every change as a new AI input:

| Revision | Meaning |
| --- | --- |
| Content/input revision | Provider content relevant to analysis changed; this identifies immutable AI input |
| Classification revision | Mail accepted a classification/correction for the current input |
| View revision | Visible message state changed, including Done/Undo; it must not by itself rerun AI |
| Account change position | Commit-ordered prefix of Mail changes used for account snapshot/reconciliation |
| Workspace client-event position | Commit-ordered prefix of Core live events used for SSE replay |

Allocate Mail account positions by locking/updating the account head in the same short transaction as its changes/outbox. Allocate Core client-event positions through a workspace journal-head row locked in the event transaction, with journal records and head committed together. Do not use PostgreSQL identity/sequence allocation or created_at as a committed high-watermark: transaction A can allocate 10, transaction B commit 11, and A commit 10 later; a client that has advanced to 11 would otherwise miss 10. Never hold these ordering locks across provider/model calls, broker waits or client delivery.

Deduplicate/apply entity facts by their own source identity and revision. A newer account position for message B does not supersede an older unseen event for message A. Core tracks contiguous applied Mail positions and durable gaps for reconciliation; it must not declare a financial projection caught up merely because it saw the largest sequence number. Every relevant position must be delivered, recorded as an explicit no-op/coverage marker, or covered by an accepted replacement snapshot; routing/filtering must not create permanent unexplained gaps. A financial replacement snapshot includes the retained fact ledger, not only surviving raw emails. Required Mail facts remain available independently of raw message bodies until those consumers catch up or accept a versioned replacement snapshot. Late conflicting results respect the current accepted classification/manual state.

SSE barriers come from committed journal heads. Snapshots use consistent database reads and report the relevant committed account/view positions. Reject an invalid or future cursor; resync when the cursor predates retained journal history. Ordinary notification read state and financial records are never pruned just because the client replay window expires.

## Shared SSE connection and browser behavior

Extend the planned Core SSE connection to carry a small set of typed client events such as `mail.changed`, `mail.sync.changed`, `notification.created` and `report.changed`. Do not open separate streams per mailbox, page or email. Keep the main architecture's per-user/per-process stream limits, heartbeat, backpressure and revocation rules.

Core filters each event using the current workspace, role and permitted account scope. Revalidate idle sessions/stream claims at the main design's 15-second heartbeat and before delivery; if authorization cannot be checked, stop sending private events and close before the 45-second claim lease expires. An idle connection cannot outlive revoked/expired credentials merely because no new mail arrived. Replay cursors are opaque and bound to the authenticated identity/workspace. A cursor never grants access. Changes to workspace or account assignment require scope revalidation and, where needed, a fresh snapshot.

A short client-event retention window, initially 24 hours, supports reconnect replay. On expiry or an invalid cursor, signal resync and refetch current authorized state. This journal is not the source of truth for mail or notification unread state. PostgreSQL LISTEN/NOTIFY only wakes each API process; scan durable records after listener reconnect to cover missed wake-ups. Use the two shared listener connections and short pooled replay/authorization queries; never reserve a database connection, transaction or query session for each live stream. Release those sessions before awaiting network writes or the next event.

### Snapshot/stream handshake

Establish an authorized stream and receive a durable replay barrier/cursor before the initial inbox snapshot. Buffer subsequent events while fetching a consistent Mail snapshot through Core. Snapshot responses include their per-account committed revisions. Apply the snapshot, then replay/deduplicate buffered events, invalidating only when an event is newer than the corresponding snapshot revision. A Mail event delayed in the outbox/Core consumer must still arrive later and trigger catch-up; a snapshot already containing that change makes the later event harmless.

The stream must register for durable events after the barrier without an unobserved gap. Use the same barrier/snapshot procedure after cursor expiry, workspace changes or a permission-scope change; do not fetch once and then open a live-only stream that can miss arrivals between those operations. If SSE cannot be established, read-only polling of current authorized snapshots remains the correctness fallback. Initially cap the browser handshake buffer at 256 events or 256 KiB, and each server stream queue at 100 events or 128 KiB. If either cap is exceeded, close/resync from a fresh snapshot instead of accumulating data without a limit. Network backpressure must never retain a database transaction or ordering lock.

The React client will:

1. Establish its stream after sign-in, with account/view interest scoped by the server.
2. Batch/coalesce invalidations over roughly 250–500 ms and refresh only affected query keys: mail list, selected message, account sync status, and relevant committed counters/reports.
3. Preserve route, filters, search, selected message, scroll anchor, row selection and unsent reply drafts. Do not remount the whole workspace or reload the page when mail arrives.
4. Show a small new-mail indication when the reader is away from the top, rather than stealing focus or jumping to a different message. All-mail and actionable Queue views keep their existing category/filter semantics.
5. Keep current data visible during background reads. Distinguish a reconnecting live stream from a failed account connection or pending AI result.
6. Resume from the last authorized cursor with exponential backoff/jitter capped at a reasonable reconnect interval. Pause unnecessary reconnect attempts while offline. A resumed/visible tab catches up once, rather than generating a burst of per-account provider checks.
7. If SSE is unavailable, use a bounded-rate read-only API polling fallback while the relevant page is visible, initially every 10 seconds with jitter. This fallback reads stored server state; it does not initiate a provider fetch for every browser. Return to SSE after recovery without leaving duplicate poll loops running.
8. Cancel streams, pending reads, local event cursors and account interest on sign-out/workspace change. Prevent a late response/event from an old identity from entering the new user's cache. Permission loss clears or locks no-longer-authorized message data and drafts; preservation during ordinary new-mail updates must not override revocation.

Native browser desktop notifications remain permission-based and best effort. An SSE data update does not itself mark a notification read or claim a popup was shown. Closed-browser push is not included in this design.

## Classification, verification codes and privacy

Admins can see newly stored permitted mail in All mail with an explicit pending-analysis state. The actionable Queue changes only when its rules justify inclusion; do not silently label all unclassified messages as actionable.

Bidder Inbox retains its restricted information-request/job-application-code scope. Unclassified mail must not be exposed merely because the bidder is assigned to the account. The current safe application-verification fast path may make an eligible message visible before AI completes; ambiguous mail waits for an authorized classification. Password-reset, unrelated sign-in and other sensitive codes are not automatically included by a broad numeric-code detector.

A later classification produces a versioned update. It must not clear Done state, overwrite manual corrections or reset a reply draft. Dashboard/badge/payment updates follow committed business facts, rather than counting raw live events. Notification previews contain no actual verification code or email body.

## Status and operator visibility

Show separate status for:

- Browser delivery: connected, reconnecting or polling fallback.
- Each mailbox: watching, polling, next scheduled attempt, backoff, paused or reconnect required.
- Classification: pending/backlogged/completed independently of collection.

Use server-owned last-successful-check and next-attempt timestamps, with time-offset handling in the browser. Show "Live watching" for an IDLE/subscription path instead of inventing a countdown to the next email. During throttling, show the actual next retry time. A connected SSE socket does not prove the provider connection is healthy.

Trace provider-hint receipt, fetch start, Mail commit, outbox publish, Core journal commit and browser invalidation. Measure queue lag and each stage's duration. Keep message bodies, code values, tokens and full delta URLs out of operational logs. Expose failures through the owner status view without making the UI depend on the model being healthy.

## Latency targets and validation

Measure on the actual Windows server under the 50-user workload, with the existing model busy. Inventory the representative number of distinct accounts/folders, message arrival volume, provider round-trip times and throttling; fifty browsers sharing one mailbox is not a fifty-mailbox capacity test. Validate the four-fetch-slot and sixteen-watch limits against that inventory before accepting the cadence goals. Queue lag must trigger visible degradation/backoff rather than unbounded work or a false freshness claim:

- Target committed Mail data to authorized browser update p95 below three seconds under normal load. Measure provider-hint-to-fetch/commit latency separately; do not hide it inside the delivery metric.
- Fallback collection uses its configured interval; an initial active-mailbox target is roughly 30 seconds end to end under normal provider availability. Provider delivery, webhook latency, quotas, throttling and outages prevent an unconditional instant-delivery guarantee.
- AI completion latency is reported separately. Code-mail visibility and raw authorized inbox updates must not wait for inference.

Required tests include reversed transaction commit order, delayed lower-position facts for another message, overlapping workers competing for global slots, source-fact survival beyond raw-mail retention, idle-session revocation and database-pool usage with fifty idle SSE clients; arrivals at each stage of the initial stream/snapshot handshake and permission-change handshake; folder coverage/moves and historical deduplication; rejected/stale Intelligence results never changing counts or alerts; Outlook personal/organizational subscription capability, subscription expiry, missed webhooks, delta expiry and interrupted pagination; IMAP disconnect/reconnect and UIDVALIDITY reset; repeated hints during an active fetch; provider throttling and credential revocation; historical import plus live arrivals; broker/consumer restart; classification arriving out of order; and replay duplicates without counter/payment inflation.

Browser tests must cover fifty clients sharing accounts, single account collection rather than per-client checks, SSE through the actual edge/tunnel, offline/online recovery, lost PostgreSQL wake-ups, replay expiry, slow consumers, filters/scroll/draft preservation, workspace/assignment revocation, restricted bidder visibility, permission-denied desktop notifications and fallback polling without duplicate loops.

## Migration sequence

Implement provider cursor/watch adapters and their account leases first; then committed Mail outbox events and authorized Core client journaling; then the shared browser stream and targeted cache updates. Add subscription acceleration only after reliable delta/fallback collection works. Retire the legacy browser-driven three-second inbox polling and tab-driven collection only after the new path passes side-by-side validation. Preserve rollback checkpoints and avoid running two authoritative collectors/senders during cutover.
