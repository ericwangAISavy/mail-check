# Classifier Rollback Implementation Plan

Goal: remove reconciliation and restore original classification with historical relogging.
Spec: docs/superpowers/specs/2026-11-04-classifier-rollback-design.md
Architecture: targeted classifier restoration, original receipt-based accounting,
admin background history actions using the existing pipeline and logs.
Tech: Python/SQLite/FastAPI/React.

- [x] Fail-first tests for original board policy, >200 stored messages, week bounds,
  repeated runs and recorded-payment preservation; restore classifier behavior.
- [x] Disconnect and remove reconciliation modules/panel and copy deductions;
  retain additive schema compatibility and one-to-one sourcing correctness.
- [x] History endpoint and UI, selected-week/all scopes, run logs, no mailbox calls.
- [x] Review null-date bounds and prevent unscoped verification after history jobs.
- [x] Verify full suites, release consistency and production build.
- [x] Prepare reviewed commit and rollback tag for atomic push.

Review focus: null message dates/fetched-time fallback; >200 histories; Chicago
week/DST bounds; repeated runs/receipt uniqueness; saved payments/manual checks;
bidder write restrictions; removed-by-retention mail cannot be rerun locally.

Verification: 685 backend tests/84 subtests and 343 frontend tests passed.
Release consistency, whitespace and production build passed. Desktop1440px and
mobile390px browser tests verified both action scopes, no reconciliation panel
and no page-wide overflow. The mobile check first failed on header overflow;
wrapping the action group corrected it. Existing model/network deprecation and
bundle-size warnings remain nonblocking. No live mailbox or on-prem database
was accessed or reclassified during development.

Independent review found and tests fixed null-date/fetched-time rebuild bounds
and unintended unscoped verification after a selected-week history run. Explicit
history now uses configured batching instead of single-message failure retries.
Retained tests cover original parsing/normalization behavior and cache semantics.
Module removal was narrowed and dependency-checked after safety review rejected a
broad rollback; later security and one-to-one sourcing fixes remain intact.

## Follow-up review

Model failures during an explicit history run could replace valid receipt labels
with unclassified placeholders and lower estimates. Fail-first tests reproduced
this; the pipeline now keeps the prior valid classification and ledger entry,
records the failed attempt as a run error, and avoids interview processing for
that failed item. Ordinary unclassified-email retry behavior is unchanged.
Preflight now omits email bodies, avoiding a redundant full-body read before the
worker loads classification inputs. A regression test checks both projections.
Read-only independent review found no regression in the changed paths.
Verification for follow-up2.14.1: 687 backend tests/84 subtests, 343 frontend
tests, release consistency, whitespace and production build passed. No production
mailbox or database was accessed. Existing dependency and bundle-size warnings
remain nonblocking.
