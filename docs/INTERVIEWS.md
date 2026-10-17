# Meeting calendar

The admin-only Interview page displays local calendar bookings in Work week, Week,
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
checks fetch unread emails from all enabled accounts and classify them into the
existing categories. On Interview, both Check now buttons use calendar-only
collection (`/api/check` with `mode: "calendar"`, or `/api/interviews/sync`) and
read native calendar events using Microsoft Graph. The collector lists every
accessible calendar and reads each calendar's `calendarView`, following calendar
and event pagination. The date window runs from the configured lookback through
one year ahead. It is based on event dates, not invitation receipt dates.

`calendarView` expands recurring occurrences and exceptions. Bookings are accepted
regardless of title, organizer, meeting provider, or whether they have a join link.
Teams, Google Meet, Zoom, Webex, Skype, telephone and in-person bookings all use the
same collection path. This does not connect to Google Calendar itself: Google Meet
bookings must exist on a connected Outlook calendar.

Only event metadata is requested: title, start/end, original timezone, organizer,
attendees, location, online-meeting link/provider, cancellation and revision data.
The calendar client requests UTC timestamps and uses read-only `Calendars.Read`.
There are no inbox/message endpoints, attachment scans, email bodies, model calls,
or meeting-relevance classification in this flow. The saved-mail scan endpoint is
retired (HTTP 410), and its UI action and source-email reader have been removed
from the calendar. The separate CLI mail tools retain their existing workflow.

IMAP has no calendar event API. IMAP-only accounts report this explicitly without
opening a mailbox or falling back to reading messages. Native Google Calendar and
CalDAV account connections are not implemented.

## Microsoft permission migration

1. Add delegated **Calendars.Read** to the Microsoft application's API permissions.
   Mail.Read remains for the existing separate mail tools; no calendar write scope
   is requested.
2. In Accounts, click **Reconnect** beside each existing Outlook account and finish
   Microsoft's device-code consent with the same Microsoft account.
3. Click **Check now**. A model connection is not required.

Reconnection retains the account ID, local event records and account associations.
A different Microsoft identity is rejected. Tokens stay in the existing OS keyring.
Personal Microsoft accounts are supported; work/school tenants retain the existing
application limitation. Missing calendar consent is reported per account with a
reconnect instruction, without a message-based fallback.

## Storage and updates

Provider-neutral `CalendarBooking` records feed the existing local event/source
SQLite tables. No new message or classification rows are created. Source rows
contain the native event identifier and account association, with no stored email.
Previous event history is preserved. Schema 19 retains organization pins and removal records and adds
manual process names without deleting events or messages;
timelines continue to derive events and messages from their existing tables.

Event UID plus occurrence identity deduplicates repeat imports. Provider revision
timestamps order native updates. Native events supersede older attachment-derived
records even when an old ICS sequence is larger. Reschedules and cancellation
updates retain local event identity. Manually corrected fields remain protected.
Invalid provider events are reported while subsequent valid events continue.
Paging limits produce an explicit incomplete-collection error rather than silently
claiming success. Deletion of a booking that the provider entirely omits from its
calendar response is not inferred as a cancellation.

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
