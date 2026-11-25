# Native Job sourcing

> In owner-managed mode, only the owner and admins sign in. Each admin has an
> isolated workspace; bidders are managed records. Any bidder-login permissions
> described below apply only to the legacy standalone compatibility mode. See
> [Multi-admin workspaces and rollback](MULTI_ADMIN.md).

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

Admins can open **Accounts → Link history** on an email account to remove retained
sourcing links. Choose a bidder, including deleted bidders, and optionally filter
by sourcing date. Leaving both dates empty includes undated links. Archived tabs
are included. Review the selected and checked-link counts before confirming
permanent deletion. A changed sheet requires a fresh preview.

Removing checked rows can change calculated application and payment totals.
Saved payment records are retained. Cleared links become available for reuse
through the usual account-level duplicate checks.

Select the account tab and job date, wait for **Saved**, then click
**Check applications**. For each job link on that tab and date, mail-check compares
its company and role with a single saved **Application received** confirmation from
the same account. If the confirmation includes a role, company and role must both
match. Only confirmations with no role allow company-only matching. A missing role
on the sourcing row does not bypass a role present in the email. Missing roles in older receipts are filled from retained email
classifications when available.
Confirmations received during the ten-day window beginning on the sourcing date
count: Chicago midnight on that date inclusive to midnight ten days later exclusive. Choose a date first; Undated rows cannot be checked.

The top-level **Check now** button and each scheduled **Auto-check** run also
verify all dated jobs on every active tab in every workbook after collection and
classification finish. Each row is compared against confirmations received within its
own ten-day window beginning on its work date, including earlier dates. Archived tabs and tabs whose accounts have
been removed are skipped. The completion message includes the matched-link and tab
counts. An open, saved sheet refreshes immediately; active edits remain protected.
Automatic verification adds new matches and never clears existing checks.

Before comparison, company names ignore case, separator punctuation, dotted
initialisms and trailing legal suffixes such as Inc. or LLC. Roles normalize
Sr./Senior and explicit Remote/Hybrid annotations. Exact company/role matches
win first; otherwise either complete normalized company phrase may contain the
other. Roles also allow whole-phrase containment in either direction.
For example, Inspira Financial matches Inspira Financial Trust LLC, and AI
Operations Engineer matches Principal AI Operations Engineer. Word fragments
do not match: Meta is not Metamask, Engineer is not Engineering, Engineer II is
not Engineer III, and C++ is not C#. No fuzzy similarity is used.

Both manual **Check applications** and automatic checks consider competing jobs
across the same account's active bidder tabs. A role-qualified reply checks every
eligible row in the winning company/role matching tier and date window, even
when URLs have different job IDs. Each row retains the confirmation as proof. A
company-only reply without a job reference checks all matching company links
for that mailbox in the existing date window, across roles, job IDs and eligible
source dates. Exact normalized company matches take priority over whole-phrase
company aliases. If the original email identifies a job, that identity still
limits a role-less confirmation to its matching links. All checks—automatic,
periodic, selected-week refresh/rebuild, and manual
**Check applications**—check only unchecked links. Existing checks, receipt
bindings and confirmation dates stay saved even when matching rules, receipt
classifications or extracted company/role details change. This protection includes automatic and manual checks and archived sheets.
Saved receipts may also check later matching rows when the
original bound row remains eligible. Reclassification cannot move saved proof
to an unrelated company or role; archived bindings remain protected.

On **Bidder payments**, daily cells show **checked applications / received replies**.
For example, **60 / 112** means 60 checked job-link rows and an allocated share of
112 application-received emails. Checked applications are bright; received replies
are grey. Weekly totals and new payment records sum checked applications. Calculated
pay is `pay per bid × checked applications × (1 + editable adjustment / 100)`.
Shared-account replies are divided in proportion to checked links per account/day
for reference only; that allocation does not change the payment basis. Matched rows
use their reply's Chicago received date. Untimed manual/legacy checks retain their
sourcing date. Saved payments and manual amount overrides remain unchanged.

## Everyday spreadsheet editing

- Double-click a column title to rename it directly; its Company/Role/Job link
  identity stays intact. The title row has no number; job rows start at 1.
- Double-click, Enter or F2 to edit. Escape cancels; Enter/Tab commits. Arrows and
  Tab navigate. Shift-click or drag selects a rectangle. Hold the pointer near the table’s top or bottom edge while dragging to scroll and extend the selection beyond the visible rows. Scrolling stops when you release the mouse or the window loses focus. Copy/paste supports TSV,
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

## Confirmation times

Each matched row stores its earliest valid confirmation received timestamp. Hover
its checked box to see that time in Chicago. Activity graphs use this receipt time;
check-run processing timestamps remain separate. Admins can use **Refresh** on
Bidder payments to repair timestamps and recheck the last seven Chicago dates of
stored confirmations and sourcing rows. Existing checks remain permanent, and
sourcing-date application totals keep their original date attribution.

## Automatic incoming job filters

Job sourcing → **Job link filters** lets admins save a workspace-wide company
blocklist, one company name or name fragment per line. A new row is blocked when
its Company name contains any listed name, ignoring case, whitespace and
punctuation. For example, `Acme` blocks `ACME Inc.` and `The Acme Group`.
Blocking rules are separate from the full-identity confirmation matching rules.
Saving the list does not remove historical jobs.

Grid URL entry/paste, appended job rows and CSV imports filter incoming rows
inside the write transaction. Duplicate URLs are compared against all stored
native tabs for the same account, across bidders and sourcing dates, and against
earlier rows in the same batch. Different accounts can keep the same job. URL
comparison ignores `jr_id`, `utm_*`, `gclid`, and `fbclid`, normalizes query order,
HTTP/HTTPS and trailing slashes, while preserving job identifiers in query values.
Known ATS URLs also share a provider-specific identity across URL formats.
BrassRing uses `partnerid` plus `jobid`: different `siteid` values and tracking
parameters do not create separate jobs. Distinct employers or job IDs remain
separate, and the first pasted copy's original URL is retained.
Blocked company rows and duplicate rows are deleted as whole incoming rows;
positions are compacted so no removed-row holes remain. Existing checked rows
are protected during grid edits. Formatting edits do not trigger filtering.
The save response reports duplicate and blocked-company counts. Operation retries
reuse the recorded filtering result and do not insert the same batch twice.

### Select and protect rows

Click any cell or row number to select the whole job row. Drag or Shift-select to
include several rows. **Ctrl/Cmd+C** copies every column of the selected rows as
tab-separated text; **Delete** or **Backspace** uses the existing row-removal flow.
Rendered cell text does not use browser text selection. Double-click an unchecked
cell to edit it. Use Ctrl/Cmd-click to open a job link without changing it.

Checked rows have a green tint and green job links. Their cell values and formatting
are read-only, enforced by both the grid and save API. They can still be selected,
copied, moved to another date, or explicitly deleted as rows. A newly pasted row
may include its job details and initial checked state in the same save.

### Diagnose an unchecked company confirmation

A missing role does not prevent matching: when a confirmation has no role or
job reference, all eligible company links for the same mailbox can be checked,
including other bidder tabs and roles within the existing date rules.
Existing receipt bindings are preserved; receipts can be shared
with additional matching rows while the original bound row is still eligible.
Do not infer the cause of an unchecked row from the currently visible sheet alone.

Run the diagnostic in the app’s Python environment (its virtualenv or application
container). It opens the workspace database without migrations, matching writes
or receipt syncing, and uses the actual matcher against saved receipt data:

```sh
python tools/explain_application_matches.py --database /actual/path/mail.db --account eric.wang.swe@outlook.com --company HP > hp-match-report.json
```

It lists company-related rows across account tabs, sourcing dates, roles, checked
states, archived status, account compatibility, saved receipt bindings, and new
matches the current matcher would propose. The report includes business metadata
but excludes email bodies, job URLs, credentials and receipt identifiers. It is a
snapshot of saved data, not a replacement for a selected-date check. Share the
report to investigate the precise reason before changing matching rules.

After **Check applications**, expand **links remain unchecked — view reasons**
to see the actual mailbox checked, which rows remain unresolved, and why. Reasons
distinguish incompatible saved proof and missing eligible confirmation evidence.
Without such evidence, the row reports that no eligible
confirmation was found for its mailbox, company, role and date window. The panel
shows up to 50 rows from the last check; run another check to refresh it. No saved
checkmarks, receipt dates or payment records are changed to create these reasons.

### Additional confirmation evidence

The company, role, mailbox and date matcher runs first. Role-qualified matches
check all eligible rows, including different job IDs, rather than stopping at
multiple candidates. Additional alternatives add supported confirmations to unchecked
rows using employer names explicitly stated in the email,
company spacing and `and`/`&` variations, verified titles from the linked posting,
and explicit application URLs or requisition IDs. Role-qualified confirmations
may also check other company/role matches even when an explicit link points to a
different job ID. Company-only confirmations keep stricter identity checks. Historical rows can
match outside the ordinary date window only with explicit application identity.

Verified posting titles can resolve stale imported titles and distinguish a
location qualifier such as Canada. Without a classified role or job reference,
company normalization and explicit employer evidence can check all related rows.
Unresolved company names and unsupported title similarities remain unchecked. The new
passes do not credit messages explicitly stating that an existing application
was overwritten or was already on file. Existing checkmarks and their proof stay
unchanged.

Normal application checks retrieve public Greenhouse, Ashby, Lever and Workable title
metadata with a bounded request budget, outside database write transactions.
Successful results are cached for 24 hours; unavailable postings retry after ten
minutes. Passive payment refreshes and the read-only diagnostic use cached facts
without network requests. A missing or unavailable posting never invalidates an
existing match; additional matches may become available on a later check.
Concurrent checks share an eight-request limit per process. Local capacity
shortages retry on a later check without caching a posting as unavailable.
Account-specific checks apply their mailbox scope before the evidence limit.

Each new fallback records its rule, explanation, email identifier and any linked
posting title in `sourcing_match_evidence`. These records supplement the existing
confirmation proof and accounting history. The read-only diagnostic reports the
matching rule while continuing to omit email bodies, URLs and receipt identifiers.

### Matched confirmation mark

Application-received emails show a small **Matched** check mark in the mail list
and reader when their saved confirmation proof points to a checked job link.
This is independent of the email's Done/Restore state. Unmatched emails keep
their usual category label. Removing the linked row, losing its checked link,
or reclassifying the email removes the mark on refresh. Proof is scoped to the
same mailbox, so identical message IDs in another account do not share a mark.

### Shared Job links filters

The Job links toolbar offers **Exclude my links**, enabled by default. It hides
the selected workspace's retained links and copies of those URLs in other
workspaces, using the same job identity normalization as incoming paste filters.
Own-link comparison includes all source dates, independently of the search date
range. Disable this option to search the complete library, including your sheets.

**Exclude one-page links** is off by default. Enable it to hide links hosted on
Greenhouse or Ashby. Both filters apply before pagination and work with keyword,
date range and page-size choices. Filter choices remain in the page URL, and
changing either filter returns to page one. If owned links cannot be read, the
page reports an incomplete search rather than showing potentially owned copies.
The database read and URL-normalization steps use separate budgets, so a large
saved-link history does not fail merely because normalization takes longer than
the short SQL read limit. Normalization remains bounded by the overall request
deadline. When this ownership check is unavailable, the warning identifies it
and offers an explicit **Include my links** retry. An incomplete empty result
does not claim that no matching jobs exist.
URL-filter computation in other workspace searches also uses the overall
request budget rather than the SQL read allowance. The total deadline remains
enforced even for small reads. A failed refresh replaces cached retry advice
with the current error, including permission revocations.
