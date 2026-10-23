# Google-backed job sourcing and private bidder workbooks

> Superseded by the user’s native-sheet choice. See [native job sourcing design](2026-10-15-native-job-sourcing-design.md). This document records the previous Google-backed approach.

Date: 2026-10-15 (America/Chicago)
Status: Ready for written-spec review

## Intended outcome

Replace the need to open five separate Google Sheets while keeping those files as
the source of truth. Admins and bidders edit job data through a spreadsheet-style
workspace in mail-check. Admins can search all connected workbooks when an interview
arrives. Each bidder can read, copy, and edit only their own workbook.

The user confirmed that one Google account controlled by the admin can edit all five
files. The approved design treats a profile as an email account already assigned to
a bidder. Company, Role, and Job link are the searchable job fields.

## Chosen approach and scope

Use a native spreadsheet editor backed by the Google Sheets API and one admin-managed
Google OAuth connection. Direct embedding would delegate navigation and access to
Google's UI and would not provide the required private app workspace and unified search.
Separate Google connections per bidder would add account setup without a benefit when
one admin identity can already edit the files.

Included in the first release:

- Parent Job sourcing workspace, one child workbook per existing bidder, and profile
  worksheet tabs within each workbook.
- Spreadsheet cell selection, keyboard navigation, editing, multi-cell copy/paste,
  clearing cells, appending job rows, and undo/redo for the current editor session.
- Google reads and writes, visible save/sync status, periodic refresh, explicit
  conflict handling, and preservation of existing remote formatting and columns.
- Named bidder sign-in, admin password setup/reset, bidder password changes, and
  server-enforced ownership checks.
- Admin search across indexed job rows and a Find application action on interview
  details that opens sourcing search with company, role, and profile context.

A full Google Sheets formula/chart/formatting authoring suite is outside this release.
Existing formula cells are displayed and preserved; the app edits literal job-data
cells using RAW writes. It must not silently replace formulas with displayed results.
Sheet entries do not alter email-based bidder payment counts.

## Workspace and editor

The workspace fills the available page area, like an embedded spreadsheet, with no
summary cards or decorative introductory labels. Keep a compact top toolbar, search,
a save indicator, column headers, row numbers, an editable grid, and bottom profile
tabs. Scroll inside the grid. Retain readable columns on narrow screens through
internal horizontal scrolling rather than shrinking text into unreadable cells.

Admins can select any bidder and manage its Google mapping. Bidders land directly
in their own workbook and do not receive a list of other workbooks. Empty and
unconnected workbooks explain that the admin must finish the connection.

Use a maintained, permissively licensed React spreadsheet/data-grid component that
supports React 19 and the required clipboard behavior. Verify compatibility and
license before installing it. Isolate the grid behind a sourcing editor component
so its library-specific selection model does not become an API contract.

Enter/F2 edits a cell; Tab/Shift+Tab and arrow keys navigate; Escape cancels an edit.
Copy and paste accept rectangular TSV, including CRLF, quoted tabs, quoted newlines,
and empty cells. Preserve surrounding Google cells when pasting a smaller rectangle.
Show a validation error before sending an oversized paste; cap a batch at 10,000 cells.
Render text as text and open job links only through validated HTTP/HTTPS URLs.
Undo of a saved edit is a new checked Google write, not an unconditional rollback.

## Google connection and workbook mapping

The admin creates a Google Cloud OAuth web client, enables the Sheets API, configures
an exact callback URL, and connects the Google account from the admin connection UI.
Support localhost HTTP callbacks and configured HTTPS deployments. Request offline
access and the Sheets read/write scope. No Google credentials are requested from bidders.

Keep the public client ID and callback URL in configuration. Store the client secret
and token bundle in the OS credential store, using chunking where the platform requires
it. Never send these values to bidders, include them in normal settings responses,
or write them to repository files or logs. Reuse the app's recoverable credential-store
error handling. Connection status exposes only readiness and the connected account.

OAuth initiation is admin-only. Validate a cryptographically random, expiring,
single-use state, PKCE, and a temporary HttpOnly callback cookie with SameSite=Lax.
Keep the normal session cookie's existing protections. The callback can be publicly
routable only with those validations; it must not depend on a Strict session cookie
being sent on the return from Google. Commit replacement tokens only after validating
the new connection; cancelling or failing reconnect must preserve the old connection.

An admin enters each spreadsheet URL. Parse a Google spreadsheet ID rather than
fetching an arbitrary URL. Confirm edit permission with Google before saving the
mapping. A spreadsheet can belong to only one bidder in this app. Use stable numeric
Google worksheet IDs, so renaming a worksheet does not lose its mapping.

For each profile tab, select a worksheet, its header row, and the columns for Company,
Role, and Job link. Recognize common header names and let the admin correct the mapping.
Other existing columns remain intact and editable where they contain literal values.
A new profile mapping must refer to an account assigned to that bidder. Preserve
historical tabs and their account-label snapshots when an account is removed or an
assignment ends; never transfer one bidder's sourcing data to another automatically.
Unlinking a workbook or tab changes app access and indexing, not the Google file.

## Synchronization and conflict behavior

Google is authoritative. Maintain a local cache and search index, not a second
independent source of job records. Each cached worksheet snapshot has a revision
fingerprint covering its values, formula markers, header mapping, and dimensions.
Read large worksheets in bounded windows and virtualize visible rows in the editor.

1. Authorize the user against the workbook and tab before consulting any cache.
2. Return the latest available snapshot and its Google fetch time. Mark stale data.
3. Accumulate edits and debounce saves after 1.2 seconds of inactivity. Keep only one
   in-flight write per open worksheet; batch rectangular pastes into one operation.
4. Before writing, read the current affected worksheet snapshot from Google and compare
   it with the submitted base revision. Serialize app-originated writes per worksheet.
5. If the snapshot changed, return a conflict with current values and preserve the
   user's pending edits for review. Offer reload/discard or an explicit reviewed retry
   against the refreshed revision. Do not silently write against shifted row positions.
6. Apply only changed literal cells and append rows through Google's append operation.
   Preserve formatting, unrelated cells, and existing formulas.
7. Report Saved only after Google acknowledges the change; refresh the cache and index.

Refresh an open clean worksheet every 15 seconds and on window focus. Coalesce repeated
reads, batch API operations, and respect Google Retry-After and quota responses with
bounded backoff. Dirty cells must not be replaced by a background refresh. A temporary
failure keeps edits in the editor with retry controls and a leave-page warning.
Pending edits are memory-only and are cleared on sign-out or user change.

Every save carries a client-generated operation UUID. Persist an owner-scoped operation
record before calling Google and record the acknowledged range/result on success.
Replaying a completed UUID returns the saved result. A crash or transport failure after
submission leaves an uncertain operation, not an automatic retry. Refresh to reconcile
literal cell writes; an ambiguous append requires review before a new append is allowed,
so a retry cannot silently duplicate job rows. Retain these operation records separately
from email retention and expose them only to their authorized workbook owner/admin.

Google Sheets does not provide an atomic compare-and-swap transaction against edits
made in its own UI. The preflight comparison detects intervening changes, including
sorts and inserted/deleted rows, but cannot eliminate a change occurring between that
check and the write. Document this remaining external-editor race; do not claim
transactional collaboration or guaranteed conflict-free concurrent editing.

Revoked access, missing worksheets, protected cells, invalid mappings, quota limits,
and network failures have distinct messages. Failed saves never display as Saved.
Without Google access, cached rows may be viewed as stale but editing is disabled
until a fresh snapshot and write permission can be established.

## Named authentication and permissions

Replace the shared Guest sign-in option with Admin and Bidder. Preserve the existing
admin password and valid admin sessions. Invalidate legacy guest sessions; they must
not provide a route around bidder isolation. Never create default bidder passwords.

Reuse existing bidder IDs from payment management. Add login enablement to bidder
records and keyed bidder password records to the private auth store. Preserve the
existing salted scrypt hashing, signed expiring cookies, atomic writes, and throttling.
The signed bidder session contains the stable bidder ID and credential version.

The unauthenticated name selector returns only enabled bidder IDs and display names.
It exposes no email accounts, workbook IDs, spreadsheet URLs, or payment information.
Admin sets or resets a bidder password; bidder passwords accept 8–256 characters.
Bidder password change requires the current password and rotates the credential
version to invalidate earlier sessions. Issue a replacement cookie to the browser
that changed its own password. Disabling login also invalidates access immediately.

| Capability | Admin | Bidder |
| --- | --- | --- |
| All sourcing workbooks and cross-workbook search | Read/write | Denied |
| Own workbook and mapped profile tabs | Read/write | Read/write |
| Google connection, file mapping, and profile mapping | Manage | Denied |
| Bidder password setup/reset and login enablement | Manage | Denied |
| Own password | Change | Change with current password |
| Bidder payments | All records; manage | Own totals/payment status; read-only |
| Triage, global Dashboard, calendar, accounts, settings | Existing access | Denied |

Check authorization on every endpoint, including rows, tab metadata, search results,
clipboard/save batches, cache refresh, and direct URLs. Derive bidder identity from
the verified session, never a client-provided owner ID. Out-of-scope workbook and
worksheet IDs return a generic not-found response. Clear query/editor caches whenever
the signed-in identity changes. Bidder bootstrap responses contain only bidder-safe data.

## Persistence and module boundaries

- Extend bidder records with login enablement; preserve assignments, payment snapshots,
  account IDs, and all current mail/calendar data.
- Add `sourcing_workbooks` (bidder owner and unique Google spreadsheet ID) and
  `sourcing_tabs` (workbook, stable worksheet ID, profile/account label snapshot,
  header row, required-column mapping). Store optional tab display names locally.
- Add cached worksheet snapshots/revisions and a searchable row index containing
  workbook/tab identity, row coordinates, Company, Role, Job link, and Google fetch time.
  Rebuild indexed rows from Google; do not subject sourcing history to email retention.
  For the Job link field, use Google's hyperlink metadata when the displayed label is
  different from the actual URL. Preserve formula-backed hyperlinks as formula cells.
- Add owner-scoped save-operation records for idempotency and uncertain-write recovery;
  their UUIDs are not a substitute for workbook authorization.
- Keep password/token material outside the sourcing tables. Add schema/auth-file
  migrations that preserve admin access and do not create Google connections automatically.
- Separate backend modules for Google OAuth/API transport, sourcing persistence and
  synchronization, and sourcing routes. Add a small verified-principal interface to auth
  rather than duplicating role parsing in each route.
- Separate frontend workbook navigation, grid/clipboard adapter, connection/mapping
  management, and personal password controls. Follow existing React Query conventions.

## API contract outline

- Extend login/session responses with bidder identity; add a public enabled-name list,
  admin credential management, and authenticated self-password-change endpoints.
- Admin Google connection endpoints: status, setup, start, callback, disconnect.
- `/api/sourcing/workbooks`: admin sees all, bidder sees only its own.
- Workbook mapping and tab mapping mutations: admin-only.
- Worksheet snapshot/refresh/save endpoints: verify ownership, mapped tab, base revision,
  changed ranges, value types, and batch limits. A save never accepts a Google access token.
- `/api/sourcing/search`: admin searches all mapped tabs; bidder search is restricted to
  its own workbook. Return row coordinates and a link into the app, with an optional
  Google row link for the admin. Show index freshness and incomplete-refresh status.
- Payment/bootstrap endpoints are scoped on the server for named bidders.

Return 401 for missing/expired sessions, 403 for disallowed capabilities, generic 404
for an inaccessible resource, 409 for a conflicting revision, and actionable validation
errors for malformed ranges, profile mappings, and unsupported edits. A Google reconnect
requirement must not be confused with expiration of the bidder's app session.

## Interview lookup

Keep interview matching explicit. Admin can search all connected worksheets by Company,
Role, Job link, bidder, or profile. Find application in interview details prefills
company/role and available account context. Search results show bidder, profile,
worksheet, job fields, and freshness. Opening a result navigates to and highlights
its sheet row. Never automatically declare a company-name-only match correct.

## Verification and rollout

Automated tests must cover:

- Migration preserving the admin credential, payment history, email data, and calendar
  data; guest-session rejection; bidder names, login, disablement, password reset/change,
  credential-version revocation, and generic incorrect-password responses.
- Cross-bidder denial for every workbook/tab/read/write/search/cache route, including
  forged owner IDs and guessed URLs. Confirm own-only payments and safe bootstrap data.
- Google OAuth state, expiry, replay prevention, PKCE, refresh, missing edit access,
  reconnect failure, and unavailable OS credential storage using mocked transports.
- Cell and rectangular paste writes, append, blank cells, quoted TSV, formulas preserved,
  unexpected remote edits/row shifts, duplicate retries, quota backoff, and failures that
  preserve pending editor values. Retry ambiguous network writes by refreshing first.
- Keyboard selection/editing, copy/paste, undo/redo, save states, navigation with pending
  edits, bidder/admin navigation, profile tabs, and interview-to-row lookup.
- Desktop and mobile layout, internal grid scrolling, session expiry, sign-out cleanup,
  and no data or credentials from another bidder in responses or the browser cache.

Run the full existing Python, standalone smoke, frontend, and production-build checks.
Browser-test with synthetic workbooks and two different bidder identities. Live Google
verification is a separate setup-dependent step requiring the user's OAuth project,
Google consent, and spreadsheet mappings; report honestly if it remains unverified.

Provide setup documentation explaining the exact redirect URL, required Google API/scope,
credential storage, connecting the five files, profile/column mappings, bidder passwords,
sync timing/conflicts, and recovery. Do not seed production rows or change Google sharing
permissions automatically. Existing pending page-heading cleanup stays separate from
this feature's design-document commit.
