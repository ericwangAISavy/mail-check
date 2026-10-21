# Native Job sourcing

Mail-check owns and saves job sheets in its SQLite database. Open **Job sourcing**
to work in a spreadsheet grid, with one workbook per bidder and profile tabs below.
There is no Google account, OAuth configuration, API quota or synchronization setup.

## Create workbooks and profile sheets

1. Create bidders and assign email/profile accounts on **Bidder payments**.
2. As admin, open **Job sourcing → settings**. Select a bidder, name their workbook,
   and choose **Create workbook**.
3. Expand that workbook, choose a currently assigned account and select
   **Create profile sheet**. Tabs use account names, including existing tabs;
   custom tab names are no longer used. Repeat for each account/bidder.
4. Each sheet starts with Company, Role, Job link and a compact Check column,
   with blank input rows.
   Paste jobs straight into the grid or import a CSV file.

Admins can read and edit every workbook. Bidders can read, copy, edit, search and
export only their own workbook. The server enforces these rules on direct API
requests too. Admins can archive/restore profile sheets in settings. Archiving
preserves their data. To permanently delete a tab, select it and click **Delete tab**
beside the tab controls, review the row count, then confirm. Deletion is admin-only,
removes all rows and checked-link counts from that sheet, and cannot be undone.
Received emails and recorded payments remain saved. Finish saving edits before
opening the delete confirmation. Historical sheets stay with their original bidder if a profile
assignment ends or an email account is removed.

## Bidder sign-in

Use Job sourcing settings to enable each bidder with an initial 8–256 character
password. Share it privately. Bidders select **Bidder**, choose their name and enter
their password. No default bidder passwords are created. The key icon lets bidders
change their own password with their current password. Admins can reset a password
or disable sign-in; old sessions lose access. Bidder payment totals remain based on
classified application-confirmation emails. The daily table also shows checked
job-link counts from their sourcing sheets.

## Daily job lists

Each profile opens on **Today** in America/Chicago. Use the date picker, previous /
next arrows, or **History** to work on another day. Only that day's jobs appear;
earlier jobs remain saved. Blank template rows are available for new jobs. Typing,
pasting, inserting or importing jobs assigns them to the selected day.

Existing jobs have no inferred date. Open **Undated**, select a job or a rectangle
of jobs, click **Assign date**, choose their intended day and confirm. The editor
opens that day after moving them. Assign date can also reschedule jobs from one day
to another, or return them to Undated. Select at most 1,000 jobs per move.

CSV import appends to the selected day. **Replace existing rows** replaces only
that day's rows; other days and Undated remain intact. CSV export includes only
the selected day and includes the day in its filename. Search covers every saved
day and opens a match on its own day. Profile tabs and column titles are shared
across all days. Switching days is blocked while edits or imports are pending;
undo history clears on a day change so it cannot affect another day's jobs.

## Check received applications

Select the account tab and job date, wait for **Saved**, then click
**Check applications**. For each job link on that tab and date, mail-check compares
its company and role with a single saved **Application received** confirmation from
the same account. If the confirmation includes a role, company and role must both
match. Only confirmations with no role allow company-only matching. A missing role
on the sourcing row does not bypass a role present in the email. Missing roles in older receipts are filled from retained email
classifications when available.
Confirmations received during the seven-day window beginning on the sourcing date
count: Chicago midnight on that date inclusive to midnight seven days later exclusive. Choose a date first; Undated rows cannot be checked.

The top-level **Check now** button and each scheduled **Auto-check** run also
verify all dated jobs on every active tab in every workbook after collection and
classification finish. Each row is compared against confirmations received within its
own seven-day window beginning on its work date, including earlier dates. Archived tabs and tabs whose accounts have
been removed are skipped. The completion message includes the matched-link and tab
counts. An open, saved sheet refreshes immediately; active edits remain protected.
Automatic verification adds new matches and never clears existing checks.

Before comparison, company names stop at the first comma or period, then lose
spaces and punctuation. ASCII letters and company digits are kept, so
`4A Consulting, LLC` matches `4AConsulting`. Roles stop at the first character
other than an ASCII letter or space, then lose all spaces. For example,
`Software Engineer - Backend` matches `Software Engineer | Remote`. Both fields
are compared without case sensitivity. No fuzzy similarity is used.
Once checked, a job link stays checked, even after reclassification,
company or link edits, or date changes. Unchecked links may also be marked manually;
checked boxes cannot be cleared.

On **Bidder payments**, daily cells show **estimated confirmations / checked sourcing
links**. For example, **112 / 60** means 112 estimated confirmations allocated to the
bidder and 60 checked job-link rows on their sourcing sheets for that day. Shared
account confirmations are divided in proportion to checked links per account and day.
The two counts can differ. Saved company metadata survives future mail cleanup;
companies from messages already deleted before this upgrade cannot be recovered.

## Everyday spreadsheet editing

- Double-click a column title to rename it directly; its Company/Role/Job link
  identity stays intact. The title row has no number; job rows start at 1.
- Double-click, Enter or F2 to edit. Escape cancels; Enter/Tab commits. Arrows and
  Tab navigate. Shift-click or drag selects a rectangle. Copy/paste supports TSV,
  quoted multiline values and blanks from Google Sheets or Excel.
- Drag across cells to select the job rows they cover. Selected rows and row
  numbers are highlighted. Click **Delete rows** (with the selection count), or
  press **Delete** while the grid is focused, to remove those entire job rows.
  Finish editing and wait for **Saved** first. Delete inside a cell editor still
  edits its text; **Backspace** outside the editor clears selected cell values.
  Filtered/sorted selections delete their original saved row identities.
- Use the toolbar for bold, italic, alignment, wrapping and undo/redo. Formatting is
  stored separately from values. Text beginning with `=` remains literal text.
- Insert rows and add/rename custom columns. Choose **Insert / edit** for append,
  deletion and column actions. Company, Role and Job link columns can be renamed;
  their job-field identity stays intact and they cannot be deleted.
- Use the filter icon for find-in-sheet, column filtering and A–Z/Z–A sorting.
  These are views of stable job rows; editing a sorted row changes that job.
- Autosave waits 1.2 seconds after committed edits. Active typing is protected from
  refresh; earlier committed cells wait until editing finishes. Watch for Saved,
  Saving or an error. Clean sheets refresh every 15 seconds and on focus.
- Entirely blank pasted/imported rows are removed automatically. One empty input
  row remains after the last job. Pasting jobs into that empty row can append more
  rows automatically. Other rectangular pastes must fit the existing grid; add
  rows/columns or use CSV import when needed.
- Limits: 101 columns, 100,000 rows per sheet; 10,000 cells per save, paste or import;
  50,000 characters per cell; CSV input up to 2 MB. Manual row insertion allows
  1–1,000 rows at a time; larger CSV imports can use the full cell budget.

This is a job-sourcing spreadsheet editor. Formula calculation, charts and pivot
tables are outside its scope. Use ordinary values for job records.

## Import and export

Choose **Import CSV**, select a file or paste CSV text, then inspect the preview and
column destinations. With headers enabled, matching column names and Company/Role/
Job URL aliases map to their respective job fields regardless of order. Unknown
headers create custom columns. Duplicate destinations or malformed CSV are rejected
before any rows change. With headers disabled, values follow the sheet’s column order.

Choose **Append jobs** to keep existing rows, or **Replace existing rows** and check
its confirmation to replace the selected day’s data. Replacement preserves column definitions and
runs atomically. Failed imports keep the source visible for retry or correction.
Import/save operation IDs prevent duplicate writes if a response is lost.

**Export CSV** includes the selected day’s saved rows in stored order, without view
filters or formatting. Values beginning with spreadsheet formula characters are
prefixed with an apostrophe so spreadsheet programs treat them as text on opening.
An exported CSV is an interchange file; use a database backup to preserve styles,
identities, all workbooks and permissions.

## Existing Google-backed sheets

On upgrade, available cached Google rows are copied once into native sheets. Owner,
profile labels and mapped job fields are retained. Actual cached hyperlink URLs are
preserved. Formula cells become their cached displayed values; missing display values
are flagged in **Imported sheet information**. A sheet without a usable cache starts
empty and explains that its current jobs must be pasted/imported.

The imported copy may lag the original Google file. To bring over newer data, export
that file to CSV and use the preview and confirmed replacement, or copy/paste its
current rows. Do not append the same cached rows again unintentionally.

External Google files and their sharing permissions are untouched. Legacy mapping,
cache and operation tables are retained for recovery, and stored Google credentials
are not erased. The active sourcing workflow never reads or writes Google.

## Concurrent edits and recovery

Cells have stable row/column IDs and versions. Independent edits can merge. Changes
to the same cell, removed rows/columns and stale structure/import operations return a
conflict without partially applying the request. Unsaved drafts remain available to
download, retry or discard/reload. Undo is another checked save; externally changed
cells clear unsafe history. Navigation, including browser Back between sourcing
queries, warns about pending edits. Signing out clears private editor data.

## Application lookup

Search by company, role, job link, bidder, profile or custom-cell text. Admin searches
cover all active workbooks; bidder searches cover only their own. Results open the
matching profile and highlight its stable row. **Find application** in interview
details opens sourcing search. Matches are suggestions for manual review.

## Backup and restore

Native jobs are independent of email-retention pruning. Include the SQLite database
shown under **Settings** in backups, together with the private `web-auth.json` file
and configuration. Stop mail-check before copying/restoring the database; copying
only the main database file while WAL writes are active can miss recent changes.
For an online backup use SQLite's backup facility, rather than a raw file copy.

To restore, stop the app, retain the current files as a recovery copy, restore the
trusted database/auth/config backup, then restart. Protect backups because they
contain application data and password hashes. CSV files alone do not restore the
complete workspace.

## Missing daily links

Admins see an amber warning in the top toolbar naming active bidders with no saved
job links on the selected job date across any active account tab. Blank links and
archived tabs do not count. The warning refreshes after saved edits and every
15 seconds, and is hidden in the Undated view.
