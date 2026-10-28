# Selected Week Refresh Implementation Plan

**Goal:** Keep both safe refresh and full automatic-match rebuild, scoped to the displayed Chicago Monday–Sunday week.

**Architecture:** Extend existing verification and refresh API rather than duplicate accounting. Safe refresh adds matches without removing checks. Rebuild additionally removes unsupported automatic matches in the selected week. Preserve manual checks, retained receipt metadata, historical check runs and saved payments. Record manual provenance when later attaching a confirmation.

**Tech Stack:** Existing FastAPI, SQLite and React Query; no schema change.

## Tasks
- [x] Reproduce the incorrect selected-week request and stale automatic check with failing API/UI tests.
- [x] Add validated week and mode to refresh API; retain empty-body compatibility using the current calendar week.
- [x] Reconcile only events in the selected week; inspect preceding source dates as needed without modifying adjacent-week completions. Preserve manual provenance, old retained receipts and payment records.
- [x] Add both week-specific buttons; disable them and week navigation during refresh, invalidate related queries, show results/errors.
- [x] Verification: 391 backend tests plus 76 subtests, 230 frontend tests, production build and final diff checks passed. Changes left uncommitted for user review.

## Review focus
Selected historical week; stale reclassified email; manual check later matched automatically; earlier sourcing date; completion outside selected week; idempotent second rebuild; paid amount preserved; invalid request/date; concurrent edit serialized by the existing transaction.
