# Shared interview feedback implementation plan

**Goal:** Admins select multiple fixed company-feedback badges in existing event details and see shared badges on the same company's calendar events across workspaces.

**Approved choices:** Multiple badges. Exact visible labels: `in-person`, `linkedin`, `fuck`, `normal`. No free text or separate page.

**Design:** Store each admin's current company choices centrally in the control database, scoped to their selected workspace and identity. Aggregate only the four fixed labels; do not share event details, mailboxes or author identities. Normalize case, punctuation and legal company suffixes, without fuzzy matching. Derive company from an accessible interview when saving and reject stale company changes. Admins can change or clear their own choices. Standalone mode uses a small local feedback store.

**Approach:** Central indexed storage avoids scanning every workspace and avoids coupling feedback availability to the calendar's existing API. Bounded, visible-company lookups load badges independently. Fixed selection buttons live in event details; compact display badges appear on calendar events. Feedback failures leave calendar navigation usable.

- [x] Test company matching, shared aggregation, isolated edits, invalid options, admin-only access and stale event validation.
- [x] Implement central/local storage and permission-checked feedback routes.
- [x] Test and implement fixed-option controls, calendar badges and isolated loading errors.
- [x] Run relevant backend/frontend tests, release checks and production build; add one minor release.

**Validation:** 84 backend tests and 14 subtests passed across feedback, control store, gateway, interview job matches and frontend API suites. All 42 related frontend tests passed. After review, all five feedback tests passed again with a mixed valid/generic company regression, alongside all six release tests. TypeScript and the production build passed; release metadata checks passed for 3.31.0. Review found and resolved one batch-isolation defect. Release checks also exposed a Windows default-encoding problem; Git comparisons and generated test history now use explicit UTF-8.

**Constraints:** Do not change existing interview extraction, completion status or matching rules. Do not modify production data as part of implementation or release tracking.
