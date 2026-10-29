# Reliability review

Scope: startup/workspace lifecycle, authentication and bidder permissions, shared API handling, Dashboard and Settings recovery, and existing accounting/sourcing/calendar suites. No production DB, credentials, or user settings were accessed or changed. Existing uncommitted 2.3.5 gateway-error handling is preserved.

## Confirmed and fixed

1. **Owner repair route blocked by bootstrap errors.** A rejected bootstrap query returned Recovery even after clicking Try settings. Owner Settings now mounts independently of bootstrap, reuses cached shell data if available, and keeps Settings mounted during background bootstrap failures/refetches so unsaved edits are retained. The setup ribbon does not infer missing accounts from unknown recovery data. Non-owner Settings restrictions remain intact.
2. **Invalid saved Dashboard filters trapped users in retries.** An out-of-range `days` or custom date URL caused repeated validation failures while all filters were hidden. The unavailable state now offers Clear filters when URL filters exist, resetting to a valid seven-day view. Existing retry and stale-data behavior are preserved.
3. **Concurrent suspend/re-enable left enabled workspaces stopped.** A delayed worker stop could run after the database and pool were re-enabled. The gateway now serializes the database update and matching worker lifecycle operation in a background thread. Regression reproduces the prior invalid state with an explicit stop barrier, then verifies final registry/runtime agreement.

## Validation

Each bug has a regression test that failed before the fix. Frontend tests cover owner repair access, direct Settings isolation, and invalid-filter recovery. Gateway tests cover overlapping access changes alongside existing revocation, isolation, settings permissions, and worker proxy tests. Final verification: 421 backend tests plus 76 subtests, 254 frontend tests, production build, release consistency, and whitespace checks passed. Browser previews with disposable sample API data confirmed owner Settings access after a bootstrap failure and Dashboard recovery after clearing invalid filters.

## Limits

The reported Windows local Dashboard outage remains unconfirmed without its current server/workspace log or exact local error response. The Cloudflare HTML-display issue was reproduced separately and fixed in 2.3.5; that client fix does not prove the external origin connection is healthy. Automated tests and code review do not establish that every production state is bug-free.
