# Application Reconciliation Implementation Plan

> For agentic workers: use superpowers:executing-plans for integration and focused
> parallel workers only on the independent files named below.

Goal: explain and reconcile raw receipt/checked-row discrepancies without destroying
mail evidence or recorded financial history.
Spec: docs/superpowers/specs/2026-11-04-application-reconciliation-design.md
Architecture: read-only reconciliation module, conservative verification guard,
existing report integration, explicit frontend diagnostics. Python/SQLite/React.
Global constraints: no real mailbox/database mutations; recorded payments unchanged;
no company/title-only automatic deduplication; preserve scope and Chicago dates.
Review focus: same receipt reused across tabs/bidders, historical conflicting claims,
shared-account allocations, malformed metadata, duplicate URLs and privacy.

- [x] Reconciliation module: mailcheck/application_reconciliation.py, reconcile(conn,start,end,*,bidder_id=None).
- [x] Verification guard: mailcheck/receipt_assignment.py plus sourcing_verification.py; fail-first tests for broadcast prevention/title aliases.
- [x] Report integration: payments.report adds reconciliation and per-bidder verified_daily/verified_total; raw financial fields preserved.
- [x] UI: raw receipt/checked labels and reconciliation summary + per-account review; existing account masking.
- [x] Full tests, fresh review, patch release/build, single commit/push and rollback tag.

Reconciliation interface: raw_receipts, verified_applications, possible_extra_confirmations,
unmatched_receipts, ambiguous_rows, duplicate_connection_groups; accounts[{account_id,
account_label,bidder_ids,raw_receipts,verified_applications,possible_extra_confirmations,
unmatched_receipts,ambiguous_rows,missing_metadata_receipts,duplicate_link_rows,
conflicting_receipt_rows}]; bidders{id:{verified_daily:[7],verified_total}} (private
mapping used by payments.report, omitted from public reconciliation object).

Ledger: baseline d18514b; user explicitly chose receipt-based payment estimates; preserve basis.

Ruling: payment policy is unchanged per explicit user reply; verified counts are
separate. Extra/missing emails remain evidence, not forced duplicate deductions.
Ruling: repeated URLs across historical checked rows require review too. Legitimate
reapplications can be flagged; no raw count/payment is reduced by that uncertainty.
Ruling: old explicit unique claims survive metadata disagreement, while timestamp
calendar-day disagreements require review rather than shifting old completion dates.

Review: fresh independent reviewer reproduced archived-row receipt broadcasting
and historical URL conflict gaps. Both fixed with fail-first SQLite regressions.
Candidate IDs are materialized before cell joins, candidate sets cached perreceipt,
and lookup parameters batched to avoid unbounded statement sizes. No schema change.
Two older multi-tab fixture tests relied on receipt broadcasting; their independent
normalization/coverage cases now use distinct receipts/companies, while new tests
assert broadcasting is forbidden. No prior user data or recorded payments changed.

Final verification: 684 backend tests +84 subtests and339 frontend tests passed.
Production build and release consistency checks passed. Desktop1440/mobile390
Chromium exercise used the synthetic actual SQLite report:165raw,81verified,
81possibleextras,3unmatched; dailycount81, accountmasking andbidderfilter passed;
receipt-based payment remained$9.90. No real on-prem database inspected.
The browser exposed a misleading no-review-reasons fallback for accounts with
extras/unmatched only; added explicit reasoncounts and a fail-first frontend test.
Rebuilt/retestedfrontend. Existing Starlette deprecation andVite chunksize notices
remain nonblocking. No minor findings deferred. Rollbacktag preserved baseline.
