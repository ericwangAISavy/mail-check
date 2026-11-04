# Application confirmations and job-link reconciliation

The daily ratio shows **counted receipts / checked job links**. Estimates remain
receipt-based: they exclude only proven platform copies, rather than switching to
verified-job payments. Two acknowledgements for one application remain visible as
two raw receipts, but a confirmed platform copy makes the counted ratio 1 / 1.
Fetching the same account/message ID repeatedly still counts one raw email.

In Bidder management, choose the week and use **Refresh this week**, then open
**Application reconciliation → Account review details**. The report now separates:

- **Raw receipt emails:** saved messages classified as application received. These
  preserve the full acknowledgement evidence, including confirmed copies.
- **Counted confirmation receipts:** raw receipts minus confirmed platform copies;
  these drive daily estimates, account allocations and future calculated amounts.
- **Confirmed platform copies:** platform acknowledgements proven to copy one
  employer acknowledgement for the same application. Both emails stay classified
  as application received and remain available for review.
- **Verified applications:** checked job rows with one receipt claim and a unique
  account/job URL. Daily verified counts appear below the counted-receipt ratio.
- **Possible extra confirmations:** unclaimed messages whose full company/title
  metadata matches a verified receipt. They may be duplicates, but remain intact.
- **Unmatched receipts:** messages without a reliable verified link, including
  ambiguous claims. They may be legitimate applications and are never discarded.

The raw count equals verified receipts + confirmed platform copies + possible extras + unmatched receipts. Counted receipts equal raw receipts minus confirmed platform copies.
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
Matching company/title alone never removes a receipt from estimates. A copy needs
one platform and one employer acknowledgement in the same account and Chicago
receipt day, identical conservative full company/title metadata, and exactly one
matching checked job row claiming a member of that pair. Multiple candidate jobs,
multiple employer messages, conflicting explicit application references, missing
origin/metadata and cross-day pairs remain counted. A sole platform receipt remains
counted too.

Repeated canonical job URLs and existing receipt claims shared between rows are
flagged, including earlier checked history. Meaningful URL query IDs (including
`jr_id`) remain distinct; ordinary tracking parameters do not create a new job.
A legitimate reapplication to the same URL may need review. Raw receipts and their
counted allocation are retained while that uncertainty exists.

Other reasons include absent receipt metadata, manually checked rows without linked
receipts, changed company/title metadata, receipt-date disagreement, and assignment
boundaries. Safe Sr./Senior and Jr./Junior title prefixes now match; broad fuzzy
matching is not used. Review reasons can overlap.

Review the account's actual receipt messages and the corresponding sourcing rows
before concluding that anything is duplicated. Incorrect historical classification
can inflate raw receipts; this change does not reclassify old email automatically.
Verification uses saved metadata/link evidence, not a live ATS application ledger.

## Preservation and rollback

Existing affected weeks can be corrected locally: select the week in Bidder
management and choose **Refresh this week**. The correction uses saved messages
and checked-job claims without historical LLM reclassification or mailbox writes.
Unknown pairs remain counted for review. Original emails and raw acknowledgement
rows are preserved; recorded paid amounts and payment-edit history are never
automatically overwritten when estimates change. An admin can explicitly edit a
saved payment after reviewing the current count.

Ordinary refresh preserves existing checked state. **Fully rebuild this week**
can still clear stale automatic checks; it is a separate explicit action.

The receipt ledger schema gains additive sender, duplicate-of and copy-evidence
columns. Proven copy evidence survives source-message retention and is validated
against current receipt evidence, so a changed or missing primary receipt cannot
leave an orphan copy excluded. Read-only viewers compute the same counted result
without writing to the ledger.

The pre-change baseline is tagged `rollback/platform-counting-before-2.13.6`.
Previous code can ignore the additive columns. Code rollback restores the previous
counting behavior; it does not delete emails, rewrite saved payments or undo checks
made after deployment. No real on-premises data was inspected or changed during
development.

Synthetic validation includes a platform/employer pair with two raw receipt emails,
one counted receipt and one confirmed platform copy. Saved paid amounts remain
unchanged. Test records do not establish the composition of your mailbox.
