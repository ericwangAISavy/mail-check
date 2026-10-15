# Native Job sourcing verification

Date: 2026-10-15
Spec: [Native sheet design](../specs/2026-10-15-native-job-sourcing-design.md)
Plan: [Implementation plan](../plans/2026-10-15-native-job-sourcing.md)

## Delivered

SQLite-owned bidder workbooks and assigned-profile tabs replace the active Google
synchronization workflow. Stable row/column identities, per-cell versions, atomic
writes and durable operation IDs protect edits and retries. The editor provides
rectangular clipboard operations, formatting, local undo/redo, row/custom-column
controls, sorting, filtering, search, CSV preview/import/export and guarded autosave.
Interview lookup includes the source account when unambiguous. Native settings
manage workbook creation, profile sheets, archiving and existing bidder passwords.

Cached legacy sheets migrate once without network access. Google files, credentials
and legacy tables/modules remain intact for recovery. Native data is independent
of email retention. The guide documents migration notices, limits and backups.
Formula evaluation, charts and pivot tables are outside this implementation.

## Automated evidence

Final commands, after the review fixes and formatting:

- `/tmp/mail-check-venv/bin/python -m pytest -q`: **206 passed**, 59 subtests passed;
  one existing Starlette/httpx deprecation warning.
- `/tmp/mail-check-venv/bin/python -m tests.test_smoke`: **331 passed, 0 failed**.
- `npm --prefix frontend test`: **117 passed**, 18 files.
- `npm --prefix frontend run build`: TypeScript and Vite passed; bundled frontend rebuilt.
- `git diff --check`: passed.

Focused tests cover atomic conflicting/independent edits, idempotent retries,
stable IDs after insertion/deletion, cross-bidder read/write/import/export denial,
legacy cache migration, consistent read transactions, required column protection,
CSV replacement/escaping/mapping, and a 2,000-row import within the cell budget.
Frontend regressions cover active typing, pending reads, merged-save undo safety,
structure-dialog identity, import file-read lifecycle and discarded append drafts.
New regression cases were observed failing before their fixes.

## Browser evidence

Chromium used real FastAPI endpoints and SQLite with synthetic data in a disposable
`/tmp` database; no production data or external Google files were modified.

- Admin: bold formatting; rectangular multirow paste; sorted edit preserves the job's
  stable row ID; find/filter; insert rows; add a custom column; CSV preview/import/
  export; search opens and highlights the correct stable row; native settings.
- Bidder scope: another bidder's workbook is absent from the index and search;
  direct sheet and CSV export requests return 404.
- Two sessions: admin changes the bidder's actively edited cell; bidder save conflicts,
  preserves the draft, downloads it, blocks navigation, and reloads the admin value
  only after confirmed discard.
- Uncommitted typing survives a window-focus refresh.
- Desktop 1440×950 and mobile 390×844 fit the viewport; horizontal spreadsheet
  scrolling stays inside the editor. Screenshots inspected after resize transitions.
- No browser page errors in the main workflow.

## Review disposition and implementation decisions

One fresh whole-feature review identified six important issues: refresh discarding
active typing, stale undo after a merged response, late GET responses replacing
acknowledged saves, structural dialogs resolving old positions against new data,
closing an import while its file read was pending, and partial CSV header matches
misrouting fields. All were reproduced with regressions and fixed. The related
1,000-row CSV restriction was also fixed to honor the documented 10,000-cell budget.
Additional checks fixed autosave during active typing and hidden append drafts.
No important review findings remain deferred.

The user explicitly approved native implementation, so work continued inline
without another design approval. Backend and frontend are committed together to
avoid an intermediate application with mismatched APIs. Existing Google modules
remain as recovery code, with no active sourcing routes invoking them. This change
is committed locally; it is not merged or pushed as part of implementation.

## HTTP browser compatibility follow-up

A user screenshot exposed `crypto.randomUUID is not a function` during autosave.
The initial browser verification used localhost, which browsers treat as secure;
ordinary HTTP origins do not expose `randomUUID`. All five sourcing write paths
now share an operation-ID helper using native UUIDs when available, otherwise
RFC 4122 version-4 UUIDs from `crypto.getRandomValues`, which remains available
on HTTP. Idempotent retries retain the same operation IDs as before.

The HTTP autosave regression failed with the exact reported error before the fix.
Final frontend suite: **120 passed**, 19 files. Production TypeScript/Vite build
and `git diff --check` passed. Chromium verification used `http://mailcheck.test`
resolved locally, confirmed `isSecureContext=false`, `randomUUID=undefined`, and
`getRandomValues=function`, then passed formatting, rectangular paste, sorted
editing, row insertion, custom columns, CSV import/export, search and bidder scope
with no browser page errors. No backend behavior changed in this follow-up.
