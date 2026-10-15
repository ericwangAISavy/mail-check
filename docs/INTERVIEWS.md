# Interview tracking

Interview is an admin-only route at `/interviews`, between Dashboard and Accounts.
Guest access remains limited to Dashboard. The page defaults to Work week and also has Week, Month and Day views,
Today/previous/next navigation and enabled-account/company/status filters.
No production events are seeded.

## Current collection behavior

Web Check now, `/api/check`, `/api/interviews/sync`, and automatic web checks now
collect explicit VEVENT calendar invitations only. They do not persist new message
bodies, create classifications, initialize a model, or infer meeting relevance from
email prose. Existing stored mail and classifications remain available. The CLI mail
triage commands remain separate and continue their documented mail workflow.

Both connected mailbox transports include read and unread invitations within the
configured lookback. Microsoft Graph requests invitation attachments and identifying
metadata without message body fields; IMAP reads MIME transport to locate calendar
parts. This imports invitations from the configured inbox/folder, not the provider's
Calendar API: events that exist only on a remote calendar are not synchronized.
The source is read-only and the existing shared job lock prevents overlapping checks.

Only dated calendar-backed events appear in the calendar. Previously inferred
text-only events remain stored but are excluded from this view. Event UID, occurrence,
sequence and revisions still control deduplication and updates. Imported source rows
retain invitation identifiers and a nullable link to any previously stored mail.
Repeated collection preserves existing source links. Unknown dates are skipped;
known cancellations without DTSTART retain the confirmed time. No upcoming/review
panels or summary cards remain. The optional saved-invitation import reads retained
calendar attachments without requiring stored classifications or a model.

The implementation history below describes the original extraction feature; the
current calendar-only collection above supersedes its automatic text inference.

## Existing architecture reused

| Concern | Integration |
| --- | --- |
| IMAP / Outlook fetching | `sources/imap.py`, `sources/outlook.py`; existing read-only requests |
| Normalization | `normalize.normalize`; separate bounded extraction text preserves full meeting links |
| Classification | Existing `llm.classify` and classification cache remain intact |
| Manual and automatic checks | `pipeline.check_once`; existing web scheduler and CLI/watch wrappers |
| Reprocessing | `pipeline.reclassify`, after stored classifications are updated |
| Local persistence | Existing `db.connect/session`, additive schema version 8 migration |
| Model extraction | Existing configured `LLMClient` and JSON-recovery layer |
| UI / routing | Existing React Router, React Query, shared cyber tokens and four-size Geist scale |
| Mail rendering | Existing `Reader` and `/api/messages/{pk}` |
| Checking / notifications | Shared `api.startCheck`, existing job status, query invalidation, toast provider |
| Authorization | Existing middleware; no new guest privileges |

No mailbox writes, additional polling service, cloud database, calendar-provider
permissions, or remote font/calendar UI service are introduced. The calendar is a
local React component, so no JavaScript calendar dependency is needed.

## Detection and storage

The existing provider response now carries calendar attachments and thread/reference
metadata into normalized messages. IMAP reads calendar MIME parts from the already
fetched message. Graph expands attachments in the same read-only message request;
no second mailbox listing or independent fetch cycle is added. Calendar text is
bounded to 256 KB per attachment and ten attachments per message. Graph expansion
can increase response size for mail containing unrelated file attachments.

`interviews.process_run` runs after classification/cache resolution and on retries.
`icalendar` parses calendar metadata before any inference: UID, sequence, DTSTART,
DTEND, timezone, summary, description, location, organizer, attendees and status.
A matching job classification or interview context is required, so ordinary
calendar appointments are not indiscriminately imported.

Without calendar evidence, existing job classification plus scheduling indicators
gate a structured extraction call through the configured local model client. This
extracts company, role, stage, times, timezone, meeting URL, participants and status.
A conservative rule fallback recognizes only explicit timestamps/year/timezone;
ambiguous or incomplete results remain review items. Full meeting URLs are kept
separately from the classifier's shortened/truncated body. The extension's model
work is capped at 60 seconds per mail run; after a model failure, further extraction
calls are deferred rather than repeatedly hitting an unavailable server.

New local tables:

- `interview_events`: schedule, company/role/stage/status, meeting/organizer/participants,
  confidence/review reasons, UTC times/original timezone, revision/sequence, protected
  manual fields, created/updated timestamps, and UID/recurrence identity.
- `interview_sources`: many source messages/accounts per event, email/thread identities,
  subject/sender/received metadata, and a nullable link to the original stored mail.
- `interview_scans`: per-message content/classification fingerprint and retry state.

Retention can prune the original email without deleting the interview or its source
metadata. The detail panel then explains why the full source email is unavailable.
Only records associated with an enabled connected account appear in the calendar.
Removing an account removes its source associations, following existing account
foreign-key conventions.

## Reconciliation and corrections

UID plus recurrence identity is strongest, including invitations copied across
accounts. Otherwise matching uses account-scoped source message IDs, references and
conversation relationships, compatible interview stage, then company/role and nearby
time. A conservative recent-process similarity fallback handles unambiguous
reschedules/cancellations. Distinct known UIDs never merge. Ambiguous matches create
a review item rather than overwriting one of several possible interviews.

Sequence and revision dates prevent old invitations from reverting new ones.
Newer, confident text reschedules/cancellations can update an existing calendar
booking. Reminders do not restore cancelled events. Reschedules update the same
record and clear an obsolete end time when a new end is unknown. Cancellation
retains the record. Completion is calculated for display from a known past end;
stored explicit status is preserved.

Edits persist to the same local database. Only edited fields are locked; later
automatic updates cannot overwrite them. Time inputs are explicitly interpreted in
the editor's selected IANA timezone. UTC is stored internally and the original
zone is preserved. Floating, missing, ambiguous DST times and recurring calendar
series are flagged for review rather than silently assigned the server timezone.

## Historical scan and APIs

`Scan existing mail` starts an optional background job through the existing job lock.
It reads classified stored mail in batches of 25, commits each message, reports
progress, and resumes unscanned/retryable messages on the next manual scan. It never
runs automatically on startup or during page rendering. Backfill model work is
bounded to ten minutes per scan; deferred messages can be retried in another scan.

- `GET /api/interviews`: enabled-account event records and real filter options.
- `GET /api/interviews/{id}`: details plus all source messages/accounts.
- `POST /api/interviews/{id}`: validated field corrections with per-field protection.
- `GET /api/interviews/scan`: background progress.
- `POST /api/interviews/scan`: start/resume discovery; returns 409 if another job runs.

All interview routes/APIs require admin. Meeting links accept HTTPS only and are
opened only by explicit user action.

## Validation and practical limits

Backend coverage includes normal invitations, calendar metadata precedence, all main
meeting platforms, lifecycle/rescheduling/cancellation, stale sequences, duplicate
confirmations/UIDs, multiple accounts, ambiguous times/DST, manual corrections,
completion, unrelated email, extraction/classification failures, source retention,
provider metadata capture, migration, API authorization and incremental backfill.
Frontend coverage includes calendar modes/navigation, filters, shared checking,
scanning, details and protected correction requests. Browser QA uses a separate
fixture database and deterministic mailbox/model stand-ins; it exercises the real
scheduler, pipeline, storage, APIs and frontend without contacting user inboxes.

A bug in the affected Graph source was corrected: `fetch_unread` now includes
`isRead eq false`, restoring the unread-only contract and passing the existing smoke
assertion. The pipeline's date sorting now also tolerates both aware and naive UTC
message dates.

Live Microsoft/IMAP credentials and a real configured model are not exercised by
the isolated QA. Extraction accuracy depends on source content and model output;
review remains necessary for uncertain schedules. Recurring series are retained as
review items rather than expanded into guessed occurrences. Historical scans can
only recover retained text and metadata; older mail fetched before this feature did
not store its ICS attachment, and deleted/expired mail cannot be reconstructed.

## Files

Added: `mailcheck/interviews.py`, `mailcheck/interview_metadata.py`,
`frontend/src/pages/interviews.tsx`, `frontend/src/pages/interviews.css`,
`frontend/src/pages/interviews.test.tsx`, `tests/test_interviews.py`, and this report.

Modified: `mailcheck/db.py`, `mailcheck/models.py`, `mailcheck/normalize.py`,
`mailcheck/pipeline.py`, `mailcheck/sources/imap.py`, `mailcheck/sources/outlook.py`,
`mailcheck/web/app.py`, `pyproject.toml`, `frontend/src/App.tsx`,
`frontend/src/lib/api.ts`, `frontend/src/lib/types.ts`, `frontend/src/cyber.css`,
`design-qa.md`, and generated `mailcheck/web/frontend_dist` assets.

## Verified results

- Backend discovery: 108 tests pass (81 existing and 27 interview tests).
- Frontend: 73 tests pass across ten files, including four new Interview-page tests.
- Existing smoke runner with its isolated test keyring: 331 assertions pass.
- Production build includes strict TypeScript checking and Vite bundling: passes.
- Python compilation: passes. No separate lint command is configured in this repo.
- Existing analytics benchmark: 10,000 messages, maximum API time 0.0535 seconds.
- Chromium workflow: sidebar navigation, Month/Week/Day, Today/next, account/status
  filters, event details, existing source reader, manual edit persistence, shared
  Check now, optional scan, and real scheduler/pipeline lifecycle all pass.
- Browser widths: 1672, 1280, 900 and 390px, with no document overflow or console errors.
- The lifecycle uses deterministic provider/model stand-ins in an isolated fixture:
  Oct 18 at 10:30 AM America/Chicago → Oct 20 at 2 PM → cancelled; event ID remains
  unchanged. Two enabled account fixtures exercise unified calendar filtering.
- Existing Triage, Dashboard, Accounts and Settings render successfully; guest
  interview API access is denied. The normal local app serves the new route/APIs.

## Calendar/interview bug review

Confirmed with regression tests before fixing:

- Separate same-stage bookings in a shared conversation could overwrite one another.
  Normal invitations now need compatible times; explicit references and matching
  timestamps outrank a shared thread or weak process similarity.
- Different recurring occurrences sharing a UID could collapse into one event.
  UID plus recurrence identity is preserved throughout matching and text updates.
- Calendar cancellations without interview keywords were missed. Known UIDs now
  establish context even for minimal cancellation metadata.
- Cancellation extraction could replace the last booked time. Cancellation now
  retains the confirmed start/end/timezone; uncertain reschedules retain known times
  while requesting review.
- A new automated start could fall after a manually protected end (or vice versa).
  Conflicting automatic fields are withheld and the record is flagged for review.
- Date-only model output was interpreted as midnight. Missing clock time now stays
  unknown and requires review. ICS DURATION now supplies the actual end time.
- Clearing a start time could make a record disappear from both calendar and review.
  Incomplete manual records now remain in Needs Review. Invalid timestamp types and
  whitespace-only company names are rejected instead of corrupting stored values.
- Date corrections could use an absent/unsupported original timezone instead of the
  timezone shown by the editor. Date edits now submit that displayed timezone and
  only the edited time fields; unrelated end times remain unprotected.
- Changing the selected event could retain another event's unsaved editor/source
  state. Details are now keyed by event ID, so navigation resets the draft.
- A configuration failure could leave scan progress stuck at running. Cleanup now
  covers configuration loading. A detector-version fingerprint lets explicit scans
  revisit records processed by the earlier detector, while remaining incremental.

Validation after review: 124 backend tests, 76 frontend tests, 331 existing smoke
assertions, TypeScript/production build, Python compilation, real browser correction
and navigation regressions, and the automatic invitation → reschedule → cancellation
workflow. Browser tests use the same isolated fixture/provider/model stand-ins
noted above. The existing API test fixture was changed from a fixed calendar date
to recent UTC mail after it aged out of the application's real retention window.

## Outlook-style calendar

The calendar uses a compact charcoal Outlook-style toolbar and time grid, with
sticky weekday headers, half-hour guides, a current-time marker, and an initial
8 AM scroll position. All 24 hours remain available. Events use their actual times;
overlapping bookings occupy separate lanes and multi-day bookings are clipped per
day. Unknown end times are explicitly identified rather than assigned a duration.
Events without confirmed start times are excluded from the calendar.

View/date navigation and account/company/status filters are reflected in the URL.
Split view displays separate source-account calendars with synchronized scrolling.
Share copies the current filtered calendar URL or downloads an RFC 5545 ICS snapshot;
it does not publish a calendar or send invitations. Print produces a landscape
calendar. Expand mode supports Escape and keyboard navigation. Clicking an event
keeps the existing details, source reader and protected local corrections.

Calendar-specific Segoe UI/Arial typography and green/blue/purple account colors
follow the supplied Outlook reference. The surrounding application retains its
existing navigation and font scale. This is the local interview calendar; provider
calendar write synchronization and drag-to-reschedule are not implemented.

Validation: 85 frontend tests, 124 backend tests, strict TypeScript and production
build pass. Chromium exercises views, history/date navigation, filters, overlap
placement, account split/scroll, source reader, copy-link, ICS download, print and
expanded mode at 1616, 1280, 900, 390 and 350px without document overflow or browser
errors. Export parsing confirms 22 distinct test events; print produces one A4
landscape page. Test appointments exist only in the isolated QA database.

## Calendar-only simplification validation

130 backend tests and 85 frontend tests pass, including no-model collection, no new
message/classification rows, text-only exclusion, generic calendar event acceptance,
repeat-import deduplication, cancellation without DTSTART, source-link preservation,
Graph metadata-only requests, and both sync endpoints without model configuration.
Production TypeScript/Vite build passes. Chromium checks joined sidebar/header edges,
removed Dashboard recent-events and Interview summary/agenda panels, calendar views,
and no document overflow at 1616, 1280, 900, 390 and 350px. Real provider credentials
are not exercised by these isolated tests.

The existing smoke runner also passes all 331 assertions using an isolated in-memory
keyring; no real OS keyring or provider credentials were used.
