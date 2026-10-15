# Meeting calendar

The admin-only Interview page displays local calendar bookings in Work week, Week,
Month and Day views. Named bidders are limited to their own sourcing sheets and payments. No production events are
seeded, and existing mail history is preserved.

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
The database schema and previous event history are preserved.

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
