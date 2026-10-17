# Daily Job sourcing and inline titles

The user selected a date selector within each profile, keeping previous jobs
available. Existing profile tabs and permissions remain intact. This bounded
change extends native sheets rather than creating separate daily tabs.

## Delivered behavior

- Double-click a title to rename it directly. Required Company/Role/Job link
  identities stay attached to their columns. Renames are shared across days and
  checked against the sheet revision; failed title drafts remain recoverable.
- The title row's number is blank. Visible job rows start at 1, including sorted
  and filtered views; the cell reference bar follows the same numbering.
- Each profile starts on Today in America/Chicago. The date picker, arrows,
  Today, Undated and History open only the chosen day's jobs. Day changes reset
  selection/scroll and undo history. Pending edits block day changes.
- New typed/pasted, inserted, appended and imported jobs use the chosen day.
  Select existing jobs and Assign date to move them, including from Undated.
  Moves use stable IDs, revision checks and idempotent operation IDs.
- CSV replacement affects only the chosen day. Export contains that day's rows
  and names the day in its filename. Cross-day search opens and highlights the
  matching job on its actual day.
- Schema 16 adds nullable row dates. Existing jobs remain Undated; no date is
  inferred or existing value replaced. Legacy API requests without date scope
  retain their previous behavior, including retries of pre-upgrade operation IDs.

## Verification

- Full backend suite: **213 passed**, 59 subtests passed. One existing
  Starlette/httpx deprecation warning remains.
- Frontend: **124 passed** across 19 files.
- Standalone smoke: **331 passed, 0 failed**.
- Production TypeScript/Vite build and `git diff --check`: passed.

Backend regressions cover dated blank-row claims, cross-day write conflicts,
invalid dates, checked/idempotent date moves, daily replace/export isolation,
API date/search context, schema-15 upgrade preservation and pre-date UUID retries.
Frontend regressions cover scoped visible rows and stable base identities, stable
view references during typing, and clearing undo on date changes. New date/filter,
view-identity, cross-day undo and upgrade-retry regressions were observed failing
before their fixes.

Chromium used real endpoints with a disposable SQLite database and synthetic
bidders/accounts. Verified default Today hides legacy jobs; Undated reveals them;
header rename preserves semantic kind; numbering is blank/1/2; Assign date moves
one selected job; pasting on two days keeps them separate; History restores the
chosen day's view; replacing/exporting a day preserves another day and Undated;
search opens the right day and highlights its stable job row. Desktop 1440×950
and mobile 390×844 screenshots were inspected. Page width stays within the
viewport. No page errors occurred.

Browser verification exposed an editor reset caused by recreating the combined
view object during typing. A stable view reference fixes it, and a regression
protects that component contract. A separate check caught undo surviving day
changes; undo now clears before the new day renders. Selections cannot retain
hidden jobs when the day changes. No production/user data was used in checks.

User guide: [Daily jobs and editing](../../JOB_SOURCING.md).
