# Investigating falling application counts

In v2.21.3, viewing an admin payment report ran verification. Verification could
attach or replace receipt timestamps on already checked rows. Payment accounting
uses the receipt's Chicago date when present, and requires an assignment on that
date. Therefore a saved check could move days or disappear from eligible totals
without its checkbox being cleared. A full rebuild could also clear automatic
checks whose receipts no longer matched. These are different failure modes;
reverting matcher code does not restore overwritten records.

From v2.21.4, payment reports are read-only. Ordinary checks and refreshes add new
matches without changing already checked rows or their saved receipt proofs. The
public full rebuild action is disabled, including direct API requests. Explicit
manual row edits still work. Internal rebuild code remains for tested, deliberate
offline repair; do not run it to recover counts without examining the records.

On the server, run the audit against the affected workspace's database:

```sh
python tools/audit_application_counts.py --database /actual/path/mail.db --week 2026-11-02 --output check-audit.json
```

Use the Python interpreter from your installation (or run inside its application
container). This opens SQLite in read-only mode, without application startup,
migrations, receipt syncing, or verification. It exports bidder/account identifiers
and dates, but no message bodies, job URLs, credentials, or receipt identifiers.

The report shows current eligible daily totals, differing source/confirmation
dates, missing assignments, rebuild-cleared checks, and retained activity for
missing source rows. Recent activity samples are **all-date totals**, not weekly
payment totals. They must not be used as weekly replacement counts.

Review the output before applying a recovery. Saved receipts can supply new
matches, but rechecking cannot guarantee reconstruction of deleted rows or
previously overwritten timestamps. Screenshots alone cannot establish which
individual applications should be restored. This release contains the automatic
writes; it does not retroactively restore production records or freeze payments.
