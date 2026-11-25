# Additive sourcing confirmation matching

**Goal:** Keep the existing matcher unchanged and add independent evidence-based alternatives for confirmations it cannot bind uniquely.

**Approved behavior:** Existing rules OR unique unchecked candidates OR company aliases/body employer evidence OR verified posting titles OR explicit job identities. Preserve all existing checks and proof. Generic company-only receipts and unresolved job IDs remain review cases. Do not force EW's count to a target.

**Architecture:** Keep `_matching_plan` intact. A separate fallback planner consumes its result and adds new bindings only. Public posting metadata is bounded, cached, fetched outside write transactions, and never fetched by passive payment refreshes. Persist fallback provenance separately from accounting history.

**Tech stack:** Existing Python/SQLite/httpx, pytest, frontend release build.

## Tasks

- [x] Add failing tests for additive planning, mailbox boundaries, proof reservations, aliases, verified titles, historical identities, ambiguous IDs and missing fields.
- [x] Implement a separate posting resolver/cache with allowlisted public ATS endpoints, bounded responses/timeouts, no redirects and no credentials.
- [x] Implement and integrate fallback planning and evidence storage in manual/global verification; preserve legacy functions and accounting behavior.
- [x] Test network failure, cached/no-network paths, unchanged legacy regressions and verification idempotency.
- [x] Run a read-only EW preview with actual retrieved facts. Report the observed result rather than assuming 96.
- [x] Request a fresh review, address findings, add one minor release, verify release consistency and build frontend artifacts.

## Review focus

Legacy outputs must win; checked proof must never move. One receipt must not credit two rows. Different ATS IDs are not duplicate applications by definition. Metadata failure must leave legacy matching usable. SQL scope/date filtering must not silently discard older rows for the explicit-identity fallback. Slow metadata requests must never hold a SQLite write lock.

## Implementation rulings

- The user's approval of the proposed fallback set authorizes implementation; no additional design approval is needed.
- The three company-only EW candidates remain review-only. New alias/title matching requires role evidence or explicit job identity.
- Live database access is for read-only verification; feature tables are created by normal application migration, not by this task against production data.

## Verification ledger

- Original `company_key`, `role_key`, `_contains_name`, and `_matching_plan` ASTs match Git HEAD exactly.
- Fresh review found explicit-identity fall-through and missing-role warming gaps; regression tests reproduced both and fixes passed review. A later labelled UUID regression was also reproduced and corrected.
- Targeted fallback/posting suites: 33 passed. Wider sourcing/payment/collection regression: 205 passed with 21 subtests. The obsolete removed-bidder test expectation was aligned with the already-shipped retained archived-sheet behavior; runtime behavior was not changed for that test.
- Original 161-email snapshot: 11 additional EW matches and 2 explicit historical Sam matches, using the real planner and posting resolver. Live SQL changes: zero. Current traffic has advanced the live baseline, so 85 to 96 describes the reviewed snapshot, not a forced production total.
- Cold metadata preparation measured 1.295 seconds; the actual bounded warming path completed in 3.605 seconds in the read-only preview with an in-memory cache.
- Release 3.27.0; production frontend build, release-history UI tests and release consistency checks passed.
