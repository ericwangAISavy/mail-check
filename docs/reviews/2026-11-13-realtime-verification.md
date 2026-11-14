# Real-time updates verification — November 13, 2026

Release: 2.28.0. Existing uncommitted reliability fixes were preserved.

## Delivered

- Optional redis-py extra; persisted Redis 7 Streams with workspace namespaces, independent
  collection/classification lanes, lease and pending-job heartbeats, consumer-fenced ACKs,
  durable retries/dead letters and notification burst coalescing.
- Opt-in per-account workers, first-attempt outage window anchoring, incremental mail
  overlap, existing calendar reconciliation, classification after persisted receipt, and
  transactional SQL-trigger outbox publication. Permanent model failures need manual retry.
- Microsoft callback validation, subscription creation/renewal/cleanup, throttle recovery,
  callback-domain migration and private credential-cache synchronization across threads/processes.
- SSE replay/resync, session/workspace checks, bidder-safe hints, finite separate admission
  budgets and network-send deadlines; React query invalidation and account opt-in/status.
- Windows/Cloudflare setup and persisted, loopback native Redis configuration in docs/REALTIME.md.

## Evidence

Regression tests failed before implementation/fixes. Real Redis was run locally with
AOF and appendfsync always. Focused tests exercise pending reclaim/ownership, retries,
dead letters, transaction rollback, active lease loss during real calendar savepoint
release, paused accounts, model errors, missed notifications, frozen initial windows,
subscription renewal/domain changes, forged callbacks and independent event readers.

A live HTTP smoke used the actual gateway, spawned workspace process and real Redis
with temporary local data. A committed account database change produced an outbox row,
Redis publication and browser SSE `changed` event. Public callback challenge validation
passed; ordinary authenticated requests remained responsive during streaming; revoking
the session produced `session-ended` and closed the stream. No provider account was enabled.

Frontend suite: 532 passed across 56 files. TypeScript and production build passed.
Standalone pipeline smoke: 332 passed. Release consistency passed.
Final backend suite after review fixes: 1,019 passed plus 98 subtests, with one existing
Starlette/httpx deprecation warning. Real-Redis tests were enabled for that run.

Independent reviews identified and verified fixes for job reclaim/ownership, stream
admission/backpressure, revocation during delivery, calendar transaction fencing,
permanent classification loops, initial outage windows, callback-domain replacement,
and concurrent keyring cache corruption. Scoped re-reviews approved these corrections.

## Deployment limits

Microsoft delivery/consent, real mailbox/model performance, Windows credential APIs and
the actual Cloudflare tunnel need validation on the deployment host. IMAP uses 30-second
polling in this release; native Gmail push/IMAP IDLE are not implemented. Outlook recovery
checks run every 120 seconds; calendar history uses the existing one-year window.

No user accounts were opted in, external subscriptions created, credentials changed,
tunnel settings modified, environment draft republished, or Git changes pushed.

Following the user's Docker-free requirement, the Compose example was removed and replaced
by deployment/redis.conf. The guide describes native Linux Redis, Windows with WSL2,
a compatible native Windows service, and an authenticated managed endpoint. The Python
application and event-processing implementation do not depend on Docker.

Docker-free validation: built Redis 7.4.12 natively from the official Redis 7.4 branch
(commit b1f7796), loaded deployment/redis.conf, and ran 60 queue/runtime/provider/gateway
integration tests successfully. Verified loopback binding, noeviction, appendonly and
appendfsync always; persisted data survived a server restart. This Linux validation
does not establish compatibility with an unselected native Windows Redis alternative.
