# OfferPath Multi-admin Workspaces Implementation Plan

Status: approved and implemented on `feature/multi-admin-workspaces`; final code and browser verification complete. Not deployed or pushed. Native Windows multi-worker and production-load rollout checks remain manual.

**Goal:** One owner provisions additional admins, each managing an isolated set of email accounts, bidders, jobs, interviews and payments. Settings are shared and accessible only to the owner.

**Architecture:** Add a control plane for owner/admin identities and workspace routing. Keep each workspace's existing business database schema and run its application in a separate worker process. Register the existing installation as the owner's original workspace without relocating or rewriting its database.

**Tech stack:** Existing FastAPI, React and SQLite; a new control-plane SQLite database; local worker processes supervised by a gateway. Keep the existing Python CLI/package name and launch command compatible.

## Settings revision (2026-10-28)

The user selected owner-only Settings access. Added admins inherit the owner’s configuration and can change their own password from the header. Settings APIs route to the original workspace even while the owner is viewing another workspace. Existing per-workspace settings files remain preserved for rollback.

## Requirements and interpretation

- Exactly one owner, initially the existing admin. Additional admins cannot create admins or become owner.
- Each added admin receives a new empty workspace, not a copy of the owner's data.
- Existing owner email accounts, bidders, passwords, sourcing rows, payments and settings remain in their current locations.
- No tenant-ID columns, ownership backfills, splitting, or destructive migrations of the existing business database for this feature.
- Preserve current per-workspace workflows and calculations. Authentication, startup, path resolution and request routing necessarily gain an isolation layer; claiming zero application-code changes would be misleading.
- Normal future business-schema migrations remain possible and are distinct from this feature's control-plane migration. Rehearse deployment against a backup before allowing production startup.
- The owner controls admin lifecycle and workspace health. Viewing another workspace requires an explicit owner switch, a persistent workspace banner and an audit entry; there is no combined email inbox by default.
- Disable an admin/workspace reversibly; preserve all data. Hard deletion, merging accounts/workspaces and cross-workspace bidder sharing are excluded initially.

## Alternatives considered

1. Shared database with tenant columns: convenient for central analytics but changes every ownership boundary and requires a risky data migration. Not recommended under the existing-data constraint.
2. Separate databases in one process: avoids business-table changes, but requires all global job/scheduler/configuration state to become workspace-specific and reliably propagate into background threads. Possible, but easy to introduce data leakage.
3. Separate databases and worker processes behind one gateway: strongest fit for the current global-state design; more process supervision and memory overhead. Recommended for the first multi-admin release.

## Data and process layout

- New control database: owners/admins, workspace IDs, status, authentication/session metadata, workspace path registrations and audit events. Never store email bodies or mailbox credentials here.
- Existing workspace: register its current database/configuration/auth paths; preserve its existing credential keys.
- New workspace directory: its own database, TOML configuration, exports and temporary files. Owner/admin authentication and session metadata live in the separate control database.
- New workspace secrets: use a workspace-ID namespace in the OS keyring and Outlook token storage. Identical account labels, bidder IDs and email addresses in different workspaces must not collide. Existing workspace keys remain readable unchanged.
- One worker owns each workspace's job state, scan progress, OAuth/device flows, scheduler and local locks. No process-global path switching between concurrent workspaces.
- Gateway is the only network-facing application. Workers bind to loopback, require a workspace-specific internal authentication secret and reject untrusted forwarded identity headers. Merely binding to localhost is not an authorization boundary.
- Worker startup receives explicit immutable workspace paths. Missing or invalid workspace configuration fails closed; never fall back to the owner's paths.

## User experience

- Only Owner and Admin can sign in. Admins use a unique username and password.
- Bidders are managed business records only, retaining names, assignments, rates, wallets, sourcing history and payments. They have no credentials or login access.
- Owner sees an **Admin management** page: create admin, set/reset password, enable/disable, open workspace, inspect health.
- New admins must change the initial password at first sign-in; no public registration.
- Each workspace shows its name prominently. Additional admins see only their workspace and cannot enumerate other workspaces or the owner panel.
- Remove the existing bidder login option, public bidder-name listing, password creation/reset/self-change controls and bidder credential-management routes. Reject bidder login attempts and invalidate previously issued bidder sessions on rollout. Retain historical bidder data and existing stored authentication files without destructive cleanup; dormant legacy credentials cannot authorize access.
- Sessions identify user, workspace, role and a revocation version. Changing password or disabling access invalidates relevant sessions. No admin role inferred from submitted IDs.
- React query caches, drafts, browser preferences containing workspace data and in-flight responses are isolated/reset on workspace changes. A stale response cannot appear in the next workspace.
- Existing application features, including filters, AI drafts, calendar availability and payment reports, operate entirely inside the selected workspace.

## Scalability policy

- Each workspace keeps SQLite and its own writer lock, avoiding contention between separate workspaces.
- Do not promise unlimited workers: establish configurable worker and job-concurrency limits and measure memory before choosing deployment defaults.
- Keep workers with enabled auto-check schedules running; idle unscheduled workers may stop and restart on demand. Closing a browser must not silently disable an enabled workspace schedule.
- Supervise/restart crashed workers with bounded retries and visible health errors. Prevent duplicate workers/schedulers for the same workspace.
- The current LLM service may be shared, but enforce a bounded global concurrency queue with fair scheduling between workspaces. No mixed prompts or shared conversation memory.
- Back up and restore per workspace; include the control database separately. Later growth can move workers to other hosts without changing the business data model. PostgreSQL migration is not part of this release.

## Delivery sequence and acceptance checks

### 1. Existing-workspace compatibility

Files: `mailcheck/config.py`, `mailcheck/web/auth.py`, `mailcheck/secrets.py`, Outlook token-store code; new `mailcheck/workspaces.py`; tests `tests/test_workspaces.py`.

- [x] Define immutable Workspace descriptors and resolve legacy vs new workspace paths.
- [x] Add namespaced secret/token lookup for new workspaces while retaining the existing workspace's lookup.
- [x] Test existing database/config/auth file hashes are unchanged by registration alone.
- [x] Test two workspaces with identical mailbox labels and bidder IDs resolve different files and secrets.
- [x] Test unknown workspace IDs, invalid paths and worker startup errors never fall back to legacy data.

### 2. Control-plane identities and owner administration

Files: new `mailcheck/control_store.py`, `mailcheck/web/admin_routes.py`; authentication integration in `mailcheck/web/auth.py`; tests `tests/test_workspace_auth.py`.

- [x] Create the separate control schema and bootstrap exactly one owner through verified existing admin credentials; no default owner password.
- [x] Implement admin creation, required password change, reset and reversible disable with audit records.
- [x] Implement workspace-bound sessions and revocation; add CSRF/origin protection for control mutations and login throttling.
- [x] Test added admins cannot create admins, switch to an unauthorized workspace, access the owner panel or forge owner privileges.
- [x] Test reset/disable revokes active admin sessions and workspace suspension rejects new requests.
- [x] Reject the legacy bidder role during login and session validation. Test old bidder cookies no longer work, and bidder credential/listing routes are removed or explicitly denied. Do not delete bidder business data.
- [x] Test partial provisioning rolls back or remains visibly incomplete without starting a worker.

### 3. Gateway and worker isolation

Files: new `mailcheck/web/gateway.py`, `mailcheck/workspace_workers.py`; startup integration `mailcheck/cli.py`, `mailcheck/web/server.py`; tests `tests/test_workspace_gateway.py`.

- [x] Route verified sessions to the correct worker; pass validated identity through authenticated internal requests.
- [x] Keep existing business routes and calculations inside workers. Preserve errors, cookies and response handling without exposing worker ports/secrets.
- [x] Isolate schedulers, OAuth flows, outgoing reply operation identities and background jobs. Owner disable must stop new jobs/sends without claiming an already-dispatched email was cancelled.
- [x] Add worker lifecycle supervision and bounded shared LLM scheduling.
- [x] Test simultaneous admins, identical row/event IDs, mailbox connection flows, reply generation, actual-send mocks, calendar aggregation and CSV/report downloads never cross workspaces.
- [x] Test forged headers, cross-workspace identifiers, session expiry, worker crash and server restart.
- [ ] Test the normal Windows launch command and selector-loop startup still work.

### 4. Owner/admin UI and removal of bidder login

Files: `frontend/src/components/auth.tsx`, `frontend/src/App.tsx`, `frontend/src/lib/api.ts`; new `frontend/src/pages/admin-management.tsx` and workspace UI tests.

- [x] Add owner management and admin sign-in flows and persistent workspace identity.
- [x] Remove bidder sign-in selectors and bidder-password UI in Accounts, sourcing settings and any other surface. Preserve bidder management and assignments for admins.
- [x] Reset/isolate caches, drafts and in-flight requests on identity/workspace changes.
- [x] Preserve the current workspace layout and features for added admins.
- [x] Test every role's visible navigation and direct URL access; API authorization remains authoritative.
- [x] Test switching workspaces while a draft/save/AI generation is in flight cannot display or send content in the wrong workspace.

### 5. Deployment and release gate

Files: deployment documentation; integration/load tests.

- [ ] Rehearse from a production-shaped backup; verify existing totals, payment history, checked states, calendar records and authentication before/after.
- [x] Run the full existing test suites and new isolation tests, plus simultaneous multi-workspace check/send simulations.
- [ ] Measure startup latency, memory per worker, SQLite behavior and shared-model fairness; document supported limits based on results.
- [x] Keep rollback instructions and backups. Rollback restores the previous entry point; it does not merge newly created workspace data into the owner's database.
- [x] Release only after owner/admin workspace isolation and rejection of all bidder authentication is proven through direct API tests, not just hidden UI controls.

## Implementation result

Approved by the owner, including removal of bidder login and a fully reversible
code boundary. The original workspace remains at its existing paths and business
schema version 34. New control/identity data is stored separately. See
`docs/MULTI_ADMIN.md` for sign-in, capacity and rollback instructions.

Verification: 371 backend tests (plus 76 subtests), 229 frontend tests, production
build, and real-browser owner/admin/CSV workflows passed. Real worker tests cover
concurrent startup, crash/restart, separate data, direct-access rejection, and a
specific-interface heartbeat surviving beyond its failure threshold. Native
Windows multi-worker validation and target-host capacity measurements are release
checks; the existing Windows selector-loop unit coverage remains green.
