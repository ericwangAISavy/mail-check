# Profile quality based on application outcomes

User delegated the methodology and implementation. Preserve profile colors and
line/bar/day/week/month controls. Replace same-period email ratios with matched
application-cohort conversion; do not cosmetically smooth false rates.

Method: deduplicate confirmations within profile/Chicago day with existing
company/role/reference rules. Link outcome receipts conservatively to the latest
compatible preceding application, using explicit job references where available.
Conflicting roles/references and ambiguous matches remain unlinked. One interview
and one rejection flag per application, each within a fixed 14-day follow-up.
Both outcomes may occur for the same application; neither rate can exceed 100%.
Recent applications remain provisional and outside mature conversion denominators.

Default visualization: sample a trailing 28-day volume-weighted application-cohort
window at day/week/month endpoints. Also offer per-period views. No fabricated
zeroes for missing denominators, no clipping peaks, and no interpolated curves.
Use a stable 0–100% axis, show exact numerator/denominator and Wilson 95% intervals,
and distinguish low-volume observations (fewer than 20 applications) and incomplete
follow-up. Surface unmatched outcomes and recorded-history limits. Treat outcomes
as observed recruiting performance rather than proof of resume quality alone.

- [x] Add tested grouping/matching/cohort aggregation in an isolated backend module.
- [x] Integrate a new outcome payload while retaining legacy dashboard API fields.
- [x] Build and test transparent rolling/cohort chart, statuses, volumes and confidence.
- [x] Review, run relevant suites, add a release, and regenerate production assets.

Do not rewrite emails, checked statuses, payments, profile settings or stored
classifications to improve metrics. Keep report calculations bounded/indexed and
independent of live model or network calls.

Validation: 93 backend tests plus 13 subtests passed; 20 focused frontend tests passed. Full frontend run: 625 passed, one settings navigation timeout; isolated retry passed all 54 tests in that file. TypeScript, production build, release consistency, and changed-file whitespace checks passed. Independent code review findings were addressed (upgrade metadata backfill, cumulative chart aggregation, scoped backend reads, stable colors across filters). Release 3.32.1.
