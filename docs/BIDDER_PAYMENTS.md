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
4. Set each bidder’s **Pay per bid (USD)** and **Adjustment (%)** on Accounts. The default adjustment is 20%, meaning a multiplier of 1.2. Weekly pay is `rate × estimated weekly total × (1 + adjustment / 100)`, rounded once to cents with decimal half-up rounding. For example, `0.05 × 309 × 1.2 = $18.54`.
5. On a completed week, **Edit / record payment** opens a prefilled amount. Edit it and choose **Save amount** to override that week without marking it paid. **Use calculated amount** removes the override. Manual amounts remain saved if counts change, with a warning to review them.
6. After making the actual payment elsewhere, choose **Record as paid** with an optional reference. Saved paid amounts do not change when rates, estimates, or adjustment percentages change. No action here transfers money.

## Daily application counts

Daily cells show **estimated confirmations / checked applications**. For example,
**92 / 75** means an estimated share of 92 confirmation emails and 75 checked job-link rows. Overview cards, weekly totals, and new payment records sum the first number: daily estimated confirmations. The second number counts checked rows across the bidder’s
account tabs, grouped by the matching confirmation’s received date in Chicago and requiring an account assignment on that completion date. The date links were given does not determine the payment day. Manual or legacy checks without a matched confirmation timestamp keep their sourcing date. Each row
counts once; archived sheets retain historical checked counts.

## Verification rules

After mail collection and classification finish, scheduled auto-checks and the
top-level **Check now** job compare confirmation emails against every active account
tab. A confirmation received on day D can check rows dated D through D−6, using
Chicago calendar dates. Company, role when present, and account must match. Manual
**Check applications** on a tab uses the same seven-day relationship.

Checked rows stay checked through later checks, reclassification, and edits. A
confirmation arriving next week counts on its received date, including links given the previous week. Manually checked rows count too. The checkbox cannot be cleared, although
row deletion can affect totals. Changing a sourcing date only moves an untimed manual or legacy count; matched completions retain their confirmation date.

## Receipt allocation

The first number remains a proportional estimate: per shared account and receipt
day, divide confirmations by the assigned bidders’ checked-link weights for that
account and confirmation date, including links sourced on earlier days. For 105 confirmations and weights 11 and 75, estimates are 13 and
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

Payment records snapshot the reviewed estimated-confirmation count, final amount, date, and reference.
The server rejects stale counts, repeat payments for the same bidder/week, and payment
recording before a week ends. Assignment changes that would affect that bidder’s paid
week are rejected. Later classifications and checked-link changes can update estimates but do not rewrite recorded payments;
the table flags any difference between the current count and paid count.

Payment cells show only **estimated / confirmed**, with the confirmed amount in blue. Without a saved manual amount or paid record, confirmation defaults to the estimate. Click the blue confirmed amount to edit it; paid rows open the recorded-payment correction form. The form starts with the recorded amount and note; **Use calculated amount** fills the current formula result. **Save changes** updates the amount, note, and application-count snapshot to the reviewed weekly total, while retaining the original payment date. Previous and new values are stored in an edit history. Concurrent edits and changed counts are rejected until the admin refreshes and reviews them. Rate changes never amend paid records automatically. There is no payment gateway or bank integration; these records describe payments made elsewhere.

The database migration runs automatically on startup. Bidder responses omit the full
account-management list, while assigned account labels remain visible in the table.

## Activity monitor and Refresh

The default **Confirmation time** graph, daily activity, hourly heatmaps, peak hour,
and last confirmation use the matching email's received timestamp, not the time
Check now or auto-check ran. Multiple valid matches use the earliest receipt in the
row's seven-day matching window. Both bidder and account views use these timestamps.
Rows checked manually without a matching confirmation have no inferred receipt time.

**Check runs** remains a separate processing-history view, showing when checks ran
and how many newly checked rows were observed. It includes every run in the selected Chicago workday. Payment
counts use the confirmation’s Chicago calendar date, even if links were given earlier. Untimed manual or legacy checks keep their sourcing date.

Admins can click **Refresh** on Bidder payments to recheck stored confirmation
messages and active sourcing rows dated today through six days earlier in Chicago.
It repairs receipt timestamps for already-checked rows, adds newly matched checks,
and refreshes payment totals, activity graphs, and open clean sourcing sheets.
Checked statuses are never cleared. This uses local saved mail; Check now collects
new mail from providers. Existing payment records are never rewritten.

Checked boxes show the confirmation's received time on hover. Old checks can acquire
historical timestamps when Refresh finds matching stored confirmations. Missing
messages do not get invented times. Both the confirmation graph and daily table use the same checked-link records and account assignments on the Chicago confirmation date. The audit ledger remains stored after row deletion, but deleted rows and rows with empty links are excluded from both views. Named bidders only see their own contributions, including on shared accounts.

Account activity counts checked document rows, which can overlap across bidders on
a shared account. Receipt times can be delayed and are not measured working hours.

The Activity Monitor distinguishes three graph views:

- **Confirmation time:** matched link arrivals in 15-minute intervals for one Chicago workday, including zero-count intervals.
- **Check runs:** every recorded processing checkpoint in that workday, including quiet checks. Hover shows exact Chicago time and source; the expandable checkpoint table shows all per-bidder or per-account counts. This daily view has no 240-run truncation.
- **By day:** calendar-day confirmation totals for the payment table's selected week.

Intraday views default to the most recent 6:00 AM in America/Chicago through the following 6:00 AM. Before 6 AM, this is the previous date's workday. A separate date selector browses other workdays without changing the payment week. Hourly axis marks use Chicago time, including daylight saving transitions. Summary cards, heatmap, and summary table remain explicitly weekly.

## Wallet details and copying a payment report

On **Accounts → Manage bidders and account assignments**, save each bidder’s payment network (for example `USDT.BEP20`) and public receiving wallet address. Saving a name does not change wallet details. A blank address clears the saved wallet. BEP20 and ERC20 addresses must have the standard `0x` plus 40 hexadecimal characters; address capitalization is preserved. Wallet fields and exports are admin-only.

For a completed week on **Bidder payments**, select **Copy weekly payment report**. It copies every bidder in that week, regardless of the bidder filter, one line per bidder:

```text
$44 -> USDT.BEP20 -> 0x6A33C5254C47DEfE820d93EAa2F4bd7ab9C378BD -> Bidder -> Dany
```

Amounts use the recorded payment if already paid; otherwise they use the saved manual amount or calculated weekly pay. If neither a rate nor manual amount is set, or wallet details are missing, nothing is copied and the page names the missing details. A selectable preview is provided for manual copying if browser clipboard access is unavailable. Recorded amounts and counts remain saved unless explicitly edited by an admin. This copies text only and never transfers money.
