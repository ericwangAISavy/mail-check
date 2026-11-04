# Fix the classifier-release receipt counting regression

User authorized fixing the demonstrated regression after reviewing the before/after
path: newly admitted platform acknowledgements and employer acknowledgements can
both count for one job. Keep both emails classified/visible, preserve interview
recall and recorded payments, and correct estimated receipt eligibility.

Approach: separate raw acknowledgement evidence from counted acknowledgement
receipts. Suppress a known platform copy only with one employer primary, the same
account and Chicago receipt date, identical conservative full company/title metadata,
and exactly one matching checked job row claiming a member of that pair. Multiple
candidate jobs, missing origin/metadata, different explicit application references,
multiple primary employer messages or cross-day pairs stay counted for review.
A sole platform confirmation remains counted. Never divide counts by two, blindly
merge company/title matches, or return genuine receipts to the noise category.

Persist sender and a reversible duplicate_of/evidence snapshot on the existing
receipt ledger using additive columns. Validate saved pairs against current receipt
categories/origins/metadata; reclassification cannot leave an orphan excluded copy.
Persisted proven pairs survive email retention and do not depend on deleting mail.
Read-only viewers compute the same effective result without writing.

Daily badge, estimates, account allocation and future amount calculations use the
same effective receipt predicate. Raw reconciliation counts remain unchanged, with
counted receipts and confirmed platform copies shown separately. Saved payments and
payment-edit history never change automatically. Current receipt-based policy is
retained: this is duplicate receipt correction, not a switch to verified-job payments.

Existing affected weeks can be repaired locally with Refresh this week, using stored
messages and job claims; no historical LLM reclassification or actual mailbox writes.
Unknown evidence is retained for review. This remains an evidence-based fix, not a
claim that the synthetic source pair proves the composition of the user's mailbox.

Rollback tag before edits: rollback/platform-counting-before-2.13.6. Additive columns
are safe for previous code to ignore; code revert restores old counting behavior,
not emails/payments. No live host/database accessed during development.
