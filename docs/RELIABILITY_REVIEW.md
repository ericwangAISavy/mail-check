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

## Concurrent-user availability — version 2.24.4

A real Uvicorn reproduction kept 63 completed HTTP connections idle with no
active requests; the previous 64-connection guard rejected a new connection.
The server now separates limits: up to 64 active ordinary requests, 8 short
loopback worker control requests, and a finite Uvicorn transport/task ceiling
of 256. Health checks and idempotent model releases have reserved active capacity;
model acquisition remains in the ordinary lane. Worker authentication and the
HTTP security boundary still validate every admitted control request. Gateway
worker authentication uses a separate bounded four-thread executor, and trivial
health handlers are asynchronous, so browser DB/thread backlogs cannot starve
those control requests. A regression saturates the ordinary executor and checks
that an authenticated heartbeat still completes. Saturating
all 256 transport connections can still produce a controlled overload response.

The real-server regression retains idle connections, fills the ordinary request
budget, checks overload responses and reserved health/release requests, then
confirms recovery after active requests finish. Model releases now retry the same
lease up to three times after transient failures, with 5-second request timeouts
and short backoff. Authentication failures are not retried. Exhaustion logs a
warning and leaves the existing expiry fallback; it never replaces a model
operation's original result/error.

Payment-page reads previously tried to acquire a write transaction for matching.
A separate writer reproduced a locked-database page failure. Automatic matching
now attempts the lock without waiting, coalesces simultaneous in-process matching,
and displays saved counts when matching is busy. Normal checks and explicit
week refresh remain available; unrelated SQL errors still surface. Normal
uncontended page matching continues to update newly registered links.

Clicking the current sidebar title or home button also preserves query/hash state,
including filters updated directly through browser history. Different-page and
modified-click navigation retain their normal behavior.

The supplied Cloudflare screenshot records a 502 host error at
2026-11-09 21:12:26 UTC (15:12:26 Chicago). The load and database bugs above were
reproduced locally; without that host's gateway/tunnel logs they cannot be claimed
as the confirmed cause of that specific 502.

Final 2.24.4 verification: 816 backend tests and 92 subtests passed; 444 frontend
tests across 47 files passed; release consistency and production build passed.
Chromium checks passed under production security headers for normal/blocked-storage
startup, active-page/home filter preservation, stale-entry recovery and bounded
missing-entry recovery. One existing Starlette/httpx dependency deprecation
warning remains. These checks do not replace deployment or host/tunnel log review.

## Loading and search follow-up — version 2.24.6

Reproduced problems and corrections:

- Every proxied admin GET acquired the control database's writer slot. Read
  dispatch now validates against a consistent read transaction; mutations retain
  the previous write transaction. No identity cache, WAL migration or permission
  bypass was introduced. Completed logout, reset, suspension and workspace switch
  still reject old sessions. With a writer held for 600 ms, four read validations
  finished in about 4 ms each instead of waiting 635–933 ms.
- Concurrent page requests independently waited for the same worker startup in
  executor threads. They now share one in-flight readiness task per serving loop
  and workspace. Cancelling one caller does not cancel other callers' startup.
  Completed tasks are removed, so readiness/errors are not cached across requests.
- Gateway reads could continue for up to the worker transport's 660-second timeout
  after the browser's 30-second deadline. GET/HEAD proxy processing now has a
  25-second overall deadline and returns 504 with Retry-After when exceeded.
  Mutations retain existing completion semantics and are never retried here.
  A synchronous worker database operation already dispatched may still finish;
  timing out its gateway read does not undo or terminate its database transaction.
- Search built a dense styled editor grid for every searched sheet. Search now
  streams sparse values, retaining ownership/date/row metadata and size guards.
  It avoids empty-query sheet scans and caps retained results at 500. On a synthetic
  900-row/100-column fixture with 900 populated cells and identical 900 matches,
  the root verification run measured 0.7201 s / 31,786,066 peak allocated bytes for
  dense snapshot search versus 0.0235 s / 353,526 bytes for sparse search, using
  time.perf_counter and tracemalloc. These are local microbenchmark results, not
  guaranteed production latency or whole-process memory measurements.
- A failed bootstrap refresh replaced a cached workspace with configuration
  recovery and discarded component state. Cached workspaces now remain mounted
  during temporary refresh errors with a single in-flight manual retry. Initial
  transport failures get connection recovery; explicit saved-configuration errors
  retain Settings recovery. This does not keep data across an identity change.

The host's remaining loading/502 reports still need correlation with its deployed
version, gateway/tunnel logs and available CPU/RAM. These fixes address reproduced
application bottlenecks; they do not establish the cause of every production 502.

Final 2.24.6 verification: 832 backend tests and 92 subtests passed; 447 frontend
tests across 47 files passed; production build and release consistency passed.
Chromium under production security headers verified initial 502 recovery and
background 502 recovery while retaining the exact search input DOM node and its
unsaved value, plus startup recovery and active-page filter preservation. The
existing Starlette/httpx dependency deprecation and Vite chunk-size warning remain.

## Broader functional review — version 2.24.7

This pass covered account setup, backup status/archive handling, manual email
replies, page/form state, and payment/deduction integrity beyond loading.

- Changing from a known IMAP provider to an unsupported provider retained the
  previous server. The email-change handler now clears the old host/port/note
  immediately, including incomplete email input, and a no-preset result clears
  automatic details. Server settings entered manually after the change remain
  protected from delayed lookup results. Browser verification exercised this
  flow in the compiled production UI without creating an account or sending mail.
- A ZIP with a correctly named archive but a null/list/bool manifest crashed
  BackupManager.status with TypeError, hiding every archive. Listing now skips
  that malformed manifest while preserving its file. Restore validation and
  retention behavior are unchanged. Backup unit/API fixtures verified the fix.
- Malformed Outlook reply metadata caused unhandled attribute/type errors before
  any send and left the operation in preparing state. Message/list identifiers,
  recipient shapes/addresses and subject values used for replies are now checked.
  A malformed response returns a controlled provider error and records the unsent
  request as failed, allowing explicit retry of the same operation after healthy
  metadata returns. Regression cases prove no send occurs on those failures and
  that retry succeeds; accepted/uncertain delivery remains protected from resend.
  This does not retroactively declare older stuck/uncertain deliveries unsent.

The financial audit found no material reproducible defect in rounding, amount/date
validation, daily-deduction eligibility, saved overrides/paid snapshots, revision
checks or serialized writes. Focused payment suites passed 61 backend and 5
payout-report frontend tests; no payment calculation or history changes were made.

Final 2.24.7 verification: 836 backend tests and 98 subtests passed; 451 frontend
tests across 47 files passed; production build, release consistency and Chromium
account-setup checks passed. Existing dependency deprecation/chunk-size warnings
remain. Tests use disposable archives, databases and mocked provider responses;
no real mailbox was connected, no email sent, and no production records changed.
