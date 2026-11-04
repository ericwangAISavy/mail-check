# Daily deduction implementation and verification

User-confirmed design: one rule per admin workspace, minimum daily checked count
and flat USD deduction. Only completed weekdays with an active account assignment
qualify; today/future/weekends/unassigned days are excluded, in America/Chicago.
A strict below-minimum comparison includes zero counts. Multiple accounts never
multiply one day's fee. A zero minimum disables deductions. Apply flat cents after
rounded weekly gross; clamp net to zero. Preserve saved payments/manual overrides.

- [x] Fail-first backend tests for eligibility, zero floor, thresholds and preservation.
- [x] Singleton rule schema42, validated admin endpoint and calculated report fields.
- [x] Admin-only form above daily breakdown; explicit save, danger counts and net explanation.
- [x] Upgrade/multi-account/permissions tests and read-only report verification.
- [x] Independent review; fix frontend minimum max to match server validation.
- [x] Desktop/mobile browser checks for save, refreshed totals and no overflow.
- [x] Full suites, release consistency, build and final repository checks.
- [x] Prepare tested release2.18.0 for commit/push.

No production database or real payment records were modified in development.

Verification: 689 backend tests/84 subtests and 349 frontend tests passed;
production build, release consistency and whitespace checks passed. Browser checks
at1440px and390px verified saving the rule updates danger days and net pay with
no page overflow. The first full backend run exposed an existing follow-up
reference to the removed INTERVIEW_CONTEXT detector; using the shared current
interview_evidence detector fixed its failing test and the final full suite.
Existing dependency deprecation and bundle-size warnings remain nonblocking.
