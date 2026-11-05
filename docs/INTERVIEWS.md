# Meeting calendar

The admin-only Interview page displays interview-related calendar bookings in Work week, Week,
Month and Day views. Named bidders are limited to their own sourcing sheets and payments. No production events are
seeded, and existing mail history is preserved.

## Interview processes

Open **Interview processes** in the sidebar to follow calendar events by organization.
Use **Check now** on Interview to collect bookings; the process page's header also
uses calendar collection. When collection finishes, the organization timelines refresh.
Each organization is a compact horizontal sequence of equally spaced milestones
connected by a line. Meetings are circles with calendar icons; messages are rounded
squares with envelope icons. The first and last milestones sit at the endpoints;
spacing shows process progression rather than elapsed time. Events and saved emails
stay in chronological order. Each process has a stable accent color and tinted
background. Hover or keyboard-focus a point to preview its title, time, status and
summary. Click, tap or press Enter on a meeting milestone to open the same event
dialog as Interview, including local corrections. Message milestones open a
matching dialog with sender/mailbox/date details, summary and full saved message
content. Both dialogs close back to the originating milestone. Where a saved email
has a safe provider link, its details can open the original email.

Use **All**, **Daily**, **Weekly**, **Two weeks**, **Monthly** or **Two months** to choose the
date window. All is selected by default and shows every process with its complete milestone history. With a narrower window, a process appears if at least one of its milestones falls in the
window, and its entire saved history is then shown. Weeks start on Monday; Two
weeks spans fourteen days from that Monday. Monthly windows start on the first of the selected
month, and Two months spans that month and the following month. The date picker,
previous/next arrows and Today move the window. Times and boundaries use your
browser's timezone. Dates appear in previews rather than along a time ruler.
Small screens can scroll longer milestone sequences horizontally.

Milestones before the window are muted; milestones inside it are highlighted.
Upcoming Scheduled/Rescheduled meetings after the window use a danger color.
Cancelled/completed meetings and messages after a historical window remain muted,
with their relation to the selected window explained in the preview. Timing labels
and distinct meeting/message shapes also convey meaning without relying on color.

If every saved milestone in a displayed process is already in the past, an amber
flag milestone appears at the end with a **Follow up** badge. This uses actual
timestamps rather than the window's colors; an already-past milestone can still be
highlighted because it falls within the selected window. A meeting that is still
in progress or any later milestone prevents the reminder. The flag is a visual
status hint, not a saved calendar event or message; it does not change counts or
window matching. Real milestones and the flag retain equal spacing.

**Pin** keeps a matching process above unpinned processes. Pins are stored in the local SQLite database
and shared across admin sessions/devices. Unpin reverses this. Processes without
milestones in the current window are hidden, including pinned processes. Search still applies to
pinned processes.

Each process has a **Remove** control beside its pin. Removal hides that organization
from this page across reloads and subsequent calendar collections; saved events and
messages remain available in Interview and Triage. Open **Removed processes** below
the list and choose **Restore** to bring a process back, including its pin state.
Removal and restoration are admin-only. All remains the default when this page
opens.

Emails already saved by mail triage join an existing calendar organization's
timeline when their sender domain matches that organization exactly. They use the
latest saved classification summary, or a short saved text preview. Unrelated
mail does not create processes; no email or model requests are made by this page.

Organization identity is the full domain after `@` in participant and organizer
email addresses, normalized to lowercase: `HR@Appian.com` becomes `appian.com`.
Subdomains remain distinct (`jobs.appian.com` is its own organization). All connected
mailbox addresses, including disabled ones, are excluded as your own identities.
Google (`google.com`), Teams (`teams.microsoft.com`, `teams.live.com`, `teams.com`)
and Zoom (`zoom.us`, `zoom.com`), including their subdomains, are excluded as meeting
services. Meeting URLs and extracted company names do not determine a process.

- Exactly one eligible domain: the event joins that organization's process.
- Multiple eligible domains: the event appears only under **Unassigned**, with the
  candidate domains shown for review.
- No eligible domain: the event appears under **Unassigned** with an explanation.

Existing calendar events appear immediately. Processes are derived from the saved
event records, so collecting the same booking again does not duplicate an event or
process. Updated participant metadata changes its group; cancellation stays in the
history and is excluded from the next scheduled interview. As on Interview, only
calendar events with a start time and an enabled source account are included.
This page is available only to admins. Search finds organization domains and also
matches candidate domains in Unassigned events.

## Collection

On Triage, Check now (`/api/check`, default `mode: "mail"`) and automatic web
checks fetch read and unread emails from all enabled accounts and classify them into the
existing categories. On Interview, both Check now buttons use calendar-only
collection (`/api/check` with `mode: "calendar"`, or `/api/interviews/sync`) and
read native calendar events using Microsoft Graph. The collector lists every
accessible calendar and reads each calendar's `calendarView`, following calendar
and event pagination. The default date window covers at least the previous year
and one year ahead, independently of the mail lookback. It is based on event dates, not invitation receipt dates.

`calendarView` expands recurring occurrences and exceptions. When an Ollama server is
configured in Settings, calendar sync uses its loaded model to classify each event
and extract company, role, interview stage, and explicitly identified interviewers.
It considers the combined title, description, organizer, named attendees, location,
and categories; there is no required keyword or fixed invitation format. Candidate
addresses, organizers, recruiters, and other attendees are not automatically treated
as interviewers. Holidays, personal appointments, and ordinary work meetings are
excluded. Ambiguous or incomplete interview details are marked **Needs review**.

Provider dates, recurrence identity, cancellation state, and meeting links remain
authoritative. Model output cannot change them. Safe recognized meeting links in
calendar descriptions are retained when structured meeting fields are absent.
All-day onsite interviews are supported; all-day duration alone does not mean holiday.

Without a configured model, collection still works with conservative interview
metadata checks. If analysis fails, recognizable interviews retain their native
schedule and previous extracted details; manual corrections always win. The sync
queues unfinished analysis for automatic retry. Successful
analysis is cached by event content and prompt version, so unchanged events do not
make repeat model requests. Description or attendee changes trigger reanalysis.
Calendar collection queues uncached events without waiting for inference. A saved
background queue resumes in small batches, even when automatic mail checks are off.
Upcoming events are prioritized within each account, and accounts take turns so a
large account cannot monopolize analysis. Failed events back off from 30 seconds to
30 minutes; a busy/unavailable model pauses requests for at least a minute. Untried
events continue before repeated failures. The configured classification deadline
bounds each batch rather than a full year of collection.

The calendar shows completed/remaining counts, retry reasons, and **Retry analysis
now**. Background batches update results without repeated completion toasts or
unrelated sourcing checks. The server must stay running; the browser may be closed.
Saved work survives restarts, including recovery of an interrupted worker claim.
A complete provider snapshot cancels tasks for removed events; an incomplete fetch
does not. Old queued results cannot overwrite a newer provider snapshot.

After upgrading from v2.20.0, refresh the calendar once to seed the saved queue for
previously deferred events. Further manual refreshes are not needed for the backlog.

After a complete successful provider sync, missing or unrelated bookings in the
collected window are hidden; incomplete provider syncs never remove missing events.
No events are edited or deleted in Outlook. Availability calculations still use all
busy appointments independently of interview classification.

Graph calendarView uses its default projection because revision timestamps do not
support `$select`. Event descriptions are converted to plain text and bounded by
Settings’ body-excerpt limit before being sent to the configured model, alongside
event metadata. Raw descriptions are not saved by this analysis cache; the cache
stores fingerprints and validated analysis results in the workspace database.
Pending queue entries retain native event metadata and the bounded description
excerpt so analysis can resume without repeated Graph fetches. This queued payload
is cleared after successful analysis or cancellation.
Calendar sync uses read-only `Calendars.Read`. It never reads inbox messages,
classifies emails, or creates message/classification rows. The saved-mail scan
endpoint remains retired (HTTP 410).

IMAP has no calendar event API. IMAP-only accounts report this explicitly without
opening a mailbox or falling back to reading messages. Native Google Calendar and
CalDAV account connections are not implemented.

## Microsoft permission migration

1. Add delegated **Calendars.Read** to the Microsoft application's API permissions.
   Mail.Read remains for the existing separate mail tools; no calendar write scope
   is requested.
2. In Accounts, click **Reconnect** beside each existing Outlook account and finish
   Microsoft's device-code consent with the same Microsoft account.
3. Configure your Ollama connection in Settings for semantic event analysis, then click **Check now**. Collection itself still works without a model.

Reconnection retains the account ID, local event records and account associations.
A different Microsoft identity is rejected. Tokens stay in the existing OS keyring.
Personal Microsoft accounts are supported; work/school tenants retain the existing
application limitation. Missing calendar consent is reported per account with a
reconnect instruction, without a message-based fallback.

## Storage and updates

Provider-neutral `CalendarBooking` records feed the existing local event/source
SQLite tables. No new message or classification rows are created. Source rows
contain the native event identifier and account association, with no stored email.
Schema 44 adds extracted interviewers and the content-based calendar analysis cache
without deleting existing events, source associations, or manual corrections.
Schema 45 adds the durable analysis queue, retry state, and worker leases.
Previous event history is preserved. Schema 19 retains organization pins and removal records and adds
manual process names without deleting events or messages;
timelines continue to derive events and messages from their existing tables.

Event UID plus occurrence identity deduplicates repeat imports. Provider revision
timestamps order native updates. Native events supersede older attachment-derived
records even when an old ICS sequence is larger. Reschedules and cancellation
updates retain local event identity. Manually corrected fields remain protected.
Invalid provider events are reported while subsequent valid events continue.
Paging limits produce an explicit incomplete-collection error rather than silently
claiming success. A booking omitted from a complete successful snapshot is hidden
within the synchronized window, while its stored history remains intact. It is
not rewritten as a cancellation.

Native timestamps are stored in UTC; original provider timezone metadata is retained
in the event notes. Provider times, locations, participants and join links appear in
the event details. No durations or bookings are inferred from prose. Previously
text-inferred records are excluded from the calendar while remaining stored locally.

## Calendar UI

The Outlook-style calendar uses sticky weekday headers, an hourly timeline with
half-hour guides, and an initial 8 AM scroll position. All 24 hours are available.
Overlapping appointments use separate lanes. Multi-day bookings are clipped per day.
View/date navigation and filters are retained in the URL. Split view separates
source accounts; Share copies a URL or exports a local ICS snapshot. Print and
expanded view are supported. These controls do not publish or modify remote events.
Upcoming and review panels are removed. Event editing changes local records only;
drag-to-reschedule and provider write synchronization are not implemented.

## Validation

- 134 backend tests, including native Graph requests, all booking kinds, multiple
  calendars and pagination, recurrence identities, reschedules/cancellations,
  calendar-only scopes, permission failures, IMAP rejection without mail reads,
  old ICS sequence migration, reconnect identity and account preservation.
- 86 frontend tests, including reconnect consent and removal of mail-scanning UI.
- 331 existing smoke assertions pass with an isolated in-memory keyring.
- Strict TypeScript and Vite production build pass.
- Chromium exercises the real web job, native Graph source with a mocked transport,
  real local database and calendar UI: seven bookings across two calendars, Teams
  join link, repeat imports, reschedule/cancellation, and desktop/mobile layout.
  No email source reader or message endpoint is used for collection.

These checks use isolated provider fixtures, not live Microsoft credentials or
production mailbox/calendar data. A real Microsoft account must grant the new
permission before its native events can be fetched.

### Manual processes and elapsed time

Use **Add process** with only a company or organization name. The process appears
immediately, including when it has no milestones. Names are unique ignoring case
and whitespace. Saved and subsequently collected events and messages match when
any word or number in the name appears in their details, ignoring case. Matching
checks event company/role/notes/participants and message subject, sender, full saved
body, snippet and summary. A single manual match takes priority over domain grouping;
multiple manual matches go to Unassigned. Matching is literal substring matching,
so short or generic names can collect broad results. Removed manual processes keep
their matching rules and stay hidden until restored. Pinning works for manual names.

Each panel shows elapsed days or weeks from its earliest calendar event to today,
with the first event date available on hover. Future bookings do not extend the
age. Empty processes show **No milestones yet**; processes containing only future
milestones show **Not started yet**. The age is independent of the selected window.

Processes start at their first calendar event. Messages before that event are excluded
from the timeline and its counts; saved mail is preserved. Manual processes without
a calendar event remain empty until one matches. Age also starts at the first
calendar event.

Panel colors represent elapsed process age from the first calendar event: green
under 1 week, teal from 1 to under 2 weeks, amber from 2 to under 4 weeks, orange
from 4 to under 6 weeks, and rose at 6 weeks or more. Empty and future-only
processes use slate. The panel border, background, line, and age label share this
color; milestone colors still indicate their timing. The age legend explains the
ranges, and changing the time window does not change a process's age or color.

Processes sort with pinned processes first, then oldest first by completed days
since the first calendar event. Equal ages sort by calendar-event count, highest
first, then organization name for a stable order. Empty and future-only processes
come after started processes within each pin group. Messages do not affect sorting.


### Outlook synchronization

On Interview, **Refresh** and **Check now** both collect current Outlook calendar
bookings. Automatic checks also collect calendar events. The default calendar
window covers the previous year (or the configured mail lookback if longer) and
the next year, independently of the usual two-day mail lookback.

A complete successful account snapshot hides bookings deleted from Outlook within
that window. Historical records and source details remain stored. Failed or
incomplete snapshots never remove bookings; copies still present in another
enabled account remain visible. Returning events reappear automatically. Outlook
updates clear removed meeting links/locations and can reinstate cancelled events;
explicit local corrections remain protected. Calendar collection is read-only
and never edits Outlook.

## Calendar event summary

The event dialog shows time in the selected display timezone, linked email accounts,
company, role, interview contacts, location, and a separate clickable full meeting URL when available. Accounts
and contacts are deduplicated; the candidate's linked email addresses are omitted
from the contact list. Organizer/contact information does not establish who will
conduct the interview.

Native calendar titles are not structured company data. When a calendar title was
stored as a fallback company, the summary keeps it as the dialog title and marks
the company as **Not provided**. Missing roles are also shown as **Not provided**;
these details are not guessed. Model analysis can fill supported details on the next calendar sync. **Edit details** allows local company, role, and interviewer corrections and event
removal. Technical source metadata and calendar notes stay out of the summary.
