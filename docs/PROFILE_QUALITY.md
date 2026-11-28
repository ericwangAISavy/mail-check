# Profile quality

The dashboard measures observed recruiting outcomes, not a causal resume score.
Role fit, company selection, market conditions, and missing mail also affect results.
It reads the permanent receipt history, independent of the dashboard's mail date,
category, handled status, and search filters. Account and bidder scope still apply.

## Counting applications and outcomes

- Confirmations are deduplicated within each profile and Chicago calendar day using
  the existing company, role, and explicit job-reference rules. Different days remain
  separate applications. Different known roles or reference sets remain separate.
- Outcomes must match a preceding confirmation for the same profile and normalized
  company. Conflicting known roles or explicit job references prevent a match.
  Strong reference evidence takes precedence over role evidence. If several applications
  have equally strong evidence, the outcome remains unlinked, including applications on
  different days. A later reminder must not automatically convert a newer application.
  Candidates are bounded to the preceding 180 days.
- Repeated interview messages, later rounds, and repeated rejections count once per
  application and outcome type. An application may have both outcomes.
- Each response window is exactly 7, 14, or 30 days after the confirmation timestamp.
  Later outcomes do not affect that window's conversion. A whole application day must
  finish its follow-up before entering the denominator. The default is 14 days.

For each mature cohort, interview rate is distinct applications with a matched interview
within the response window divided by distinct confirmed applications. Rejection rate
uses matched rejections and the same denominator. Each rate is between 0% and 100%;
the two rates need not sum to 100%. Recent applications are shown separately.

## Reading the graph

The default 28-day trend sums outcomes and denominators from the trailing 28
application days before dividing. It does not average daily percentages. Day/week/month
selects the sampling interval. Per-period mode instead uses that calendar period's
cohort. The most recent mature week/month can be partial.

The axis remains 0–100%. Missing denominators produce gaps. Samples below 20
applications are hidden by default and can be displayed explicitly. There is no curve
smoothing, peak clipping, or invented zero activity. Tables and tooltips show exact
counts and Wilson 95% confidence intervals. These intervals cover sampling uncertainty,
not missing-data or matching errors. Overlapping rolling points are not independent.

The table covers the latest 28 mature application days. Interview trend compares
that window with the preceding nonoverlapping 28 days; it reports higher/lower only
when both have at least 20 applications and their intervals do not overlap. Otherwise
it shows a small sample, a building baseline, or no clear change. This is a conservative
descriptive signal, not a controlled statistical test.

Unlinked outcome emails are excluded from numerators and disclosed. Historical
coverage is inferred from available retained records, not certified complete. Missing
confirmations or outcomes can bias rates; don't compare profiles without considering
these limits. Schema 56 backfills job-reference metadata for retained outcome messages
once; pruned email bodies cannot be recovered. Reporting never changes checked links,
email handling, classifications, payments, or profile settings.
