# Native mail-check job sheets

Date: 2026-10-15
Status: Implemented and verified locally; see [verification](../verification/2026-10-15-native-job-sourcing.md)
Supersedes: Google-backed sourcing design and synchronization implementation plan.

## User's revised choice

The user has selected the native-sheet alternative previously discussed. Mail-check
will own and save job sheets itself. Users work in a familiar Google Sheets-style
editor inside mail-check, without connecting or synchronizing separate Google files.
The original purpose remains: manage jobs for five bidders in one place and find
which application corresponds to an interview.

## Workspace and access

- Keep Job sourcing as the parent workspace, one workbook per bidder, and one tab per
  profile assigned to that bidder. Reuse the existing named bidder authentication.
- Admin reads and edits every workbook. Bidders read, copy, search and edit only
  their own workbook. Check ownership on the server for every operation.
- Admin manages profile tabs and bidder access. Preserve historical tabs when an
  assignment ends or an account is removed; never transfer their contents to another
  bidder automatically.
- Keep payments based on classified application-confirmation emails. Job rows do not
  alter payment counts.

## Spreadsheet experience

Reuse the current React grid and replace Google-dependent settings and save behavior.
Use a compact, familiar spreadsheet layout: column letters, row numbers, cell-value
bar, editing toolbar, internal scrolling and bottom profile tabs. Match the app's
appearance while making the sheet feel like an embedded workspace.

The first release supports:

- Company, Role and Job link as initial columns; custom columns can be added.
- Keyboard navigation, typing, rectangular selection, copy/paste and clearing cells.
- Quoted multiline TSV and empty cells when copying from Google Sheets or Excel.
- Adding, inserting and deleting rows; adding, renaming, resizing and deleting custom
  columns. Required job fields remain identifiable if their labels/order change.
- Basic formatting: bold, italic, text alignment and text wrapping. Store formatting
  separately from values; copy/paste remains useful without copying rich formatting.
- Sorting and column filters, find within a tab, and application search across all
  workbooks an admin can access. Bidder search stays limited to the bidder's workbook.
- Autosave with visible Saving/Saved/Failed state, undo/redo and safe recovery of
  unsaved edits. Prevent silent cropping of pasted rectangles; grow the grid within
  documented limits or reject the whole paste with an explanation.
- Validated HTTP/HTTPS job links, CSV import/export and ordinary clipboard copying.

The goal is familiar everyday spreadsheet editing for job sourcing. A general
formula engine, charts, pivot tables and full Google Sheets feature parity are
outside this release. Treat imported formulas as displayed values, mark this during
import, and do not execute pasted text as code or formulas.

## Native storage and concurrent edits

SQLite becomes authoritative, rather than a cache of Google. Store native workbooks,
profile tabs, column definitions, stable row IDs, cell values and formatting in new
native tables. Keep row identities stable across sorting, insertion and deletion;
never apply a save using only an old visual row number.

Save changed cells in an atomic database transaction. Each operation has a UUID for
idempotency. Check expected cell/row versions: independent edits can merge, but
conflicting edits to the same cell or deleted rows must return a conflict and keep
pending editor values available for review. Structure changes use a tab revision.
Undoing a saved change is another checked write, not an unconditional rollback.

Refresh clean sheets periodically and on focus. Do not replace dirty drafts with a
background response. Warn on navigation, including browser Back between sourcing
queries. Clear private editor/query data on sign-out or identity change.

Native sheet data, permissions and operation records are independent of email
retention. Document SQLite backup and restore because the app now owns the records.
CSV is an interchange option, not a replacement for full database backups.

## Existing Google-backed data

- Do not delete, modify or change sharing permissions on external Google files.
- Preserve existing mappings and cached snapshots during migration. Convert available
  cached rows into native sheets transactionally and idempotently, retaining owner,
  profile labels, column mapping and displayed job links. Record that these are the
  last cached values and may not include newer Google edits.
- Allow users to bring current data over by rectangular copy/paste or CSV import.
  Preview imports and offer append or replace; replacement requires confirmation.
  Validate the whole import before writing, and do not silently combine a cached
  migration with a second copy of the same rows.
- Existing Google formulas become their cached display values. If a display value is
  unavailable, flag the cell for review rather than claiming it was imported fully.
- Keep legacy Google tables intact for recovery, but stop using them for active sheet
  reads/writes. The new sourcing workflow has no Google login, token, API, sync,
  external-sheet mapping or quota dependency. Do not silently erase stored credentials.

## Implementation sequence

1. Add native schema, stable row/column identities, revisions and operation records;
   test migration and preservation of bidder ownership and cached data.
2. Replace sourcing read/write/search APIs with native transactional operations;
   retain authentication and payment isolation. Add row/column, formatting, sort/filter
   and scoped CSV import/export endpoints.
3. Adapt the existing grid and settings to native workbooks and assigned-profile tabs.
   Add the compact editing controls and remove Google setup/sync controls.
4. Connect search results and interview lookup to stable native row identities.
5. Verify permissions with two bidders, concurrent edits, idempotent retries,
   migration, clipboard/import, undo/redo, draft recovery, desktop/mobile layout,
   backup guidance and all existing application regression tests.

## Success criteria

An admin or bidder can open their permitted sheet, paste jobs, edit and organize them,
reload and find the saved rows without any Google connection. Admin can search all
bidders' jobs from an interview and open the matching profile/row. A bidder cannot
read or change another bidder's data through the UI, direct API calls, search or
exports. Existing email/calendar/payment behavior and external Google files remain
preserved.
