# Multi-admin Performance Optimization Plan

**Goal:** Reduce gateway and page-loading overhead without changing data, schema, status, session validation, scheduling, LLM concurrency, or business calculations.

**Measured baseline:** Disposable loopback worker, 60 authenticated requests: median 13.46 ms, p95 17.87 ms, 60 TCP connections. Disposable weekly reconciliation with 20,000 rows/receipts: warm median 154.26 ms; only 520 candidate rows actually belong to its window.

## Work
- [x] Test then implement a lifecycle-managed reusable worker HTTP client. Reject upstream cookies, preserve per-request worker secrets and authentication revalidation, preserve no automatic retries, close on shutdown.
- [x] Cache public content-hashed assets in the browser and avoid private identity lookups for those assets. Keep HTML and API responses uncached.
- [x] Run workspace lookups outside the event loop and preserve every dispatch validation.
- [x] Restrict reconciliation SQL reads to candidate source/receipt dates, retaining timezone boundaries, earlier valid receipt selection, archived/undated stale events and every existing matching rule.
- [x] Remove bootstrap's duplicate queue-count query while returning identical values.
- [x] Run full backend tests and disposable before/after benchmarks. Verify schema/data/status invariants; document measured limits. Do not run migrations, tune database pragmas, or modify production files.

## Results and preservation checks

Local Linux measurements on disposable data (not the user's production database):

| Workload | Before | After |
| --- | ---: | ---: |
| 60 authenticated loopback API requests, median | 12.73 ms | 5.40 ms |
| Same requests, p95 | 15.38 ms | 7.49 ms |
| TCP connections for those requests | 60 | 1 |
| Warm weekly reconciliation, 20,000 links + 20,000 retained receipts | 157.25 ms | 29.38 ms |

The weekly dataset spans 500 days, with 520 candidate source rows and 280
completions in the selected week. Before/after logical-state SHA-256 matches:
`fcc8d95b2f0269f14b947859606538e1f0356d9b775d321c42b782aad768c8c7`.
The comparison includes checked values, cell versions, confirmation timestamps,
message associations, and recorded source. No schema, index, database pragma,
worker capacity, scheduler interval, model concurrency, or credential setting
changes are introduced. Private responses remain `no-store`; only public
content-hashed build assets receive immutable caching.

Regression checks cover connection reuse/shutdown, rejection of upstream cookies
across workspace switches, unchanged session revocation, nonblocking workspace
lookup, one bootstrap count query, real process isolation/restart, accounting
boundaries, and the final microsecond of a Chicago week. SQLite materialized CTEs
use the same SQLite 3.35 feature floor already required by existing `RETURNING`
queries. Actual Windows/production-load speedups have not been measured.

Final verification: 396 backend tests and 76 subtests passed; 230 frontend tests passed; `git diff --check` passed. Frontend source/build artifacts are unchanged. Changes remain uncommitted.
