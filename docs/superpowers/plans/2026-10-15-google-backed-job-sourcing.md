# Google-backed Job Sourcing Implementation Plan

> Superseded by the user’s native-sheet choice. See [native job sourcing design](../specs/2026-10-15-native-job-sourcing-design.md). This document records the previous Google-backed approach.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Edit the existing bidder Google spreadsheets privately inside mail-check and find source applications from interviews.
**Architecture:** One server-side Google OAuth connection; owner-scoped workbook/tab records and snapshots; signed named-bidder sessions; a virtualized spreadsheet editor with checked writes.
**Tech Stack:** FastAPI, SQLite, httpx, scrypt/HMAC sessions, React 19, React Query, a permissively licensed React data grid.
**Spec:** `docs/superpowers/specs/2026-10-15-google-backed-job-sourcing-design.md`

## Global Constraints

- Google is authoritative. Existing email-based payment counting stays unchanged.
- One Google account accesses all five files; bidders never receive Google credentials.
- Profile means an assigned email account. Company, Role, and Job link are indexed.
- Replace shared Guest login with Admin/Bidder; preserve admin credentials and reject guest sessions.
- Enforce ownership on all reads, writes, search, mapping, and operation-status endpoints.
- Signed sessions expire in 12 hours. Bidder passwords accept 8–256 characters.
- Refresh a clean worksheet every 15 seconds; debounce saves for 1.2 seconds; batch maximum is 10,000 cells.
- Never overwrite formulas through literal writes or blindly replay an uncertain append.
- Keep pending heading cleanup in the workspace; stage feature files selectively.

## Review Focus

1. A bidder changes a workbook/tab ID in a request: no other bidder data or metadata is returned (Tasks 1, 3).
2. Google inserts/sorts rows while a local edit is pending: reject the stale revision, preserve edits (Tasks 3, 4).
3. Google accepted a write but the response was lost: operation remains uncertain and is not replayed (Tasks 2, 3).
4. Password reset/disable during an active session: old session loses access immediately (Task 1).
5. A quoted multiline Google Sheets paste contains blanks/formulas: parse rectangles correctly and preserve formula cells (Tasks 3, 4).

## Task 1: Named identities and scoped access

**Files:** `mailcheck/web/auth.py`, `mailcheck/web/app.py`, `mailcheck/payments.py`, `mailcheck/db.py`; new `mailcheck/sourcing/store.py`; `tests/test_auth.py`, new `tests/test_bidder_auth.py`.
**Interfaces:** `AuthStore.identity(token)->dict|None`, `login(role,password,address,bidder_id=None)->(token,limited)`, `set_bidder_password(id,password)`, `change_bidder_password(id,current,password)`. Add `bidders.login_enabled`. Middleware sets `request.state.bidder_id`. `payments.report(..., bidder_id=None)` filters its response and data query scope.

- [ ] Write tests for named login, incorrect password, public enabled names only, own password change, reset/disable revocation, old guest rejection, and own-only payments.
- [ ] Run `pytest tests/test_bidder_auth.py -q`; expect missing named-login behavior to fail.
- [ ] Implement auth-file migration preserving admin, bidder hash/version records, session principal, login enablement, safe bootstrap, and role middleware. Register public name-list and admin/self password routes.
- [ ] Update legacy guest tests to assert rejection or named-bidder isolation, preserving their original host/cookie/expiry tests.
- [ ] Run auth, payment, and migration tests; commit this independently testable change.

## Task 2: Google OAuth and Sheets transport

**Files:** new `mailcheck/google_sheets.py`, `mailcheck/google_oauth.py`, `mailcheck/web/google_routes.py`; modify `mailcheck/config.py`; new `tests/test_google_sheets.py`, `tests/test_google_oauth.py`.
**Interfaces:** `GoogleConnection.status/setup/begin/complete/disconnect`; `SheetsClient.metadata(id)`, `snapshot(id,sheet_id)`, `write(id,changes)`, `append(id,range,rows)`. Use an injected httpx client for transport tests. Google errors expose a safe message and status, never credentials.

- [ ] Test state replay/expiry/cookie binding, PKCE, refresh, failed reconnect retaining the previous token, keyring failure, URL validation, protected-cell errors, formula metadata, and quota backoff using real transport serialization and fake HTTP responses.
- [ ] Run the new tests; expect missing modules/interfaces to fail.
- [ ] Implement private chunked token storage, public configuration fields, exact callback validation, single-use OAuth state, fixed Google endpoint requests, metadata validation, bounded read windows, RAW patch writes and append.
- [ ] Register admin connection routes and the state-validated public OAuth callback. Coalesce token refresh and bound retries.
- [ ] Run provider/config/credential tests; commit.

## Task 3: Workbook mappings, checked saves, indexing, search

**Files:** new `mailcheck/sourcing/service.py`, `mailcheck/sourcing/models.py`, `mailcheck/web/sourcing_routes.py`; extend `mailcheck/sourcing/store.py`, `mailcheck/db.py`; new `tests/test_sourcing.py`, `tests/test_sourcing_api.py`.
**Interfaces:** `SourcingService.workbooks(principal)`, `tabs(principal,workbook_id)`, `snapshot(principal,workbook_id,tab_id,refresh=False)`, `save(principal,workbook_id,tab_id,SaveBody)`, `search(principal,q,...)`. `SaveBody` contains operation UUID, base revision, changed literal cells or appended rows. Ownership is resolved from the verified principal and persisted mapping.

- [ ] Test real SQLite owner isolation, unique file assignment, valid profile mapping, header mapping, retained historical labels, stale snapshots, formula protection, 10,000-cell limit, append uncertainty, idempotent replay, and scoped search.
- [ ] Run new service/API tests; expect missing routes/behavior to fail.
- [ ] Create mapping/cache/operation/index tables through the schema migration. Implement generic 404 for inaccessible IDs, before-cache authorization, worksheet locks, revision comparison, checked Google writes, durable operation states and index rebuild.
- [ ] Cache snapshot freshness; refresh indexed tabs on explicit admin refresh and report incomplete/stale search data. Do not apply email-retention pruning to sourcing tables.
- [ ] Run sourcing/auth/payment tests; commit.

## Task 4: Named sign-in and spreadsheet workspace

**Files:** modify `frontend/src/components/auth.tsx`, `frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`, `frontend/src/App.tsx`; new `frontend/src/pages/sourcing.tsx`, `frontend/src/pages/sourcing.css`, `frontend/src/components/sourcing-grid.tsx`, `frontend/src/components/sourcing-settings.tsx`, `frontend/src/components/password-dialog.tsx`, `frontend/src/lib/sourcing.ts`; update dependency manifests.
**Interfaces:** `Principal={role:'admin'|'bidder',bidder_id?:number,name?:string}`; sourcing API wrappers mirror Task 3. Grid emits changed cells with original values, never Google tokens. Clipboard utilities parse/serialize TSV rectangles independently of the grid library.

- [ ] Verify grid license and React 19 compatibility before installation.
- [ ] Test Admin/Bidder login, name selection, own-workbook landing, password controls, private navigation, TSV multiline/blank handling, selection/keyboard behavior, dirty-refresh preservation, 1.2-second debounce, failed/conflicting save state, and sign-out cleanup before implementation.
- [ ] Run targeted frontend tests; expect missing workspace/behavior to fail.
- [ ] Implement the full-height grid workspace and profile tabs, admin connection/mapping/access controls, save/conflict/retry states, add rows, clear, undo/redo, internal scrolling, and owner-safe React Query keys.
- [ ] Integrate interview Find application and searchable row deep links, plus bidder-own payment visibility. Preserve pending heading cleanup.
- [ ] Run full frontend suite and production build; commit.

## Task 5: End-to-end verification and setup documentation

**Files:** new `docs/JOB_SOURCING.md`; update `README.md`, affected regression tests and bundled frontend.

- [ ] Document OAuth project setup, exact redirect URLs, Google consent, credential storage, five workbook mappings, profile/column mappings, password management, sync timing and external-edit race limitations.
- [ ] Run `pytest -q`, `python -m tests.test_smoke`, `npm test`, and `npm run build`; inspect every failure and resolve confirmed regressions.
- [ ] Browser-test admin + two distinct bidders using synthetic/mock Google workbooks: copy/paste, saves, conflict, own-only API access, search-to-row navigation, password reset, desktop/mobile layouts, and session expiry.
- [ ] Review the whole change against the spec; fix important findings with regression coverage. Report live Google verification separately when OAuth credentials and consent are not available.
- [ ] Commit remaining feature/docs/build changes. Do not push without user authorization for this feature.

## Execution result

Implementation is complete on the existing feature branch. The concrete persistence
and synchronization helpers live together in `mailcheck/sourcing.py`; Google routes
are grouped with sourcing routes. Dependent modules are committed together after
verification, with the preexisting heading cleanup in a separate commit. Google
client configuration is kept with its secret in the OS keyring. See
[verification, implementation decisions, and deferred minor polish](../verification/2026-10-15-job-sourcing.md)
for actual test counts, review fixes, browser evidence, and live-Google setup limits.
