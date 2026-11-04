# Checked-application accounting review

Baseline: fd8734f (2.17.0). Scope: payment amounts and reviewed counts, saved records,
admin/viewer boundaries, receipt matching, shared-account allocation, time filters,
repeated report/refresh writes, query plans and upgrade compatibility.

## Confirmed issues corrected

- A company-only receipt could check several roles, dates or bidder tabs. Matching
  now requires a unique eligible job and respects existing receipt bindings.
  Manual and automatic checks share the same account-wide candidate policy.
- First-word company matching and truncated role keys merged unrelated employers,
  levels and C++/C# roles. Normalization now retains meaningful identity, with
  limited legal-suffix, initialism, seniority-abbreviation and location aliases.
- Removed bidders' manual checks still entered shared-account receipt weights.
  Both matched and untimed checked totals now exclude removed bidders.
- Saved payment/manual override counts could differ from the new checked count
  without explanation. The table now shows that difference without rewriting money.
- Zero rates were allowed but zero settlements were rejected. Recording and editing
  zero-dollar settlements now use the same nonnegative amount policy as the UI.
- Triage date filters compared timestamp strings rather than instants. Mixed UTC
  offsets now use SQLite's indexed Julian-date comparisons.
- Malformed legacy confirmation timestamps could crash a selected-week refresh or
  drop a checked link from accounting. Refresh handles malformed timestamps and
  untimed checked rows retain their sourcing-date fallback.

## Performance changes

Payment and reply counts are grouped in SQLite using explicit Chicago-day UTC
boundaries (including DST), instead of loading individual events and repeatedly
walking assignments in Python. Scoped receipt synchronization bounds source and
previous receipt dates before joining classifications. Unchanged ledger and match
metadata updates are suppressed. A report following a refresh does not synchronize
the same receipt set twice. Payment writes construct only the target bidder's
report while retaining all competitors' reply weights.

Additive schema version 40 adds indexes for confirmation-date expressions, source
row dates and receipt reservation lookup. Matching candidates are indexed by
account/company/role/date, and reservation reads batch only relevant message IDs.
No email, checked status, amount, credential or historical payment is rewritten by
these index changes. Ordinary refresh retains existing checks; removing stale
checks remains an explicit selected-week rebuild action.

## Synthetic measurements

Run from the repository root with the development virtual environment:

```sh
.venv/bin/python tools/benchmark_payments.py --baseline fd8734f --rows 12000 --rounds 5
.venv/bin/python tools/benchmark_payments.py --baseline fd8734f --rows 60000 --rounds 3
```

The benchmark creates disposable data, compares payment/checked/reply totals, and
requires unchanged reports and warmed weekly refreshes to write zero rows.
Baseline and current report measurements use the same database and indexes;
baseline code is loaded from local Git history, never a live workspace.

| Synthetic rows over 90 days | Baseline report median | Current report median | Speedup | Unchanged report writes, before / after |
| --- | --- | --- | --- | --- |
| 12,000 | 20.40 ms | 7.36 ms | 2.77× | 402 / 0 |
| 60,000 | 101.15 ms | 44.13 ms | 2.29× | 2,001 / 0 |

At 60,000 rows, a warmed unchanged selected-week refresh took a median 341.80 ms
and wrote zero rows. These are synthetic local measurements, not production
latency or model-accuracy claims. The benchmark also does not include HTTP,
rendering or network costs.

## Regression coverage and operational limits

Tests cover ambiguous company-only mail, cross-bidder competition, reservation
reuse, stale automatic-binding rebuilds, no-op refresh writes, removed bidders,
zero payments, saved-record preservation, single-day/DST boundaries, timestamp
offsets, concurrent migration and expression-index selection.

Existing permissively checked rows are intentionally preserved on ordinary reads
and refreshes. Review an explicit selected-week rebuild before changing historical
automatic checks. Live mailbox classification quality and the deployed server's
exact data have not been measured or modified in this review.

## Final validation

The full backend run passed 674 tests and 84 subtests. Its one remaining failure
was the historical-schema fixture dropping a column without first removing the
new index; the fixture was corrected and that test plus all migration checks
passed. Final matching/migration checks passed 42 tests and 13 subtests. All 342
frontend tests, the TypeScript/Vite production build, release-history consistency
and whitespace checks passed. No production mailbox or application database was
used for this work.
