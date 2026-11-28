# OfferPath broad reliability review — November 13, 2026

Release 2.28.1 on feature/multi-admin-workspaces; database schema 50. Existing uncommitted
work was preserved. All development checks used temporary/synthetic data and native Redis.
No Docker, production subscriptions, real outgoing mail, user credentials or tunnel settings
were used or changed.

## Review coverage

| Area | Source and behavior reviewed | Outcome |
| --- | --- | --- |
| Gateway/security | Host/origin policy, encoded dispatch, worker auth, admin/bidder boundaries, admission, session invalidation | Fixed owner-only route bypass through double-encoded paths; preserved literal account-label characters |
| Worker lifecycle | Startup, heartbeat, recovery, retirement, supervision, lock ownership | Fixed replacement starting before retiring worker released its workspace lock |
| Replies/outgoing | Graph/SMTP preparation, receipts, ambiguous delivery, retention races, draft identity | Fixed transport uncertainty, stale-message dispatch and wrong-message Done updates; receipts replay after message removal |
| Settings/accounts/CLI | Atomic writes, concurrent field updates, rules/autocheck, credential cleanup | Serialized complete web/CLI read-modify-save; credential cleanup failure no longer deletes cached account data |
| Mail/LLM | Read-only sources, Inbox/Junk completeness, incremental cutoffs, retention, checkpoints, retries/schema | Discarded impossible calendar deadlines; model deferral no longer masks hard mailbox failures |
| Calendar/availability | Native recurrence/identity, rescheduling/cancellation, queued analysis, manual overrides, calendar windows | Preserved Rescheduled on unchanged sync; unknown event end within query padding blocks unsafe availability |
| Realtime | Streams ownership/recovery, subscription scope, outbox transactions, replay, UI invalidation | Added business invalidations, bounded per-topic outbox replacement, Junk notifications and subscription resource upgrades |
| Sourcing/payments | CAS/idempotency, structural/import mutations, filters, assignments, cents/deductions/settlements | Existing protections verified; live business/filter/viewer updates now refresh |
| Interview pipeline | Review decisions, linking, followups, contact/event chronology, merge/split and draft saves | Corrected offset-aware ordering; stale review actions cannot create duplicate opportunities; pending forms preserve drafts |
| Analytics | Shared filter scope, pagination, timezone bounds, synthetic 10k-message performance | Unrepresentable extreme dates now return validation errors instead of overflow |
| Backups/restore | Archive validation, maintenance exclusion, rollback/recovery, credential/file handling, download paths | Domain tests passed; backup settings fields now lock during saves |
| UI/session/drafts | Request cancellation, workspace changes, uncertain writes, realtime subscriptions, forms | Protected reply operations and backup/interview/pipeline draft inputs during pending saves |
| Legacy Google integration | OAuth browser state, credential generations, disconnect/refresh races | Disconnect invalidates pending/in-flight authorization; module is not mounted in current native sourcing UI |

## Confirmed fixes and regression evidence

- Direct ASGI tests reproduced encoded owner API bypasses that higher-level clients
  double-decoded before dispatch. Quoting the authorized path at the worker transport
  boundary prevents a second decode and retains legitimate percent/question/hash labels.
- Event-controlled retirement tests reproduced the worker replacement lock collision.
- Reply tests replace/delete the original message while provider I/O is in flight and
  verify unrelated rows remain untouched. Expected message/account identities protect
  the current composer before sending. Saved receipts remain authoritative for replay.
- Actual ApiError status 0 tests protect ambiguous sends from new operations/body/mode
  changes. No real email was sent in these checks.
- Concurrent settings tests reproduced lost web changes; an independent CLI process
  test reproduced and verified cross-process preservation. Maintenance and update locks
  cover the entire load/modify/save cycle, not only file replacement.
- Migration tests exercise schema49→50 with an old duplicate outbox backlog and missing
  business triggers. Hundreds of writes coalesce to one new identity per topic; rollback
  and concurrent publication/ACK tests verify that committed newer hints are retained.
- Outlook subscription upgrade tests replace legacy Inbox-only resources while preserving
  callback/secret validation. Actual provider acceptance remains a deployment check.
- Calendar fixtures reproduce repeated-snapshot status loss. Deadline tests include leap
  dates and impossible dates; pipeline tests compare actual instants across offsets.
- Review-decision tests retain same-operation replay while rejecting stale decisions or
  already-linked evidence under the existing write transaction.
- Realtime UI tests exercise open read-only sheets and active business/filter queries,
  including infinite-stale-time views. Pending-save tests cover success/failure draft safety.

## Final verification

- Full Python suite with native Redis enabled: **1,070 passed, 102 subtests passed**;
  one existing Starlette/httpx deprecation warning.
- Full frontend suite: **540 passed across 56 files**.
- Standalone pipeline smoke: **332 passed**.
- Synthetic 10,000-message/90-day dashboard: five requests passed the one-second
  benchmark bound; slowest request was **0.1861 seconds** during concurrent validation.
- Independent final source review and scoped review of the last pipeline form fix:
  no actionable remaining finding in the changes reviewed.
- Release consistency and whitespace checks passed; the final production build passed.
  Bundled UI is newer than production sources and all referenced JS/CSS assets exist.

No failing checks remain from this review. The existing frontend build chunk-size and
test-environment deprecation/window.open notices are not application readiness failures.

## Limits

This is a broad risk-based source review with regression and integration testing, not proof
that every possible bug is absent or a live penetration test. The Windows Python runtime,
native Windows credential APIs, actual Cloudflare connector, Microsoft delivery/consent,
real IMAP/SMTP providers and model performance still require deployment-host validation.
The real OS-keyring integration script remains opt-in. The supported IMAP realtime path
is polling, and calendar history follows the existing collector window.

Optional identity fields preserve API compatibility for older reply clients; current UI
requests send them. Third-party callers should send expected_message_id and
expected_account_label to receive pre-send stale-message protection. No integration,
merge, push, publication or user-account opt-in occurred during this review.
