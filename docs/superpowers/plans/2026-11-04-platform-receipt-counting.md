# Platform Receipt Counting Implementation Plan

> For agentic workers: use superpowers:executing-plans for integration with focused
> independent workers for the new counting module/tests and frontend only.

Goal: prevent the classifier's wider receipt intake inflating application estimates.
Spec: docs/superpowers/specs/2026-11-04-platform-receipt-counting-design.md
Architecture: additive receipt origin/copy evidence, conservative receipt_counting
module, shared effective counts at all report/header consumers, preserved raw evidence.
Stack: Python/SQLite/FastAPI/React.
Constraints: no noise relabelling of real receipts, no blanket metadata-only merging,
recorded payment immutability, Chicago days, tenant/bidder/read-only boundaries.
Review focus: platform-only mail, two actual jobs same title, missing sender/role,
cross-day copies, reclassification/parent loss, retained proofs after message pruning,
shared accounts, stale checked source and payment history.

- [x] Fail-first migration/count tests; receipt schema sender,duplicate_of,counting_evidence.
- [x] Independent receipt_counting module and synthetic tests.
- [x] Origin backfill and effective counts in payments, badge and reconciliation;
      materialize at end of verification/report, preserve query-only readers.
- [x] UI distinguish raw receipts/counted receipts/confirmed copies; basis wording.
- [x] Whole-branch review, full suites, release/build/browser.
- [x] Prepare reviewed release commit and rollback tag for atomic push.

Interface: receipt_counting.effective_receipts(conn,start:date,end:date,*,account_id=None)
returns list[dict] raw ACK rows with effective duplicate_of and counting_evidence.
receipt_counting.materialize(conn,start:date,end:date,*,account_id=None)->int writes
only changed duplicate_of/evidence for ledger rows, including resetting stale flags.
receipt_counting.application_reference(text)->str|None conservative explicit label parser.
Schema columns: sender TEXT NOT NULL DEFAULT '', duplicate_of TEXT,
counting_evidence TEXT NOT NULL DEFAULT ''. No other agent edits schema/consumers.

Ledger: baseline19487ed; new policy corrects eligible receipt count only.

Verification: 712 backend tests and 104 subtests passed; 340 frontend tests passed.
Production build, release consistency and whitespace checks passed. Desktop1440px
and mobile390px browser checks verified counts, masking, filtering, corrected
estimates and no page overflow. Synthetic 162 raw ACKs yield 81 eligible receipts
for 81 checked jobs; all emails and recorded payments remain preserved.
Independent review findings fixed: persisted proof must revalidate live source
changes/added candidates; explicit alphabetic application references must prevent
merging conflicting applications. Both covered by passing regression tests.
No production mailbox or on-prem database was inspected or modified.
Rollback tag: rollback/platform-counting-before-2.13.6 at baseline19487ed.
