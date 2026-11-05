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

## Restore specific rebuild-cleared rows (v2.21.5)

`tools/recover_application_checks.py` targets only row IDs listed as
`previous_automatic_check_cleared_by_rebuild` in the supplied audit. It does not
rerun email matching or restore deleted rows. Preview first against the same
workspace database used for the audit:

```sh
python tools/recover_application_checks.py --database /actual/path/mail.db --audit check-audit.json
```

For the November 2 incident audit, expect 332 candidates, minus any already
checked rows. Review the per-bidder and per-date breakdown. A conflict aborts
the entire recovery, without changing any rows.

Original receipt dates are unavailable for these rows. Applying this recovery
credits each restored check to its **saved sourcing date**. This is an explicit
administrative restoration of historical credit, not newly verified email proof.
Daily deduction amounts and calculated payments may change. It does not recreate
the exact original daily allocation or rewrite saved payment records or overrides.

After reviewing the preview, stop the app and all mail/scheduler/workspace
workers. Use the same installation config file that the running app uses for
its maintenance lock (the shared/legacy installation config when configured):

```sh
python tools/recover_application_checks.py --database /actual/path/mail.db --audit check-audit.json --config /actual/path/config.toml --apply --use-source-dates
```

Apply takes an exclusive installation maintenance lock and a database write
transaction, revalidates every target, and commits all changes together. It
requires unchanged bidder/account/date identity, an existing nonempty job link,
a current bidder, an assignment on the sourcing date, and rebuild-cleared
provenance without a receipt binding. Already checked targets are left unchanged.
Restored activity is marked `recovered-rebuild`; no confirmation timestamp or
receipt identity is invented. Sheet revisions and changed cell versions advance
so clients reload the checked state. Rerunning safely skips restored checks.

Restart on v2.21.4 or later, then run the read-only audit again and review the
week's daily counts and payment deductions. Do not start an older version or run
an internal destructive rebuild after restoring these checks.
