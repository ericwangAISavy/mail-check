# OfferPath reliability review — November 12, 2026

Reviewed on `feature/multi-admin-workspaces`; fixes recorded in release 2.27.18.

## Scope

Reviewed gateway dispatch/authentication, worker startup and supervision, request admission,
timeouts, proxy trust, HTTP security and static serving; frontend request/error handling,
query lifecycle, polling and workspace/session boundaries; backend authentication,
Outlook connection lifecycle, scheduling, credential handling and model coordination.
Ran the repository-wide backend and frontend suites and standalone pipeline smoke runner.
This is a broad source and regression review, not proof that every possible bug is absent.

## Confirmed defects fixed

1. **Gateway serving-loop stall during session replacement.** Successful login offloaded
   password validation but performed SQLite logout writes and the final identity lookup
   on the serving loop. A competing control-database writer could stall unrelated traffic
   and worker heartbeats. Replacement now runs in a thread. A regression holds a real
   SQLite write transaction and verifies that an internal heartbeat remains responsive.
2. **Obsolete page reads continue after cancellation.** Query callbacks omitted their
   AbortSignal, leaving unnecessary requests running during navigation, filter changes,
   and reader closure. Query signals now reach the API transport across pages/dialogs;
   the manual header status/notification poll also aborts on cleanup. Writes retain their
   existing completion semantics.
3. **Canceled responses can change active session UI.** A response resolving during
   cancellation could still emit unauthorized/workspace-change events. Transport checks
   cancellation after fetch and body parsing before dispatching events or returning data.
   Regressions cover reader closure, polling cleanup, and late 401/409 responses.
4. **Stale Outlook sign-in flows damage working credentials.** An older canceled or
   superseded flow could overwrite/delete credentials belonging to a newer successful
   flow; failed/wrong-account reconnects could erase existing credentials. Web flows now
   defer cache persistence until current-flow/account validation under the flow lock.
   Cancellation and failure preserve existing credentials; direct callers keep immediate
   persistence. Database/persistence failures now leave the waiting state with an error.

## Validation

- Regression tests reproduced the defects before fixes.
- Frontend: 527 tests passed across 54 files; TypeScript and production build passed.
- Standalone pipeline smoke runner: 332 checks passed.
- Live local HTTP smoke with public Host and forwarded HTTPS headers: login 200,
  unauthenticated bootstrap 401, authenticated real-worker bootstrap 200, and 36/36
  concurrent bootstrap reads successful with concurrency set to 12.
- Release consistency and whitespace checks passed. Bundled UI regenerated.
- Final backend suite: 956 tests and 98 subtests passed, with one existing
  Starlette/httpx deprecation warning.

During validation, one run overlapped a production rebuild, temporarily removing the
index file under a static-page test. That run was stopped. Outdated Outlook fixtures and
frontend call expectations were corrected to match the new behavior; validation was
restarted with stable build output.

## Limits and deployment follow-up

The live smoke uses temporary local test data and a real worker on Linux. It does not
exercise the user's Windows Python 3.15 runtime, actual Cloudflare connector, Microsoft
OAuth service, production mailbox/model, or OS credential store. No user databases,
credentials, tunnel settings or environment drafts were changed by this review.

The reported public 502 still needs the same-time cloudflared error and configured
origin service URL. The pasted application log shows Ctrl+C shutdown and cannot identify
that failure's cause. See ON_PREM_SECURITY.md for origin-versus-tunnel diagnosis.

Worker monitoring currently visits enabled workspaces serially; a slow startup can delay
later monitoring. No additional user-visible failure was reproduced, so this review did
not introduce an unverified concurrency redesign. Existing dependency/build deprecation
and bundle-size warnings remain.
