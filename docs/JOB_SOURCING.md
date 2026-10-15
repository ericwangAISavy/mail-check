# Native Job sourcing

Mail-check owns and saves job sheets in its SQLite database. Open **Job sourcing**
to work in a spreadsheet grid, with one workbook per bidder and profile tabs below.
There is no Google account, OAuth configuration, API quota or synchronization setup.

## Create workbooks and profile sheets

1. Create bidders and assign email/profile accounts on **Bidder payments**.
2. As admin, open **Job sourcing → settings**. Select a bidder, name their workbook,
   and choose **Create workbook**.
3. Expand that workbook, choose a currently assigned profile, name the sheet and
   choose **Create profile sheet**. Repeat for each profile/bidder.
4. Each sheet starts with Company, Role and Job link columns and 100 blank rows.
   Paste jobs straight into the grid or import a CSV file.

Admins can read and edit every workbook. Bidders can read, copy, edit, search and
export only their own workbook. The server enforces these rules on direct API
requests too. Admins can archive/restore profile sheets in settings. Archiving
preserves their data. Historical sheets stay with their original bidder if a profile
assignment ends or an email account is removed.

## Bidder sign-in

Use Job sourcing settings to enable each bidder with an initial 8–256 character
password. Share it privately. Bidders select **Bidder**, choose their name and enter
their password. No default bidder passwords are created. The key icon lets bidders
change their own password with their current password. Admins can reset a password
or disable sign-in; old sessions lose access. Bidder payment totals remain based on
classified application-confirmation emails, independently of the job sheets.

## Everyday spreadsheet editing

- Double-click, Enter or F2 to edit. Escape cancels; Enter/Tab commits. Arrows and
  Tab navigate. Shift-click or drag selects a rectangle. Copy/paste supports TSV,
  quoted multiline values and blanks from Google Sheets or Excel.
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
- A rectangle must fit the current sheet. Add rows/columns or use CSV import if it
  extends beyond the grid; the app rejects the entire paste instead of cropping it.
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
its confirmation to replace the data. Replacement preserves column definitions and
runs atomically. Failed imports keep the source visible for retry or correction.
Import/save operation IDs prevent duplicate writes if a response is lost.

**Export CSV** includes the current saved sheet in stored row order, without view
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
