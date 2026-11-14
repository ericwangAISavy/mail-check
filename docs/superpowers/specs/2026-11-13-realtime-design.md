# Real-time ingestion and page updates

Approved direction: Redis Streams, independent Python collection/classification consumers,
workspace SQLite transactional outbox, and authenticated gateway SSE. Preserve existing
manual/scheduled workflows and previous uncommitted reliability fixes. No external
provider subscription is created until the user explicitly enables an account.

Provider callbacks carry hints only. Verify Graph clientState against a persisted hashed
secret; resolve workspace/account only from the registered subscription. Acknowledge only
after durable enqueue. Renew expiring subscriptions; periodic per-account reconciliation
recovers missed notifications. IMAP initially uses bounded polling (30 seconds), since
IDLE support varies; calendars require Outlook. Reuse proven collectors with timestamp
overlap for mail and existing calendar snapshot reconciliation rather than inventing an
unverified provider delta implementation. Mail collection persists before classification.

Redis persistence is required (AOF); consumers acknowledge success, reclaim abandoned
jobs, retry with bounded backoff and dead-letter persistent failures. Scope streams by
workspace. Synchronize account work with renewable distributed leases. Do not expose
Redis publicly or store message contents/tokens in streams. Outbox records are inserted
by SQLite triggers in the same transaction as data changes, including manual changes.

SSE carries change topics only. Each browser independently replays events, with a refresh
on connect/reconnect; no consumer group distributes browser events among users. Revalidate
sessions/workspace selection while connected. Separate finite connection admission from
normal requests/control calls; close slow senders and release capacity on disconnect.

Environment: OFFERPATH_REDIS_URL (private Redis), OFFERPATH_PUBLIC_URL (HTTPS public app
root for Graph callbacks). Optional feature dependencies must not break normal startup
when disabled. Offer account-level opt-in/status in Accounts and document native Redis/Windows,
Cloudflare webhook bypass, Redis persistence, and rollback. No production configuration,
credentials, user data or tunnel settings are edited during development.

Acceptance: regression suites pass; real Redis verifies enqueue/reclaim/retry/dead-letter,
outbox rollback/replay and independent readers; synthetic provider callbacks test validation
and tenant routing; SSE auth/revocation/admission/disconnect tests; UI invalidation cleanup
tests; production build; actual Microsoft/tunnel checks remain deployment prerequisites.
