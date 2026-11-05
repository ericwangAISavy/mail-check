# Bidder payments

Open **Bidder management** in the sidebar. Admins manage bidders, account assignments,
and payment records. Named bidders can view their own checked activity and, when enabled,
their own payment amounts. Admins configure payment visibility and sharing of team work
counts in **Accounts → Bidder visibility**. See [Bidder web access](BIDDER_ACCESS.md).
Bidder writes are rejected by the server.

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
   received replies are allocated per bidder using their checked links on the same
   account and day. Checked links stay with the bidder who owns the document. Overlapping
   rules for the same bidder and account are blocked.
3. Open **Bidder payments** and use the week selector or arrows to view Monday–Sunday totals in America/Chicago.
   The bidder selector narrows the table and summary to one bidder.
4. Set each bidder’s **Pay per bid (USD)** and **Adjustment (%)** on Accounts. The default adjustment is 20%, meaning a multiplier of 1.2. Weekly pay is `rate × weekly checked applications × (1 + adjustment / 100)`, rounded once to cents with decimal half-up rounding. For example, `0.05 × 309 × 1.2 = $18.54`.
5. On a completed week, **Edit / record payment** opens a prefilled amount. Edit it and choose **Save amount** to override that week without marking it paid. **Use calculated amount** removes the override. Manual amounts remain saved if counts change, with a warning to review them.
6. After making the actual payment elsewhere, choose **Record as paid** with an optional reference. Saved paid amounts do not change when rates, estimates, or adjustment percentages change. No action here transfers money.

## Daily application counts

Admins see **checked applications / received replies** in daily cells. Bidders see only their checked-application count in bidder rows, expanded account rows and totals; received-reply counts and historical review counts are omitted from their payment API response. For example,
**75 / 92** means 75 checked job-link rows and an allocated share of 92
application-received emails. Checked applications appear in bright text; received
replies appear in grey for reference. Received replies are application acknowledgements,
not every email reply, and are not a count of unique submitted jobs.

Overview cards, weekly totals, calculated payments, and new payment records use
checked applications. Weekly pay is `pay per bid × checked applications ×
(1 + adjustment / 100)`; the adjustment remains editable and defaults to 20% (×1.2).
Existing manually checked and legacy job-link rows remain included. Checked counts
are grouped by the matching reply's Chicago receipt date and require an account
assignment on that completion date. Untimed manual or legacy checks keep their
sourcing date. Each row counts once; archived sheets retain historical counts.
Received replies do not increase pay unless a sourcing row is checked.

## Verification rules

After mail collection and classification finish, scheduled auto-checks and the
top-level **Check now** job compare confirmation emails against every active account
tab. A confirmation received on day D can check rows dated D through D−6, using
Chicago calendar dates. Accounts must match. Exact normalized company/role matches take precedence; otherwise either complete normalized company phrase may contain the other, and role phrases may contain each other in either direction. This matches Inspira Financial with Inspira Financial Trust LLC, while rejecting word fragments such as Meta/Metamask, Engineer II/III and C++/C#. A company-only reply can automatically check a job only when it identifies one eligible row across the account’s active bidder tabs. One reply cannot automatically check several rows, even on different dates or bidder tabs. Ambiguous jobs remain unchecked for manual review. Pre-registered future dates are also eligible for early work: recent confirmations from the last seven Chicago dates can check future rows, with no limit on how far ahead the row is scheduled. A selected-week refresh compares that week’s receipts with future rows too. Manual
**Check applications** checks the selected date plus future rows on that account tab.

Checked rows stay checked through later checks, reclassification, and edits. A
confirmation arriving next week counts on its received date, including links given the previous week. Manually checked rows count too. The checkbox cannot be cleared, although
row deletion can affect totals. Changing a sourcing date only moves an untimed manual or legacy count; matched completions retain their confirmation date.

## Receipt allocation

The second number, received replies, remains a proportional allocation: per shared account and receipt
day, divide confirmations by the assigned bidders’ checked-link weights for that
account and confirmation date, including links sourced on earlier days. For 105 confirmations and weights 11 and 75, reply allocations are 13 and
92. Largest-remainder rounding preserves the total, with ties broken by bidder ID.
A sole assigned bidder receives the full receipt count; shared accounts with no
checks show unallocated received replies.

Calculate each account separately before summing a bidder's daily received replies. For
example, if Joseph checks 1 of account A's 4 links and 3 of account B's 4 links,
with 100 and 40 confirmations respectively, his received-replies allocation is 25 + 30 = 55.
Never combine his checked counts across accounts before calculating the shares.
These allocations affect only the grey received-replies count. Weekly application totals and new payment counts sum checked applications, without applying receipt weights.

Only the latest `application_ack` classification contributes to received replies.
Receipt dates use America/Chicago, falling back to collection time when absent.
Rechecking a message does not duplicate its account/message identity. Estimates
are not proof of submissions. New automatic matches never reuse one reply across several sourcing rows.

## History and payment integrity

A separate ledger stores account/message identities, received timestamps, and
categories and extracted company names and roles. Email bodies are not stored in the ledger. Entries survive normal
email retention cleanup and account removal. New accounts cannot reuse an accounting
account identity. Existing retained classifications populate the ledger automatically.
Emails already removed before this feature was installed cannot be recovered by it.

Payment records snapshot the reviewed checked-application count, final amount, date, and reference.
The server rejects stale counts, repeat payments for the same bidder/week, and payment
recording before a week ends. Assignment changes that would affect that bidder’s paid
week are rejected. Later classifications and checked-link changes can update current totals but do not rewrite recorded payments;
the table flags any difference between the current count and paid count.

Payment cells show only **before / after deductions**: gross calculated pay first, then net calculated pay in blue. For example, **$10.00 / $7.00** means $10 gross and $7 after daily deductions. Formula details appear only in the admin editor. This pair is independent of saved manual amounts and recorded payments. Click the blue amount on a completed week to open the payment editor; paid rows open the recorded-payment correction form. The form starts with the saved amount and note; **Use calculated amount** fills the current formula result. **Save changes** updates the amount, note, and application-count snapshot to the reviewed weekly total, while retaining the original payment date. Previous and new values are stored in an edit history. Concurrent edits and changed counts are rejected until the admin refreshes and reviews them. Rate changes never amend paid records automatically. Reports continue to use the saved paid or manual amount when one exists. There is no payment gateway or bank integration; these records describe payments made elsewhere.

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
messages and active sourcing rows, including pre-registered future rows.
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

- **Confirmation time:** matched link arrivals in 15-minute intervals for one Chicago calendar day, including zero-count intervals.
- **Check runs:** every recorded processing checkpoint in that calendar day, including quiet checks. Hover shows exact Chicago time and source; the expandable checkpoint table shows all per-bidder or per-account counts. This daily view has no 240-run truncation.
- **By day:** calendar-day confirmation totals for the payment table's selected week.

Intraday views use midnight to the following midnight in America/Chicago, matching the daily breakdown's calendar dates. The default is today's Chicago date, including before 6 AM. A separate date selector browses other calendar days without changing the payment week. Hourly axis marks use Chicago time, including daylight saving transitions. The heatmap remains explicitly weekly.

## Wallet details and copying a payment report

On **Accounts → Manage bidders and account assignments**, save each bidder’s payment network (for example `USDT.BEP20`) and public receiving wallet address. Saving a name does not change wallet details. A blank address clears the saved wallet. BEP20 and ERC20 addresses must have the standard `0x` plus 40 hexadecimal characters; address capitalization is preserved. Wallet fields and exports are admin-only.

For a completed week on **Bidder payments**, select **Copy weekly payment report**. It copies every bidder in that week, regardless of the bidder filter, one line per bidder:

```text
$44 -> USDT.BEP20 -> `0x6A33C5254C47DEfE820d93EAa2F4bd7ab9C378BD` -> Bidder -> Dany
================================================================================
Total: $44
```

Amounts use the recorded payment if already paid; otherwise they use the saved manual amount or calculated weekly pay. If neither a rate nor manual amount is set, or wallet details are missing, nothing is copied and the page names the missing details. A selectable preview is provided for manual copying if browser clipboard access is unavailable. Recorded amounts and counts remain saved unless explicitly edited by an admin. This copies text only and never transfers money.

Activity line charts offer **Per interval** (the original counts) and
**Cumulative** (the default running totals). In cumulative mode, confirmation-time and check-run modes
accumulate within the selected midnight–midnight Chicago calendar day; By day accumulates across
the selected week. Quiet intervals stay flat, and each series' final point shows
its period total. Dots appear only when a series changes value, keeping flat
sections clear. Bidder and account series accumulate independently. Heatmap cells
and the check-run detail table retain their original interval counts.


### Missing calculated amounts

A bidder with application counts but no saved pay-per-bid rate has an unavailable
calculated payment, rather than a zero-dollar payment. The Payment column now
shows **Rate not set** and an admin **Set rate** action directly on Bidder
management. Enter the agreed rate and adjustment; this is available during the
current week as well as completed weeks. Saving refreshes calculated/payable
amounts immediately. Recorded payments and saved manual overrides are preserved.
Bidder viewers see an explanation to contact their admin and cannot edit rates.
No rate is inferred from another bidder or from the input placeholder.

## Reviewed counts and performance

Recorded payments and manual overrides keep their saved amounts when the current checked count differs. The payment table shows the saved review count and current checked total so admins can explicitly review a correction. Zero-dollar settlements are accepted, including an agreed zero rate. Removing a bidder excludes their checks from current report totals and shared-account reply weights without deleting payment history.

Auto-checks, scheduled checks, manual **Check applications**, and ordinary refresh preserve existing checkmarks and their saved receipt bindings and confirmation dates. Matching rule or receipt-classification changes do not re-evaluate already checked rows. **Fully rebuild this week** checks only unchecked links using the broader company/role matching rules. It preserves all existing checkmarks, receipt bindings and confirmation dates, including manual, automatic and archived checks. It cannot move a bound receipt to another job. Recorded payments remain saved. No automatic bulk rebuild runs during an upgrade. Repeated unchanged report/refresh requests avoid rewriting receipt and matching records.

## Daily minimum and deductions

Admins can save one **Daily deduction rule** above the daily breakdown. Enter the
minimum checked applications per day and the flat deduction in USD. Saving or
editing the rule immediately recalculates the displayed calculated payments for
all bidders in this workspace. A zero minimum disables it.

A day qualifies only when it is a completed Monday–Friday in America/Chicago and
the bidder had at least one active account assignment. Today, future days,
weekends and days without an assignment are excluded. Checked counts strictly
below the minimum appear in the danger color with a tooltip. An exact minimum
passes; zero checked applications on an eligible day still incurs one deduction.
Multiple assigned accounts never multiply the daily fee.

The calculated payment is `max(0, rounded weekly gross − total daily deductions)`.
The existing adjustment applies to gross pay before the flat deductions. The
table shows gross / net, with deduction details in the admin editor. A zero-dollar deduction can still display
the below-minimum warning without reducing pay. Saved manual amounts and recorded
payments retain their precedence and do not change automatically; administrators
can explicitly review and edit them. Bidder viewers cannot change the rule.

Rule drafts survive background refreshes. If another tab saves a different rule,
review it using **Load saved rule** before saving your edits. The console submits
the saved rule it reviewed; the server rejects a conflicting edit.

Open payment forms also capture the rule and calculated amount reviewed on opening.
If either changes, close and reopen the form before saving. This includes daily
count changes that alter deductions while leaving the weekly total unchanged.
The current console's payment writes are checked inside the server transaction,
so an unnoticed refresh cannot record a stale calculated amount.

The header's **today** badge uses checked applications for the current Chicago day,
matching the first number in the daily breakdown's workspace total. Received replies
remain the second number in the admin table and do not drive the badge.
