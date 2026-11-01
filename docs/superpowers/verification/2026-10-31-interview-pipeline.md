# Interview pipeline verification — v2.5.0

The approved opportunity model and concise UI are implemented. The default
`/interview-processes` route now opens the pipeline; the previous timeline remains
at `/interview-processes/legacy` for reconciliation. No production data, credentials
or remote mail/calendar were used during development.

## Automated checks

- Full backend suite: 533 passed, 76 subtests passed. One existing Starlette
  TestClient deprecation warning. Log: `/tmp/pipeline-verification-backend.log`.
- Full frontend suite: 294 passed across 37 files.
  Log: `/tmp/pipeline-verification-ui.log`.
- Final production build passed after responsive CSS refinement.
  Log: `/tmp/pipeline-shipped-build.log`.
- Release consistency and git whitespace checks passed.
- Independent review identified and verified fixes for synthetic task collisions,
  replay after revoked access, lost merge deadlines, paginated activation guards
  and explicit deadlines suppressed by holds/future meetings.
- Further regression verifies evidence-review SQL count remains bounded as
  bookings grow (50 bookings: under 20 queries, previously 61).

## Real browser checks

Chromium used the real FastAPI application, real temporary SQLite records and
real sign-in with synthetic profiles/opportunities on loopback:
- Created an opportunity through the actual form and verified All active selected.
- Completed a task through the real detail action and verified next actions updated.
- Opened list/detail in dark and light themes without JavaScript page errors.
- Verified 390px mobile width, stacked opportunity summaries and visible next-action
  cells without page/table horizontal overflow.

Screenshots were inspected locally under `/tmp/pipeline-*.png`; they are QA
artifacts, not production data or dependencies.

## Deliberate boundaries

- Review/accept or link existing evidence explicitly. Ordinary calendar meetings,
  domains and broad names do not silently become confirmed hiring opportunities.
- Legacy data/control tables remain intact. Activation requires reconciliation
  of legacy reminder controls; the follow-ups API then uses the new shared engine.
- Per-account calendar successful-sync receipts are recorded; mail freshness stays
  Unknown where no per-account receipt exists. Outlook Sent Items is not collected.
- Explicit manual contact logs are not delivery receipts; local successful sends
  display as Sent through OfferPath. No automatic send or outcome change exists.
- Remote booking history retains original link-time metadata and attendance
  history, not every intermediate Outlook revision. Latest 100 audit entries are
  displayed; the underlying audit history is retained.
- Native Windows/live Outlook/provider latency was not validated in this Linux
  workspace. Tests cover local contracts, permissions, concurrency/retries,
  timezone/DST edges and stale/deleted evidence using isolated fixtures.
