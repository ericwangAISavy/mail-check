# Reliability review — November 9, 2026

Scope: gateway/worker lifecycle, background jobs, first-password flow, database
transactions, sourcing reads/CSV, provider parsing, routing recovery and bidder
Inbox delivery. Production report: Cloudflare Bad gateway during first password
changes and navigation. No production traceback or server access was available;
findings below were reproduced locally and do not identify every cause of a 502.

## Reproduced and corrected

- Healthy workers treated gateway HTTP503 overload responses as parent death and
  exited after three heartbeats. They now remain alive on 503; unreachable or
  replaced parents still terminate stale workers. Gateway capacity limits remain.
- Background completion callbacks and failed thread creation could retain the
  global check lock. Both paths now release it; failed rescheduling is reported.
- Outlook successful responses with missing/invalid message listings could advance
  a checkpoint incorrectly or abort all mail collection. Malformed data now fails
  that account with SourceError while healthy accounts continue.
- Interviews error Retry started a calendar sync instead of reloading the failed
  list. It now retries the read.
- Job sourcing index reads attempted INSERT even when all workbooks existed. WAL
  reads now succeed during another writer's transaction without unnecessary writes.
- Dense full-sheet responses could allocate hundreds of MB and repeat every 15s.
  Responses over 100,000 display cells or 8 MiB stored text/style are rejected before
  allocation with 413. Nothing is silently truncated or deleted. Sparse CSV export
  remains available, with a 32 MiB output preparation budget. Oversized imports roll
  back atomically. Split large sheets or export one work date when needed.
- Lazy page-load errors were intercepted by the router before the outer recovery
  boundary. A route-level boundary now provides OfferPath's Reload recovery screen.

## Password-change investigation

The exact forced-password HTTP flow passed: login -> forced password update ->
session refresh -> first workspace bootstrap. A real-process regression creating
legacy and fresh admin workers also passed. A password-specific crash was not
reproduced. The first workspace request after changing a password starts/contacts
its worker, so failures at that point need gateway output and the corresponding
`offerpath-control/logs/<workspace_id>.log`, with secrets removed before sharing.

## Remaining operational limits

A502 can still originate from a stopped tunnel/server, OS/process termination,
resource exhaustion, or an unavailable workspace. These fixes do not establish
production uptime or eliminate every defect. Live Inbox checks target faster
arrival, not guaranteed instant delivery; existing access/classification rules
and admin automatic-check controls are unchanged.

## Verification

- Backend: 791 tests and 92 subtests passed (one dependency deprecation warning).
- Frontend: 418 tests passed across 47 files; production build passed.
- Production CSP browser checks passed for normal startup, blocked browser storage,
  signed-in blocked storage, stale entry recovery and bounded missing-entry recovery.
- Release consistency and whitespace checks passed.

## Follow-up review — version 2.24.1

Additional timing-sensitive failures reproduced after the first review:

- Concurrent startup waiters could disagree on readiness. A delayed waiter could
  time out and stop the shared worker after another request had confirmed it was
  healthy. Waiters now share readiness under the pool lock and do not return a
  worker removed by suspension. Failed process launches close their log handles.
- Cancelling shared-model acquisition during worker validation permanently lost
  semaphore capacity before any expiry lease existed. Failed or cancelled
  validation now returns capacity immediately.
- Bidder membership database reads ran directly on the worker HTTP event loop.
  A slow database open/read therefore delayed unrelated HTTP traffic. Those
  checks and standalone authentication now run in the request thread pool;
  authorization conditions remain the same.
- Frontend response protection compared only workspace names. A delayed response
  could cross a logout/login round trip or a user change within one workspace;
  an old 401 could sign out the newer session. Responses now also validate the
  session handoff revision, and cache invalidation includes the full identity.
- Pending sign-in/password form results could restore local session state after
  sign-out. Reset now invalidates those pending form completions. The initial
  password form disables sign-out during saving to avoid conflicting session
  cookie updates; expired sessions can begin a new login without an older form
  completion clearing its busy state.

These are local reproductions; no production crash trace was available to
attribute the reported Bad gateway events to a specific race.

Follow-up verification: the complete backend run passed 798 tests and 92
subtests. Expanded model-lease interruption coverage subsequently passed all
three cancellation/error/revocation cases. Production compilation and Chromium
checks passed, including startup recovery and initial password save/navigation.
The complete frontend suite passed 424 tests across 47 files. Release metadata
consistency checks passed.
