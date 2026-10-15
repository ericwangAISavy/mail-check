# Job sourcing

Job sourcing brings the existing bidder Google spreadsheets into one workspace.
Google remains the source of truth. App edits update the same files, and clean open
sheets refresh every 15 seconds and when the window regains focus.

## Connect Google once

1. In Google Cloud, create a project, enable **Google Sheets API**, and configure
   the OAuth consent screen. If the app is in testing, add the connecting Google
   account as a test user. Google's testing-mode refresh tokens can expire after
   seven days; reconnect when prompted or publish the consent configuration.
2. Create an OAuth client of type **Web application**. Register the exact app
   callback URL: `https://your-app-host/api/google/callback`. For local use, register
   `http://127.0.0.1:8765/api/google/callback` (use the port where mail-check runs).
   The scheme, host, port, and path must match exactly.
3. Sign in as Admin. Open **Job sourcing → settings**. Enter the client ID, client
   secret, and callback URL, save, then choose **Connect Google**.
4. Consent using the one Google account with edit access to all five spreadsheets.
   The app requests the Sheets read/write scope. Bidders need no Google connection.

The operating system credential store holds the OAuth client configuration and
Google tokens; no Google secrets are stored in SQLite or sent to bidders. This
requires a working OS keyring, such as Windows Credential Manager. Headless servers
need an appropriate supported keyring backend. An unavailable keyring produces a
recoverable connection error rather than saving plaintext secrets.

On HTTPS deployments, use the existing `--secure-cookies` server option and configure
allowed hosts as described in the main README. Do not expose the initial admin
password. Changing the admin password preserves Google files and bidder credentials.

## Connect the five workbooks

1. Create each bidder and their email/profile assignments on **Bidder payments**.
2. In Job sourcing settings, choose a bidder and paste their existing Google Sheets
   URL. Each bidder has one workbook; each spreadsheet can belong to only one bidder.
   Connecting verifies that the Google account has edit access.
3. Expand the workbook and map each Google worksheet to one of that bidder's assigned
   profiles. Select the header row and Company, Role, and Job link columns. Column
   letters refer to the original Google sheet. Other columns remain available.
4. Repeat for all five bidders. Removing a mapping unlinks app access and cached
   search results; it does not delete anything from Google. To correct a mapping,
   remove it and map the tab again. Historical tabs remain attached to their bidder
   even if an assignment ends or an email account is removed.

The editor supports tabs up to 100,000 rows and exposes the first 101 columns.
Additional remote columns are preserved. Reads use bounded 1,000-row requests.
Formula cells and rows above/including the selected header are read-only. Edit
formatting, formulas, protected ranges, and sheet structure directly in Google.

## Give bidders access

In Job sourcing settings, enter an initial password (8–256 characters) beside each
bidder and choose **Enable sign-in**. Share that password privately. Bidders choose
**Bidder**, select their name, and enter their individual password. There are no
default bidder passwords. The previous shared Guest login no longer works.

Bidders see only their own workbook and payment totals. They change their own
password through the key icon in Job sourcing. Admins can reset a password or disable
sign-in. Password changes invalidate previous sessions; disabling takes effect on
the next request. The public name selector contains only enabled names and IDs.

## Editing and synchronization

- Double-click, Enter, or F2 to edit; arrows and Tab navigate. Shift-click selects
  a rectangular range for copying or clearing. Paste TSV rectangles from Google
  Sheets or Excel, including quoted multiline values and empty cells.
- Autosave runs after 1.2 seconds without an edit. A save writes only changed cells
  with Google's RAW mode, preserving unrelated formatting and cells. Text beginning
  with `=` stays literal. Existing formula cells are preserved.
- **Append jobs** accepts rows without a header in the sheet's column order and
  appends them to the Google table. Paste at most 10,000 cells per operation.
- Undo/redo applies within the current editor session. Undoing an acknowledged cell
  edit makes another checked write. An external sheet change clears positional undo
  history so it cannot overwrite a different job after a sort. Append is not automatically undone.
- **Saved to Google** appears only after acknowledgment. A failed/conflicting save
  keeps the draft in memory and offers a draft download and review/reload controls.
  Leaving with pending edits prompts before discarding. Signing out clears private
  editor data. Drafts are not persisted in browser storage.

Every write compares the latest Google snapshot with the version opened in the app.
If another person edits/sorts/inserts rows, the app rejects a stale save and asks you
to compare your draft with Google. This preflight check cannot eliminate a Google
UI edit occurring between the check and the write: Google Sheets has no atomic
compare-and-swap API. Avoid simultaneously editing the same rows in both interfaces.

A network failure after submitting a save may mean Google applied it. The app does
not automatically replay ambiguous writes or appends. Open Google, compare the
current rows, download your draft if useful, then explicitly choose **I reviewed
Google; reload**. Check whether appended jobs already exist before appending again.
Successful operation IDs are idempotent; uncertain append operations block additional
appends until reviewed. Operation records are separate from email retention.

When Google is unavailable, previously cached rows may be displayed with an error;
editing stays disabled until a successful refresh. Google permission failures prompt
for reconnection/edit access. Read quota errors respect bounded Retry-After backoff;
writes are never retried automatically.

## Find the application behind an interview

Use **Find application** in interview details, or search Job sourcing by company,
role, job URL, bidder, or profile. Admin searches cover every mapped workbook; bidder
searches cover only their own. Results include freshness and open the matching sheet
row. **Refresh all sheets** updates the search copies before searching recent Google
changes. Search suggests candidates; it does not automatically assert an interview
match. Sheets do not change payment counts, which still use classified application
confirmation emails.

## Validation

Automated tests cover named authentication, owner isolation, Google transport and
OAuth, formula/header protection, revision conflicts, checked/idempotent saves,
ambiguous append recovery, and clipboard/draft behavior. Synthetic browser checks
exercise the editor and two bidder identities. Live Google consent and writes must
be checked after configuring your OAuth project and connecting the actual files.
