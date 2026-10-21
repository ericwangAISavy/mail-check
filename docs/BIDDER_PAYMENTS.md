# Bidder payments

Open **Bidder payments** in the sidebar. Admins manage bidders, account assignments,
and payment records. Named bidders use their individual sign-in to view their own
daily and weekly totals and recorded payment amounts. Bidder writes are rejected by
the server. Individual bidder credentials are managed in [Job sourcing](JOB_SOURCING.md).

## Setup and use

1. As admin, open **Accounts**, expand **Manage bidders and account assignments**, and add each bidder.
   Adding a bidder automatically creates their Job sourcing document. **Remove bidder**
   asks for confirmation, disables sign-in, archives their documents, and hides them
   from active lists. Saved documents, assignments, and payment records are retained.
   Job sourcing refreshes its list after additions and removals, including changes
   from other tabs within 15 seconds.
2. Assign one or more connected accounts to the bidder. Set the first assigned day
   to the date they actually started, including earlier dates when appropriate.
   Each assignment has **Edit** and **Remove** controls. Edit the account, first
   day, or optional last day; clear the last day to restore an ongoing rule.
   Removal requires confirmation and changes attribution, without deleting emails.
   Changes affecting a paid week are blocked; changes outside it remain editable.
   One account may be assigned to several bidders on the same day. Shared-account
   confirmation counts are estimated per bidder using their checked links on the same
   account and day. Checked links stay with the bidder who owns the document. Overlapping
   rules for the same bidder and account are blocked.
3. Open **Bidder payments** and use the week selector or arrows to view Monday–Sunday totals in America/Chicago.
   The bidder selector narrows the table and summary to one bidder.
4. After a week ends, select **Record payment**, enter the amount in USD and an
   optional reference, then select **Record as paid**. Amounts are entered manually;
   there is no rate-per-application calculation or money transfer.

## Daily application counts

Daily cells show **checked applications / estimated confirmations**. For example,
**75 / 92** means 75 checked job-link rows and an estimated share of 92 confirmation
emails. The first number is the bidder’s application count used by overview cards,
weekly totals, and new payment records. It sums checked rows across the bidder’s
account tabs, requiring an account assignment on the row’s sourcing date. Each row
counts once; archived sheets retain historical checked counts.

## Verification rules

After mail collection and classification finish, scheduled auto-checks and the
top-level **Check now** job compare confirmation emails against every active account
tab. A confirmation received on day D can check rows dated D through D−6, using
Chicago calendar dates. Company, role when present, and account must match. Manual
**Check applications** on a tab uses the same seven-day relationship.

Checked rows stay checked through later checks, reclassification, and edits. A
confirmation arriving next week can therefore increase the original sourcing day’s
count. Manually checked rows count too. The checkbox cannot be cleared, although
row deletion or changing the row’s date can affect the daily totals.

## Receipt estimates for reference

The second number remains a proportional estimate: per shared account and receipt
day, divide confirmations by the assigned bidders’ checked-link weights for that
account and date. For 105 confirmations and weights 11 and 75, estimates are 13 and
92. Largest-remainder rounding preserves the total, with ties broken by bidder ID.
A sole assigned bidder receives the full receipt count; shared accounts with no
checks show unallocated confirmations. These estimates do not determine the primary
application totals or new payment counts.

Only the latest `application_ack` classification contributes to receipt estimates.
Receipt dates use America/Chicago, falling back to collection time when absent.
Rechecking a message does not duplicate its account/message identity. Estimates
are not proof of submissions, and one confirmation can match several sourcing rows.

## History and payment integrity

A separate ledger stores account/message identities, received timestamps, and
categories and extracted company names and roles. Email bodies are not stored in the ledger. Entries survive normal
email retention cleanup and account removal. New accounts cannot reuse an accounting
account identity. Existing retained classifications populate the ledger automatically.
Emails already removed before this feature was installed cannot be recovered by it.

Payment records snapshot the reviewed checked-link count, entered amount, date, and reference.
The server rejects stale counts, repeat payments for the same bidder/week, and payment
recording before a week ends. Assignment changes that would affect that bidder’s paid
week are rejected. Later classifications and checked-link changes can update estimates but do not rewrite recorded payments;
the table flags any difference between the current count and paid count.

Payment records are immutable in this version. There is no payment gateway or bank
integration. The records describe payments the admin made elsewhere.

The database migration runs automatically on startup. Bidder responses omit the full
account-management list, while assigned account labels remain visible in the table.

## Activity monitor

Below the daily breakdown, the activity monitor shows newly detected checked links
by check run or calendar day, a Chicago-time hourly heatmap, peak detection hour,
active half-hour windows, last detected activity, and latest-versus-previous check
counts. Click bidder chips to filter the graph and payment table together. The
selected payment week also filters activity; the per-check graph keeps the latest
240 checks while daily and hourly views cover the whole week.

Auto-check and Check now record snapshots even when no new links match. Manual tab
checks and saved checkbox marks are recorded too. A stable row identity prevents
repeated checks from duplicating activity. Existing checked rows receive an untimed
baseline on upgrade, rather than invented historical working hours. Activity history
survives later row deletion. Named bidders can only read their own activity.

Activity uses detection timestamps, whereas payment totals use original sourcing
dates. Delivery delays, batch confirmations, and check frequency affect the signal.
Active half-hour windows are not measured working hours or verified submissions.

Use **By bidder** or **By account** to switch the activity monitor. Account chips
filter the same graph, heatmap, peak hour, and change table. Account activity sums
checked document rows across assigned bidders; shared accounts can have overlapping
rows and these are not deduplicated receipt or submission counts. A selected bidder
limits account activity to that bidder's rows. Bidder sign-ins never see another
bidder's contribution, even on a shared account. Existing recorded account IDs and
per-check event cursors support account history without inventing older timestamps.
