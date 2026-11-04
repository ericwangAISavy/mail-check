# Application confirmations and job-link reconciliation

The original ratio counts **receipt emails / checked job links**. Two emails for
one application can produce 2 / 1; fetching the same account/message ID repeatedly
still counts one email. These numbers are not two measurements of unique applications.

In Bidder management, choose the week and use **Refresh this week**, then open
**Application reconciliation → Account review details**. The report now separates:

- **Raw receipt emails:** saved messages classified as application received. These
  remain the basis for existing payment estimates, as requested.
- **Verified applications:** checked job rows with one receipt claim and a unique
  account/job URL. Daily verified counts appear below the original ratio.
- **Possible extra confirmations:** unclaimed messages whose full company/title
  metadata matches a verified receipt. They may be duplicates, but remain intact.
- **Unmatched receipts:** messages without a reliable verified link, including
  ambiguous claims. They may be legitimate applications and are never discarded.

The raw count equals verified receipts + possible extras + unmatched receipts.
Summary figures cover workspace receipts, including unassigned accounts; payment
allocations cover assigned accounts. Shared-account review counts describe the
entire account and must not be interpreted as a single bidder's allocated count.
Filtering to a bidder shows associated accounts and their verified job-row totals.
Account labels stay masked in the interface.

## Why a row needs review

One email cannot newly check multiple candidate jobs, including jobs in another
bidder's tab or an archived sheet included in a weekly refresh. Multiple candidate
jobs with indistinguishable metadata remain unchecked for review, even when two
emails arrived: they could describe two applications or two notifications for one.
No new company/title-only duplicate merging is performed.

Repeated canonical job URLs and existing receipt claims shared between rows are
flagged, including earlier checked history. Meaningful URL query IDs (including
`jr_id`) remain distinct; ordinary tracking parameters do not create a new job.
A legitimate reapplication to the same URL may need review. Raw receipts and their
payment allocation are retained while that uncertainty exists.

Other reasons include absent receipt metadata, manually checked rows without linked
receipts, changed company/title metadata, receipt-date disagreement, and assignment
boundaries. Safe Sr./Senior and Jr./Junior title prefixes now match; broad fuzzy
matching is not used. Review reasons can overlap.

Review the account's actual receipt messages and the corresponding sourcing rows
before concluding that anything is duplicated. Incorrect historical classification
can inflate raw receipts; this change does not reclassify old email automatically.
Verification uses saved metadata/link evidence, not a live ATS application ledger.

## Preservation and rollback

Original emails, raw receipt rows and recorded payments are not deleted, merged or
rewritten by reconciliation. Existing checked state is preserved during ordinary
refresh. The existing **Fully rebuild this week** action can still clear automatic
checks that no longer match; it is a separate explicit action.

This release changes no database schema. Baseline code is tagged
`rollback/reconciliation-before-2.13.5`. Revert the single reconciliation commit to
restore prior behavior; code rollback does not undo checks made after deployment.
No real on-premises data was inspected or changed during development.

Synthetic validation includes a 165-email example with 81 verified applications,
81 possible extra confirmations and 3 unmatched receipts. Its receipt-based $9.90
estimate stays unchanged. These are test records, not findings from your mailbox.
