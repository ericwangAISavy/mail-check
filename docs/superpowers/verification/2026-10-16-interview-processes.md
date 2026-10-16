# Interview processes

Implemented the admin-only `/interview-processes` page and
`/api/interview-processes` endpoint on `fix/page-specific-check`.

Calendar participant and organizer domains determine organization identity. Own
mailbox addresses and Google/Teams/Zoom service domains are excluded. Exactly one
eligible domain assigns an event to that organization; zero or multiple domains
place it only in Unassigned with an explanation. Domains retain their full name,
including subdomains, and compare case-insensitively.

The page displays counts, next scheduled interviews, chronological histories,
calendar booking titles, status, organizer, source account labels, domain search
and event detail links. The existing calendar collector and shared interview
query invalidation refresh the groups after collection. Existing stored calendar
events participate immediately; no second event store or process migration is
needed. Cancelled events remain in history and do not become the next interview.

## Verification

- Backend: 225 passed, 59 subtests passed. The existing Starlette/httpx
  deprecation warning remains.
- Frontend: 130 passed across 20 files.
- Standalone smoke: 331 passed, 0 failed.
- TypeScript and Vite production build passed; compiled assets regenerated.
- `git diff --check` passed.

Regression coverage includes domain normalization and exclusion boundaries,
organizer evidence, ambiguous events, idempotent repeated collection, new
organizations, updated participants, cancellation, disabled sources, admin-only
API/page access, search, empty/error states, detail links and calendar-mode header
checks without an LLM.

Chromium exercised a real local app and disposable SQLite database with synthetic
Graph responses: Interview Check now collected four events; Interview processes
showed Appian, Rava and Unassigned. A subsequent header check imported another
Appian event into the same group and refreshed the page automatically. Domain
search preserved ambiguous matches, and View event opened the right details.
Desktop 1440×1000 and mobile 390×844 screenshots were inspected. Mobile heading
actions stack vertically and page width stays within the viewport. No page errors
occurred. No real mailbox or user data was used; live Microsoft access was not
tested.

## Existing merge regression repaired

The branch's merged database initialization retained migrations for sourcing and
payment tables but omitted creation of those tables and native snapshot migration.
Fresh databases failed with `no such table: native_rows`; the existing legacy
migration test reproduced it. Restored all schema initialization inside the
existing upgrade transaction, and let native snapshot migration join that outer
transaction. The legacy migration test and complete backend suite now pass.

The first full backend run overlapped a Vite build, which temporarily removes its
output directory. One existing Interview shell test returned 404 during that
window; it passed individually afterward and the complete backend suite passed
when run against the completed build.
