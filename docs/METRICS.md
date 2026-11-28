# OfferPath dashboard metrics

This is the specification for every number and graph on the Dashboard. The implementation is `mailcheck/dashboard_metrics.py`, served read-only at `GET /api/dashboard/metrics`. Tests are in `tests/test_dashboard_metrics.py`. A change to a definition must update the code, this file and the tests together.

## Principles

- **Records only.** A value that cannot be derived from stored records is `null`: it is drawn as a gap or shown as **N/A** with the reason. Missing history is never shown as zero.
- **One definition.** Metrics are computed only in the metrics layer, which reuses existing logic: confirmation de-duplication (`confirmation_counts.applications`), outcome matching (`profile_outcomes.match`), the Interview calendar's event list (`interviews.list_events`), checked applications (`completed_account_counts`), the sourcing lifecycle (`native_sourcing`) and payments (`payments.report`).
- **Time.** America/Chicago days; weeks run Monday to Sunday; boundaries are DST-safe.
- **Read-only.** The endpoint never writes.

## Controls

- **Account** limits every section to one mail profile, except payments, which are per bidder.
- **Bidder** limits profiles to the accounts assigned to that bidder on each record's date, and limits sourcing work and payments to that bidder.
- **Graph range** (4, 8 default, 12 weeks, or custom up to a year, expanded to whole weeks) applies to the analytics graphs only. The two weekly summaries always describe the current week.
- **Bidder sign-ins** see only their own scope. Account-connectivity and unclassified-mail items are admin-only.

## Weekly summaries

### Applications this week

- Distinct confirmed applications (`application_receipts`, category `application_ack`, de-duplicated by account, company, role and job reference), from Monday to now.
- **Comparison:** against last week up to the same weekday and local time. Shown as the absolute change and the percentage; the percentage is omitted when the previous count is 0.
- **Last week:** the full previous week.

### Interviews this week

- Events on the Interview calendar whose **scheduled start** falls in the current Monday–Sunday week, including upcoming ones. The calendar's rules apply: enabled accounts only; removed, hidden and duplicate copies excluded. Cancelled events are excluded.
- Each calendar event counts once, so separate interview rounds count separately and a reschedule moves an event without adding one. An event shared by several profiles counts once in the total.
- **Started so far:** events that have started by now.
- **Comparison:** this week's scheduled total against last week's full total.
- The calendar's *Work week* view hides weekends, and the calendar can display another time zone; the dashboard always uses the full Chicago week.

### Weekly average and trend

- **Average:** total over the previous four completed weeks divided by the number of those weeks that have history. Weeks with zero activity are included; weeks before history began are not. The label states how many weeks were used.
- History starts at the first recorded application (for interviews: the earlier of the first application and the first calendar event) in scope.
- The small trend line shows the last 8 weeks; the current week is dashed.

## Profile quality graph

One line per account in scope, per week, colored with the account's Interview calendar color (accounts sharing a color are shaded apart). A line starts when the account has records. The current week is dashed.

| Metric | Definition |
|---|---|
| Interviews | Calendar events (rules above) by scheduled week. |
| Applications | Distinct confirmed applications by confirmation week. |
| Rejections | Unique rejections by the week the email arrived: the first rejection matched to an application, plus unmatched rejection emails de-duplicated by account, company, role and job reference. Emails naming no company count individually. Expired links and unanswered applications are never rejections. |
| Interview conversion | Applications of that week with an invitation matched within 14 days ÷ eligible applications of that week. |
| Rejection rate | Applications of that week rejected within 14 days ÷ the same cohort. An application can count in both rates. A low rejection rate does not by itself mean a better profile. |

### When the rates are shown

1. **Reply history.** Interview and rejection emails are recorded only from the first stored message or reply receipt. Applications before that date are not eligible, and rejections before it are unknown.
2. **Follow-up.** An application is eligible once it is at least 15 days old.
3. **Attribution gate.** A rate is shown only if at least **80 %** of that outcome's emails (since reply history began, in scope) match exactly one application on the same account and company (with role and job reference when known, within 180 days). Otherwise the metric is **N/A** and shows the matched and total counts.

Calendar events cannot be traced to the application they came from, so interview conversion relies on invitation emails.

**Audit, 27 November 2026.** The earlier dashboard showed 0.4 % (14 of 3,759). Reply emails were recorded only from 10 November while applications went back to 10 October, so most "eligible" applications could never have a recorded reply; recent applications were excluded by the 14-day window; and only about 38 % of invitation emails (89 of 235) and 58 % of rejection emails (673 of 1,164) matched one application. The rate was not reliable.

## Bidder productivity graph

One line per active bidder, per day or week, from links on current sourcing sheets.

- **Availability.** A link is available to a bidder while it is open (from creation until completion or the 7-day expiry) **and** the bidder is assigned to its account.
- **Available** = opening backlog + newly available links in the period, each counted once.
- **Completed** = links of that population completed in the period. Completion time is the matched confirmation time, otherwise the start of the sourcing day (the payments rule). Opening a link is not completion. A confirmation arriving after the 7 days still completes the link.
- **Completion rate** = completed ÷ available; never above 100 %; blank when nothing was available.
- **Checked** = credited applications, exactly as counted by Bidder management and payments (`completed_account_counts`). It can differ slightly from *Completed*.
- **Expired** = available links that reached 7 days unchecked in the period.
- **Remaining** = available links still open at the end of the period (a point-in-time stock, not an inflow).

## Workload graph

- **New links:** links that became available in the period. **Checked:** credited applications. **Backlog** (optional): links open at the end of the period. **Expired** (optional).
- Checked can exceed new links when earlier backlog is completed.

## Payments

The current payment week from `payments.report`, to the cent: gross, deductions, net payable (recorded payment, else manual override, else gross − deductions) and recorded. **Outstanding** appears only once the week has ended and every bidder with work has a pay rate.

## Needs attention

Only items with a count above zero, each linking to its page.

| Item | Definition |
|---|---|
| Unconfirmed links | Checked in the last 30 days, more than 24 hours ago, with no matched confirmation. |
| Expiring within 48 hours | Open links reaching the 7-day limit. |
| Carried-over links | Open, unexpired links created before today. |
| Bidders below the daily minimum | Weekdays only, when the deduction policy sets a minimum and an assigned bidder has fewer links available today. |
| Accounts with sync failures | Enabled accounts whose real-time sync last failed (admins). |
| Unclassified messages | Open, unclassified messages from the last 30 days (admins). |

## Known limitations

- **Removed or moved links** are deleted without history, so past workload covers only links still on current sheets.
- **Older creation and check times.** Links that predate the work queue were stamped at the start of their sourcing day, and checks without a recorded confirmation are dated to that day. Early history is therefore approximate. Periods before the first link are blank.
- **Reassignment** follows dated assignments; administrative removal of rows cannot be reconstructed.
- **Interviews follow the calendar.** An interview never added to the calendar is not counted.
- **Unmatched rejections** can still count twice when emails about one application name the company or role differently.
