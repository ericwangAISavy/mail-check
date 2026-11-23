# OfferPath version history

Generated from releases.json. Use tools/release.py to add a release.

## 3.17.3 — 2026-11-23

HTTP connection cleanup and sustained crash recovery

- Malformed requests on closing HTTP connections are safely disconnected without an asyncio callback traceback.
- After an unexpected server exit, automatic recovery retries failed replacements and pauses during repeated crashes before trying again.

## 3.17.2 — 2026-11-22

Busy database is deferred, slow write locks are named

- A calendar save that finds the database busy is retried later without counting as a failure or printing a traceback
- The server window names any process that holds the database write lock for more than 10 seconds

## 3.17.1 — 2026-11-22

Scheduled checks no longer repeat for account problems

- A scheduled check that finishes with problems on some accounts is no longer re-run five times; the problems stay on the Accounts page and the check runs again on its normal schedule

## 3.17.0 — 2026-11-22

Colored server window

- The server window colors messages by severity: red for errors, yellow for warnings, green for success, cyan for routine progress, white on red for critical

## 3.16.4 — 2026-11-21

Offline outages no longer burn retries

- When the internet or DNS is down, queued mail and calendar work now waits and is retried later instead of using up its attempts and being dropped

## 3.16.3 — 2026-11-21

Clean second Ctrl+C

- Pressing Ctrl+C again while the server is stopping no longer prints a traceback from the log follower

## 3.16.2 — 2026-11-21

Clearer shared worker logs

- Failed background jobs now log where the error was raised, and the repeated reconnect-for-read-marking warning is printed once per account instead of on every run

## 3.16.1 — 2026-11-21

Calendar saves survive a busy database

- Calendar events are no longer lost when another worker is writing; the database wait is longer and a locked save is retried

## 3.16.0 — 2026-11-21

Server window shows warnings and crashes

- The server window now shows warnings, errors and full tracebacks from every server process, labelled with the process name, instead of only startup lines. Everything is still saved in the log files.
- When a worker process dies on its own, the window reports it with the exit code explained in words (for example access violation, stack overflow or forcibly ended) and what the worker wrote before it stopped.
- Uncaught errors in any process, Python warnings and hard native crashes (with every thread's stack) are now recorded. Set OFFERPATH_CONSOLE_LOG to info, error or off to change how much the window shows.

## 3.15.5 — 2026-11-20

Clean shutdown on repeated Ctrl+C

- Pressing Ctrl+C again while the server is shutting down now stops it immediately with a short message instead of crashing with a traceback.

## 3.15.4 — 2026-11-20

Compact job matches on calendar events

- Possible job matches on a calendar event now show just the job title with its date, a Saved by or Applied by badge with the bidder's name, and the link; the match reasons, account and verification lines are gone.

## 3.15.3 — 2026-11-20

One profile quality chart

- Profile quality shows every account in a single chart, one line per account, with a switch between interview rate and rejection rate instead of a separate chart for each account.
- A table under the chart lists each account's applications and exact rates, doubles as the legend, and shows or hides an account's line when selected; the chart axis fits typical values so one thin week cannot flatten the lines.

## 3.15.2 — 2026-11-20

Profile quality from saved records

- Each account's interview rate is interview emails divided by received application emails, and its rejection rate is rejection emails divided by received application emails.
- The status is calculated from permanently saved records, not from mail received recently, so it no longer goes empty when an account has had no new mail for a week; it matches the application counts in Payments.
- Interview and rejection emails are now saved permanently from now on, and the page shows the day the comparison starts from.
- Redesigned the account cards with two rate tiles and the counts behind them, smooth area and bar charts, weekly grouping by default, and a clear message when an account has no application emails yet.

## 3.15.1 — 2026-11-20

Profile quality across all stored history

- Profile quality ratios and daily, weekly and monthly charts now cover the entire stored mail history for the selected accounts.

## 3.15.0 — 2026-11-20

Profile quality chart styles

- Switch each profile's quality trends between line and bar charts with the same interview and rejection email ratios.

## 3.14.0 — 2026-11-20

Profile quality trends

- Compare interview-related and rejection email rates for each account by day, week or month in place of the dashboard message explorer.

## 3.13.4 — 2026-11-20

Full-height sourcing spreadsheet

- The Job sourcing grid fills the available workspace even on empty days or sheets with only a few rows.

## 3.13.3 — 2026-11-20

More frequent shooting stars

- Twelve staggered shooting stars bring a new streak to the sign-in sky every second.

## 3.13.2 — 2026-11-20

Brighter shooting star trails

- Shooting stars on the sign-in screen are slightly brighter and leave longer trails.

## 3.13.1 — 2026-11-20

Shooting stars on sign-in

- Tiny tapered star fragments cross the mountain sky on staggered diagonal paths.

## 3.13.0 — 2026-11-20

Ambient lights on sign-in

- Tiny points of light drift slowly across the sign-in background when motion is enabled.

## 3.12.9 — 2026-11-20

Align the sign-in role selector

- The Admin and Bidder selector uses the full rounded field and a single focus outline.

## 3.12.8 — 2026-11-20

Single focus outline

- Text fields and shared buttons show a single clear keyboard focus outline.

## 3.12.7 — 2026-11-20

Clearer form interaction feedback

- Mail filters highlight the focused field and show when results are updating. Buttons give a subtle press response.

## 3.12.6 — 2026-11-20

Dropdown hover feedback

- Dropdowns and the calendar timezone picker smoothly highlight their borders on hover.

## 3.12.5 — 2026-11-20

Subtle button and tab transitions

- Buttons and tabs ease into their hover colors over 140 milliseconds. Inactive profile tabs also softly highlight their lower edge.

## 3.12.4 — 2026-11-20

Show stripes for unanalyzed calendar bookings

- The left stripe now follows each booking’s analysis status, including bookings with no review message.

## 3.12.3 — 2026-11-20

Hatched calendar event accent

- Calendar events awaiting detail analysis show diagonal stripes inside their left accent bar.

## 3.12.2 — 2026-11-20

Fit the sourcing table to the workspace

- Default text columns share the available width, and long job sheets scroll inside the table.

## 3.12.1 — 2026-11-20

Modern calendar event bars

- Calendar events are calm rounded cards with a soft tint and a gentle lift on hover.
- Past events are shown lightly transparent while upcoming ones stay bright; dashed outlines are gone, and unknown end times fade out softly at the bottom.

## 3.12.0 — 2026-11-20

Choose calendar colors per account

- The interview calendar has a Colors menu: pick one of eight colors for each account, or reset it to the automatic color.
- The chosen colors are saved for the workspace, so the browser and desktop app show the same colors.

## 3.11.5 — 2026-11-20

Tidier accounts and bidder forms

- Account rows read Outlook and Updated 10s ago, so the sync time is always visible, and only paused accounts show a status badge.
- Bidder payment, wallet and assignment fields no longer overlap or push Save buttons out of view, and the add bidder box has room to type.

## 3.11.4 — 2026-11-19

Reliable sync failure reasons

- A mailbox's Sync failing reason now stays visible until mail collection succeeds; a successful calendar sync no longer hides it.
- Mail that was collected is no longer reported as failing when only a follow-up step had a problem.

## 3.11.3 — 2026-11-19

Sync switch on each account

- Each connected account now has a Sync switch for collecting new mail as it arrives, replacing the separate Automatic updates list and the Include in checks switch.
- Turning Sync on for a paused account also includes it in checks again.

## 3.11.2 — 2026-11-19

Cleaner bidder management

- Bidders are now managed in one panel: the bidder list on the left and the selected bidder's profile, payment, wallet, web access and accounts on the right, so switching bidders takes one click and no longer pushes the page around.

## 3.11.1 — 2026-11-19

Clean reply editor focus

- The email reply editor shows one clean focus outline instead of a doubled line.

## 3.11.0 — 2026-11-19

See why automatic updates fail

- When automatic mail collection fails for a mailbox, its card now shows Live · failing and a short reason, such as an expired Microsoft sign-in, instead of only Not synced yet.
- The next successful collection clears the warning automatically.

## 3.10.4 — 2026-11-19

Clearer weekly refresh

- Refresh this week now says how many new checks it found, and the duplicate Fully rebuild this week button is gone (it ran the same refresh).
- Refreshing a week no longer rewrites blank Check cells, so people editing a sheet while Payments is open no longer get a sheet changed error.

## 3.10.3 — 2026-11-19

Pasted job rows start unchecked

- Copying job rows to another sheet no longer copies their Check status; pasted rows start unchecked and are checked by that account's own confirmations.

## 3.10.2 — 2026-11-19

Keep job sourcing rows for pasting

- Delete in Job sourcing now clears the selected rows' contents and keeps the rows, so you can paste the next batch of links into them.
- Pasting into a day that has no job rows adds the copied rows to that day.
- Deleting a day's rows always leaves a blank input row, so other days are never left without a row to paste into.

## 3.10.1 — 2026-11-19

Monitoring reliability fixes

- Job activity is no longer lost on Windows when the monitoring page reads its files at the moment a worker saves them.
- Workers save monitoring counts at most every 10 seconds instead of rewriting the whole day's file for each event.
- The monitoring page's own refreshes are no longer counted as traffic.
- Chart values are announced to screen readers, hover stays valid after switching the range, and the range is locked while live updates are paused.

## 3.10.0 — 2026-11-19

Graph-based system monitoring

- System monitoring now shows graphs for traffic, server errors, response time, job outcomes and queue backlog over the last 1, 6 or 24 hours.
- Key numbers (requests, error rate, p95 response time, jobs completed, retries and failures, backlog) appear as tiles with trend lines.
- Service health is a compact strip with ready counts, and a per-stage table shows failure rates, job time and live queues.
- Recent problems lists retries and failures; the long explanations and dot timeline are gone.
- Job activity is recorded more reliably and with less disk work.

## 3.9.10 — 2026-11-18

Less explanatory text on Bidder management

- Remove the activity chart caption, the deduction rule description and the unallocated-replies subtitle to save space.

## 3.9.9 — 2026-11-18

Simpler Sourcing toolbar

- Keep only the previous/next day, date and Today controls on Sourcing, moved into the top toolbar; the second tool row is removed and the toolbar wraps neatly on smaller screens.

## 3.9.8 — 2026-11-18

Simpler Interview calendar toolbar

- Remove the calendar's top tool row and keep Check now at the end of the date row, which is now the calendar's top row.

## 3.9.7 — 2026-11-18

Instant page navigation feedback

- Highlight the page you click in the sidebar and header immediately, with a slim progress bar while it opens, instead of appearing to do nothing.
- Start loading a page as soon as you point at or focus its link, so most pages open without waiting.

## 3.9.6 — 2026-11-18

Round status indicators

- Fix the grey square around status and footer dots, and restore theme glows on buttons, dialogs and counts that the dark theme had overridden.

## 3.9.5 — 2026-11-18

Sourcing sheet fits the window

- Keep the Sourcing sheet and its account tabs within the window at every header height.
- Give dark-theme table headers a solid background so rows no longer show through them while scrolling.

## 3.9.4 — 2026-11-18

Readable Dashboard metrics

- Show a visible label beside each Dashboard metric icon and arrange the four totals to fit the available space.

## 3.9.3 — 2026-11-18

Restore Dashboard compatibility across workspace workers

- Open the Dashboard even when a workspace worker runs an older version during an update.

## 3.9.2 — 2026-11-18

Load Dashboard totals before optional details

- Start loading Dashboard history without waiting for the chart and reader bundles, and load message rows when the explorer is opened.

## 3.9.1 — 2026-11-18

Start OfferPath from a fresh Windows session

- Prompt for the local RabbitMQ password when a cold-start launcher has no AMQP_URL, and check the connection before startup.

## 3.9.0 — 2026-11-18

One-click Windows server restart

- Double-click restart.bat to restart the running OfferPath server or start it when stopped.

## 3.8.5 — 2026-11-18

Reduce repeated inbox and realtime reads

- Compute Inbox totals and category counts together, and coalesce realtime updates while a refresh is running.

## 3.8.4 — 2026-11-18

Scale worker health checks by process

- Check each shared API worker once per sweep so a temporary slowdown cannot trigger repeated health failures from different workspaces in that sweep.
- Reduce repeated Windows lock setup during database access.

## 3.8.3 — 2026-11-18

Load workspace pages before header totals

- Open pages without waiting for Inbox and application totals, and compress large page responses over the gateway.

## 3.8.2 — 2026-11-18

Faster workspace loading and steadier traffic

- Show workspace navigation while the page finishes loading and download smaller sign-in images.
- Reduce repeated bidder Inbox requests and limit expensive database reads when a workspace is busy.
- Return saved settings immediately and reload workspace schedules in the background.

## 3.8.1 — 2026-11-18

Faster first load after updates

- Compress the app's scripts and styles before sending them, so the first visit after an update loads about three times faster over the tunnel.
- Show a calm 'Still opening OfferPath…' notice instead of a connection warning when the first load is slow; the app opens on its own as soon as it is ready.

## 3.8.0 — 2026-11-18

Calendar sync with Check now and tidier header

- Check now also collects calendar events, like scheduled checks; real-time updates already sync calendars with mail.
- Keep the header on one tidy row at every desktop width, with a cleaner two-row layout on phones.
- Remove the auto-check button from the header; automatic checks stay available in Settings and are off by default.
- Calmer primary buttons, an icon-only sidebar collapse button in the sidebar's bottom-right corner, and aligned dashboard filter buttons.

## 3.7.3 — 2026-11-18

Matching selects and buttons

- Give dark-theme dropdowns and secondary buttons the same glass fill, gradient rim and hover glow as outline buttons.

## 3.7.2 — 2026-11-18

Softer dark theme glow

- Tone down the dark theme's gradient edges, glows and highlights for a calmer look.

## 3.7.1 — 2026-11-18

Consistent hover and focus states

- Keep dark-theme buttons, the active navigation item and tabs looking the same on hover and after, with smooth glow changes instead of flat or grey flashes.
- Restore visible keyboard focus on dark-theme buttons, remove glow from disabled buttons, and keep borderless panels borderless.
- Show red borders on invalid fields in both themes, including while hovered or focused.

## 3.7.0 — 2026-11-18

Glowing dark theme

- Refresh the dark theme with luminous gradient edges on panels and dialogs, cyan-to-blue borders, lit icon tiles and an ambient background glow.
- Highlight the active navigation item, primary buttons, counts and focused fields with the brand glow. The light theme is unchanged.

## 3.6.5 — 2026-11-18

Roomier header identity

- Add more space between the logo, the OfferPath title and the version badge, scaling it to fit narrower sidebars.

## 3.6.4 — 2026-11-18

Aligned header and sidebar collapse

- Align the header breadcrumb with the page at every window width and sidebar state.
- Move the sidebar collapse control from the header to the bottom of the sidebar.

## 3.6.3 — 2026-11-18

Full-width header

- Move the OfferPath logo, title and version into a header that spans the full width, with the sidebar beneath it on the left.

## 3.6.2 — 2026-11-18

Brighter sidebar identity

- Restyle the sidebar logo, OfferPath wordmark and version badge with the brand glow, bold italic two-tone lettering and a highlighted version pill.

## 3.6.1 — 2026-11-18

Shorter, plainer interface text

- Remove technical and how-it-works explanations across the app, keeping labels, errors and the instructions you need to act.
- Shorten confirmations, empty states, Settings descriptions and check status messages.

## 3.6.0 — 2026-11-18

Let real-time collection replace redundant checks

- Scheduled checks skip accounts real-time collection is keeping current and slow to every 30 minutes once it covers every account; they speed back up automatically if real-time stops. Check now still checks everything.
- Bidder live Inbox checks poll only assigned accounts real-time is not covering.
- Replace check countdowns with how recently mail was updated: the top bar shows Updated 2 min ago, and the bidder Inbox shows when every assigned mailbox was last collected, turning amber after 5 minutes.

## 3.5.8 — 2026-11-18

Compact live Inbox status

- Show the bidder Inbox live status as one compact, colour-coded line with a state pill (Live, Checking, Retrying, Delayed, Offline or Off), the next check countdown and the last update.
- Flag live checks that are running late instead of showing due now indefinitely; the explanation moves to an info tooltip.

## 3.5.7 — 2026-11-18

Keep live Inbox checks healthy during read update retries

- Outlook read update retries no longer make bidder live Inbox checks report failure or slow down to every minute; new mail keeps arriving every 30 seconds.
- Show today's last successful live check as a time, matching the next check.

## 3.5.6 — 2026-11-18

One last-synced time per account

- Account cards show one Last synced time covering both full mail checks and real-time collection, instead of a Last mail check time that ignored real-time updates.
- Accounts with real-time collection on show a Live marker; the Automatic updates panel no longer repeats the sync time.

## 3.5.5 — 2026-11-18

Bidder Inbox in received order

- Show the bidder Inbox as one list ordered by when each email was received, newest first, instead of grouping it by category.

## 3.5.4 — 2026-11-18

Compact Outlook read update badge

- Show pending Outlook read updates on Accounts as a small orange count badge instead of a long description; hover it for details and reconnect guidance.

## 3.5.3 — 2026-11-18

Clearer Outlook read updates after reconnecting

- Apply queued Outlook read updates immediately after an account is reconnected instead of waiting for the next mail check.
- Ask to reconnect only when Microsoft refuses read permission; otherwise show that emails will be marked read on the next check.
- Stop retrying read updates Microsoft permanently rejects, so they no longer keep the Accounts warning visible.

## 3.5.2 — 2026-11-18

Keep Google sign-in out of a full Credential Manager

- On Windows, Google Sheets sign-in and its OAuth client settings are now stored in encrypted files instead of Credential Manager, so connecting Google no longer fails when Credential Manager is full.
- Existing Google connections move to the new files automatically and free their Credential Manager entries.

## 3.5.1 — 2026-11-18

Reconnect Outlook when Credential Manager is full

- On Windows, Outlook sign-in tokens are now stored in one encrypted file per account instead of several Credential Manager entries, so connecting or reconnecting accounts no longer fails when Credential Manager is full.
- Existing Outlook sign-ins move to the new files automatically and free their Credential Manager entries; accounts stay connected.

## 3.5.0 — 2026-11-18

Show all mail in the bidder Inbox

- Bidders now see classified mail in every category for their assigned accounts, not only info requests and application confirmations.
- Filter the bidder Inbox by any category that has messages.

## 3.4.0 — 2026-11-18

Application confirmations in bidder Inbox

- Bidders now see Application received messages alongside Info requests for their assigned accounts.
- Filter the bidder Inbox by Info request or Application received, or view both together.

## 3.3.1 — 2026-11-18

Keep link-history cleanup within its selection

- Remove only selected links from retained import snapshots during history cleanup, preserving unrelated imported rows and operation records.
- Roll back cleanup safely when a retained import snapshot cannot be read.

## 3.3.0 — 2026-11-18

Manage sourcing link history from Accounts

- Let admins preview and clear sourcing link history per email account and bidder, including deleted bidders, with optional sourcing-date filters.
- Show affected and checked-link counts before permanent deletion, with concurrent-edit protection and safe retries.

## 3.2.15 — 2026-11-18

Extend application matching to ten days

- Match application confirmations within ten Chicago calendar days of the sourcing date, including manual checks, automatic verification, and bounded payment refreshes.

## 3.2.14 — 2026-11-18

Modernize sign-in typography

- Use locally hosted Manrope typography with refined heading weights, quieter supporting text, and restrained silver-blue accents on the sign-in page.

## 3.2.13 — 2026-11-18

Compact sign-in and expose Outlook read-sync failures

- Reduce the sign-in panel, branding, fields, and button to a more natural size.
- Show pending Outlook read updates in Accounts and preserve mail-collection read-sync errors so accounts requiring Mail.ReadWrite consent can be identified.

## 3.2.12 — 2026-11-18

Remove the sign-in logo frame

- Remove the inherited rounded border, tile background, and shadow around the sign-in logo.

## 3.2.11 — 2026-11-18

Lighten the OfferPath logo finish

- Lighten the shared logo to an icy silver-blue palette with soft cyan highlights for the updated application design.

## 3.2.10 — 2026-11-18

Deepen and sharpen the OfferPath logo

- Refine the logo with richer sapphire-blue tones, controlled highlights, and a cleaner high-resolution transparent asset throughout the application.

## 3.2.9 — 2026-11-18

Use the supplied neon loop logo

- Replace the approximate arrow mark with the supplied open-loop logo design across sign-in, navigation, startup, and the browser icon.

## 3.2.8 — 2026-11-18

Match the mountain sunrise sign-in design

- Refine sign-in branding, glass panel, rounded fields, and metallic blue button to match the supplied design while retaining the existing background.

## 3.2.7 — 2026-11-18

Refine the OfferPath application mark

- Update the shared application mark with a metallic silver-blue finish, dark rounded tile, and cyan highlights inspired by the new brand design.

## 3.2.6 — 2026-11-18

Center the sign-in form independently

- Center the sign-in form itself in the viewport with OfferPath branding positioned above it, while keeping the complete layout visible on small screens.

## 3.2.5 — 2026-11-18

Center the sign-in panel

- Remove promotional text and milestone badges over the sign-in artwork and center the sign-in panel vertically and horizontally.

## 3.2.4 — 2026-11-18

Refresh sign-in background

- Publish the updated sign-in background in the production frontend assets.

## 3.2.3 — 2026-11-18

Close workspace schema probe connections

- Close SQLite schema-check connections immediately after workspace validation to prevent retained database handles during repeated requests and failed upgrades.

## 3.2.2 — 2026-11-18

Recover workspaces after Outlook upgrade

- Automatically apply the additive Outlook read-task migration when existing shared workspaces open, preventing schema-50 workspaces from returning server errors after updating.

## 3.2.1 — 2026-11-17

Avoid redundant Outlook read updates

- Preserve Outlook read state during collection so already-read messages are not repeatedly updated and completed retry tasks are cleared.
- Allow later Outlook read updates to proceed when an individual message update is rejected, while preserving failed tasks for retry.

## 3.2.0 — 2026-11-17

Automatically mark collected Outlook emails read

- Automatically mark Outlook emails as read after they are saved, with durable retries for failed updates.
- Reconnect existing Outlook accounts to grant Mail.ReadWrite permission.

## 3.1.2 — 2026-11-16

Recover workspace mail collection checkpoints

- Recover automatic email collection from malformed or future-dated workspace checkpoints while preserving valid catch-up windows.
- Identify failed shared jobs by workspace, account, and error type without logging private provider responses.

## 3.1.1 — 2026-11-16

Safe Windows monitoring probes

- Fix a Windows monitoring liveness probe that could generate console interrupt events instead of checking model process state.

## 3.1.0 — 2026-11-16

Visual status history

- Replace the monitoring event table with an interactive timeline grouped by component and status, with selectable event details.

## 3.0.3 — 2026-11-16

System-wide monitoring

- Focus monitoring on shared service pools, global queue backlog, and event flow; remove per-admin health and sync cards.

## 3.0.2 — 2026-11-16

Close live event streams before server shutdown

- Close browser event streams before the HTTP shutdown deadline and finish asynchronous subscription cleanup without cancelling ordinary API requests.
- Log the shutdown signal or Windows listener failure so unexpected exits can be distinguished from shutdown cleanup errors.

## 3.0.1 — 2026-11-15

Protect shared worker retries and sign-in lifecycle

- Prevent duplicate completed manual checks and keep queued retries from being replaced or overwriting newer status.
- Defer busy shared workers without exhausting provider retries, separate collection/model queue budgets, and reject reclassification of disabled accounts.
- Cancel and drain pending sign-ins on shutdown, revalidate workspace access before credential writes, and ignore notifications for suspended workspaces.
- Restore the original-workspace backup check before shared worker startup.

## 3.0.0 — 2026-11-15

Shared RabbitMQ worker architecture

- Add an opt-in fixed shared API and RabbitMQ job pool while keeping admin databases and credentials isolated.
- Keep the current runtime as the default; switching requires draining existing jobs and does not migrate application database schemas.
- Show shared component, data, and event flows in owner system monitoring.

## 2.29.0 — 2026-11-14

Owner system monitoring

- Add an owner-only System monitoring page with health checks across all admin workspaces, queue and sync status, and a live operational event flow.
- Record bounded operational telemetry without blocking collection, classification, or event delivery.

## 2.28.2 — 2026-11-13

Maintenance version update

- Update the OfferPath application and bundled console version to 2.28.2.

## 2.28.1 — 2026-11-13

Protect concurrent workflows and live updates

- Prevent encoded gateway paths from bypassing owner-only API restrictions and avoid worker replacement races.
- Guard replies against stale messages, uncertain delivery, and unrelated Done updates; preserve account data when credential cleanup fails.
- Preserve concurrent settings changes and prevent pending form saves from discarding edits.
- Refresh business views through bounded transactional realtime hints and include Junk Email in Outlook notifications.
- Correct calendar reschedule state, deadlines, time-zone ordering, review decisions, and date-boundary validation.

## 2.28.0 — 2026-11-13

Automatic email and calendar updates

- Opt in to background email and Outlook calendar collection using durable Redis Streams jobs, recovery checks, and independent classification.
- Update open workspace pages through authenticated server-sent events with replay, scoped access, and separate traffic limits.
- Configure Microsoft notification subscriptions and monitor per-account automatic sync health from Accounts.

## 2.27.18 — 2026-11-12

Keep gateway and page loading responsive

- Keep session replacement database work off the gateway serving loop so login contention does not stall other requests.
- Cancel obsolete page reads and status polls, and ignore canceled responses before they can change the active session.
- Preserve working Outlook credentials when a reconnect is canceled, fails, or is superseded by a newer sign-in.

## 2.27.17 — 2026-11-10

Bound local worker connects and recover dropped page-read sockets

- Prevent stalled local worker connects from occupying gateway capacity for minutes, and expire idle connections before workers close them.
- Recover a dropped GET/HEAD worker connection once within the page deadline, revalidating sessions and never replaying writes or slow reads.
- Log sanitized worker connection failures and Cloudflare request references for origin/tunnel diagnosis.

## 2.27.16 — 2026-11-10

Recover Triage reads after temporary Cloudflare connection failures

- Retry temporary Triage connection failures with bounded backoff while retaining filters and cached mail; never replay outgoing actions.
- Show safe Cloudflare error codes and request references for HTTP 530 so tunnel failures can be diagnosed accurately.

## 2.27.15 — 2026-11-10

Recover missing startup styles and parse import wrappers safely

- Keep startup covered until required styles are loaded; recover stylesheet failures with one bounded reload and a clear manual retry.
- Wrap only parsed JavaScript import expressions, preserving ordinary text and Vite's lazy CSS dependency graph.

## 2.27.14 — 2026-11-10

Restore lazy page styles while retaining download retries

- Preserve Vite's CSS and preload dependency graph when applying page-file retries, restoring calendar, dashboard, sourcing and pipeline layouts.

## 2.27.13 — 2026-11-10

Keep blocked optional analytics from aborting startup

- Ignore CSP-blocked Cloudflare analytics and unrelated extension scripts during startup, while retaining recovery for OfferPath files and reporting genuine app initialization errors.

## 2.27.12 — 2026-11-10

Fix stalled startup recovery and page reveal timing

- Keep slow-start recovery available after React mounts, ignore HTML whitespace when checking startup, and reveal ready pages correctly after class changes or frequent live updates.

## 2.27.11 — 2026-11-10

Retry transient page-file downloads before leaving the page

- Retry failed lazy page imports twice using fresh request URLs before showing recovery, while preserving the current page and filters. Code errors still fail immediately.

## 2.27.10 — 2026-11-10

Keep startup smooth with one consistent loading screen

- Use a single branded startup screen through sign-in checks, workspace loading and the initial page, with a gentle reveal and reduced-motion support.

## 2.27.9 — 2026-11-10

Recover failed page-module loads after outages and updates

- Recover failed lazy-loaded page files with a bounded, connection-checked reload that preserves filters and deep links, plus a retry screen while the origin is unavailable.
- Prevent truncated successful static responses when a hashed asset disappears during deployment; return a clean non-cacheable error instead.

## 2.27.8 — 2026-11-10

Preserve valid nested Windows static paths

- Allow Windows-normalized filesystem separators for valid nested assets while continuing to reject malformed URL separators.
- Reject reserved Windows device filenames and trailing-dot/space aliases before static-file lookup.

## 2.27.7 — 2026-11-10

Reject malformed Windows asset paths safely

- Return HTTP 404 for invalid static-file URLs such as JavaScript stack locations instead of raising Windows invalid-filename exceptions, while preserving normal asset serving and genuine I/O diagnostics.

## 2.27.6 — 2026-11-10

Harden clipboard parsing and job-link duplicate checks

- Preserve word boundaries in copied HTML blocks and reject incomplete quoted clipboard cells without changing the sheet.
- Preserve repeated URL parameter value order so distinct links are not incorrectly filtered as duplicates.

## 2.27.5 — 2026-11-10

Remove embedded line breaks from pasted job fields

- Automatically flatten cell-internal line breaks in pasted company names and roles and rejoin wrapped job URLs, while preserving spreadsheet row boundaries.
- Apply the same cleanup to saved and imported job fields before validation and filtering.

## 2.27.4 — 2026-11-10

Keep pasted job rows aligned

- Preserve spreadsheet HTML cell boundaries when pasting wrapped or multiline company names, roles and job links, with TSV fallback and bounded text-only parsing.

## 2.27.3 — 2026-11-10

Bound gateway authentication and startup waits

- Include authentication in page-read deadlines, return retryable responses for session storage outages, and keep public sign-in assets independent of database availability.
- Keep startup backup I/O away from worker heartbeat locks and enforce a wall-clock limit on readiness polling without interrupting dispatched writes.

## 2.27.2 — 2026-11-10

Deeper gateway and worker recovery fixes

- Keep session reads available during control writes and recover unresponsive workspace listeners without restarting healthy or overloaded workers.
- Avoid heartbeat lock contention during worker cleanup, preserve replacement workers, and complete shutdown cleanup after background errors.

## 2.27.1 — 2026-11-10

Recover stalled HTTP origins and keep gateway monitoring responsive

- Move workspace discovery off the HTTP event loop and keep worker monitoring alive after transient storage errors.
- The Windows start script now probes the local origin, recovers crashed or non-responsive child servers with bounded retries, and records recovery diagnostics.

## 2.27.0 — 2026-11-10

Separate owner and admin workspace mail schedules

- Configure independent automatic mail-check intervals for the owner’s workspace and other admin workspaces, with quick choices, validation and clear live Inbox guidance.

## 2.26.2 — 2026-11-10

Bidder Inbox live refresh reliability

- Show the next live Inbox check time and countdown, successful freshness, failure retries and disabled reasons in a responsive status panel.
- Keep loaded Inbox messages during temporary outages, preserve access-revocation protection, correct fixed-category filter counts and reset reader position when switching messages.

## 2.26.1 — 2026-11-09

Invitation matching review fixes

- Preserve saved job destinations, avoid false URL matches with repeated parameters, handle invalid dates safely, and expose refresh failures without losing loaded matches.

## 2.26.0 — 2026-11-09

Calendar invitation job history matches

- Calendar invitation details suggest matching historical job links and the bidder who recorded each application, with confidence and multiple candidates.

## 2.25.1 — 2026-11-09

Make Queue retries and Undo notifications safe

- Reuse a durable confirmation ID for bulk Queue retries so a lost response cannot clear newly arrived mail or reapply an undone action.
- Discard notifications and Undo actions from previous workspaces or sessions, including delayed completion callbacks.

## 2.25.0 — 2026-11-09

Clear the Queue in one bulk action

- Add an admin Queue action to mark the entire workspace backlog as done, including messages beyond current filters and the loaded list, with confirmation.
- Restore bulk completion as one Undo action while preserving later individual changes, existing completed messages, and future arrivals. Emails are not deleted and provider read status is unchanged.

## 2.24.7 — 2026-11-09

Fix account presets, backup listing and manual reply recovery

- Clear stale automatic IMAP server details immediately when changing mailbox addresses, while preserving subsequent manual edits.
- Keep the backup list usable when an archive contains a malformed manifest, preserving the archive file.
- Handle malformed Outlook reply metadata without leaving unsent requests stuck or weakening uncertain-delivery protection.

## 2.24.6 — 2026-11-09

Speed up page loading and recover from temporary outages

- Keep open workspaces and unsaved input during temporary refresh failures, with an explicit connection retry.
- Avoid write-lock waits for admin page reads, share concurrent workspace-startup waits, and bound page-read processing without retrying writes.
- Search sparse job-sheet values without building full styled editor snapshots, reducing search time and memory use.

## 2.24.5 — 2026-11-09

Clarify duplicate Windows startup and preserve launch flags

- Detect an existing gateway before opening the dashboard, distinguish lock contention from file access failures, and avoid growing Windows lock files on failed starts.
- Forward Windows start-script arguments and preserve its exit status when using domain and tunnel options.

## 2.24.4 — 2026-11-09

Improve availability under concurrent users and preserve active filters

- Separate bounded active-request admission from idle connection headroom, reserving capacity for worker health checks and model releases.
- Retry temporary shared-model release failures and keep payment pages readable during concurrent database writes.
- Preserve filters and URL state when clicking the current sidebar page or home title again.

## 2.24.3 — 2026-11-09

Refresh daily counts after bidder assignment changes

- Refresh the header daily-count badge immediately after assigning or removing accounts and other bidder-management changes.

## 2.24.2 — 2026-11-09

Allow removal of previously paid account assignments

- Admins can remove past or ongoing account assignments even when their dates include a recorded payment. Saved payment amounts and counts, emails, and job sheets remain intact.

## 2.24.1 — 2026-11-09

Close startup and session race conditions

- Prevent concurrent workspace startup requests from stopping healthy workers, and clean up failed process launches.
- Recover shared model capacity when lease validation is interrupted; keep authentication database reads off the HTTP event loop.
- Discard stale account responses after session changes and prevent delayed password or sign-in responses from restoring a signed-out session.

## 2.24.0 — 2026-11-09

Improve active bidder Inbox speed and server reliability

- Check currently assigned mailboxes about every 30 seconds while bidder Inboxes are active, with faster visible-page refresh and unchanged access/classification rules.
- Prevent healthy workspace workers from terminating during gateway overload and always release background job locks after completion or startup failures.
- Reject malformed Outlook responses without advancing failed checkpoints; fix Interviews error retry to reload its list.
- Avoid unnecessary Job sourcing writes during navigation; bound large sheet responses and keep CSV export independent of dense snapshots.
- Show the app recovery screen for lazy page-load failures while navigating.

## 2.23.1 — 2026-11-08

Recover frontend startup failures without a stuck loading screen

- Use safe defaults when browser storage is unavailable so sign-in and workspace startup can continue.
- Retry failed startup assets once with fresh HTML, then show a readable recovery action instead of an indefinite Starting OfferPath screen.

## 2.23.0 — 2026-11-08

Remember page filters and view preferences

- Restore each page's filters, search, dates and view choices when navigating away and returning, scoped to the signed-in user and workspace.
- Use tab-session storage with safe defaults and an in-memory fallback; leave passwords and editing drafts unsaved.

## 2.22.1 — 2026-11-06

Improve bidder inbox refresh and check schedule

- Show bidders the next automatic mail check time and hide cached message details when access can no longer be confirmed.

## 2.22.0 — 2026-11-06

Add a restricted bidder inbox using Info request

- Reuse Triage for bidders to read only Info request messages from currently assigned accounts and mark them Done, with server-enforced access and no reply or mailbox-management permissions. No classification categories or rules changed.

## 2.21.15 — 2026-11-05

Reconcile activity graphs with checked application totals

- Use payment accounting for By day graphs and show the selected-day split between timed confirmations and checked links without receipt times.
- Clarify that confirmation-time lines and hourly heatmaps show only recorded receipt times; preserve existing checks and timestamps.

## 2.21.14 — 2026-11-05

Recover invalid calendar analysis responses and bound retries

- Normalize common model formats, use larger output budgets, and repair invalid or truncated calendar JSON once without inventing interview details.
- Pause repeatedly invalid events as needs review, preserve their schedules and manual edits, and allow explicit retry without repeating successful analyses.

## 2.21.13 — 2026-11-05

Match delayed company-only confirmations and explain unchecked links

- Company-only replies prefer the most recent eligible source date, including next-day confirmations, while preserving checked links and reserved receipts.
- Check applications now shows row-level reasons for unresolved links instead of leaving silent unchecked boxes.

## 2.21.12 — 2026-11-05

Fix company-only confirmations blocked by checked job history

- For confirmations without a role, match a unique unchecked company/account job on the receipt date before considering other source dates; checked rows cannot block new company-only matches, and bound receipts remain reserved.

## 2.21.11 — 2026-11-05

Fix shared payment status display and add match diagnostics

- Show recorded paid amounts separately from calculated payment amounts for bidders, and enforce viewer row scope in the report serializer.
- Add a read-only company/account matching report to investigate unchecked confirmations such as HP without modifying checks or saved receipt dates.

## 2.21.10 — 2026-11-05

Show permitted team payment status to bidders

- Payment-visible bidders can see payment amounts and recorded status for coworkers when team work visibility is enabled, while coworker wallet details, rates, notes and accounts remain private.

## 2.21.9 — 2026-11-05

Broaden matching only for unchecked applications

- Restore bidirectional whole-phrase company and role containment with exact-match priority, while preserving checked links, receipt bindings and historical confirmation dates across all checking paths.

## 2.21.8 — 2026-11-05

Preserve checked links across every checking path

- Auto-checks, periodic checks, refreshes and manual Check applications now process only unchecked links, preserving saved checkmarks, receipt bindings and confirmation dates even after matching rules change.

## 2.21.7 — 2026-11-05

Make full rebuild preserve checked applications

- Fully rebuild checks only unchecked links; existing checkmarks, receipt bindings, and confirmation dates remain unchanged, and bound receipts cannot be reassigned.

## 2.21.6 — 2026-11-05

Restore complete v2.21.0 checkpoint

- Restore the complete application code and behavior from bc02a75, before the company and role containment matching changes and subsequent checking and recovery changes. Database records are not reverted.

## 2.21.5 — 2026-11-05

Recover rebuild-cleared application checks

- Add a preview-first recovery command for audit-listed cleared checks, with explicit sourcing-date credit, transactional validation, and safe reruns.

## 2.21.4 — 2026-11-05

Preserve recorded checks and stop payment report writes

- Make payment reports read-only and preserve existing checks and receipt dates during ordinary verification.
- Disable destructive full rebuild requests and add a read-only application-count audit for recovery investigations.

## 2.21.3 — 2026-11-05

Restore checking behavior from v2.21.0

- Restore the application matching and confirmation attribution logic from v2.21.0, before company/role containment changes.
- Keep calendar analysis, background queue, dashboard permissions, UI improvements, and published release history unchanged. This restores code behavior; stored database history is not rolled back.

## 2.21.2 — 2026-11-05

Keep expanded matching additive and daily counts stable

- Preserve legacy exact company/role matches before considering broader name containment, including valid saved receipt reservations during rebuilds.
- Keep legitimate saved confirmation dates instead of moving historical counts to newly discovered earlier aliases or duplicate receipts.
- Adding receipt evidence to an already manually checked job preserves its original manual accounting day; unchanged refreshes do not rewrite tab revisions.

## 2.21.1 — 2026-11-05

Match contained company and role names

- Application confirmations match company names when either normalized name contains the other as a whole-word phrase, including Inspira Financial Trust LLC and Inspira Financial.
- Role names support the same bidirectional containment when no exact eligible role match exists. Ambiguous matches, account/date limits, receipt reservations, and saved payments remain protected.

## 2.21.0 — 2026-11-04

Resume calendar analysis automatically

- Calendar collection saves a durable analysis queue and finishes without waiting for the model; background batches resume automatically even when mail auto-check is disabled.
- Analysis prioritizes upcoming events, rotates across accounts, and retries failed events with backoff without restarting completed work or re-fetching calendars.
- Show completed and remaining analysis counts with retry reasons and a Retry analysis now action. Background batches update the calendar without repeated completion toasts or unrelated sourcing checks.

## 2.20.0 — 2026-11-04

Analyze calendar interview details with the configured model

- Calendar sync analyzes event titles, descriptions, organizers, and attendees to identify interviews and extract company, role, stage, and actual interviewers without requiring fixed title patterns.
- Successful analysis is cached; changed events are reanalyzed, while unavailable or malformed analysis is deferred for retry without losing native schedules or manual corrections.
- Calendar times, cancellations, and meeting links remain authoritative. Interviewer corrections are editable and protected from automated updates.

## 2.19.7 — 2026-11-04

Fix spreadsheet drag selection regressions

- Preserve the original range anchor for Shift-click selection after drag cleanup.
- Start edge auto-scrolling only after the pointer actually moves, so holding an ordinary click cannot expand the selection.
- Calculate drag-selection bounds from the usable grid viewport, excluding borders and the horizontal scrollbar.

## 2.19.6 — 2026-11-04

Auto-scroll spreadsheet drag selection

- Dragging a sourcing row selection near the top or bottom edge now scrolls continuously and extends selection beyond the visible viewport, including wrapped rows.
- Auto-scrolling stops on mouse release, window blur, view changes, or leaving the sheet.

## 2.19.5 — 2026-11-04

Dismiss completed link import progress

- The sourcing progress bar briefly shows 100% after the saved sheet is ready, then automatically disappears.

## 2.19.4 — 2026-11-04

Show explicit meeting links

- Calendar event details display the full meeting URL in its own clickable Meeting link field, separate from location.

## 2.19.3 — 2026-11-04

Simplify interview calendar details

- Interview dialogs focus on time, email account, company, role, interview contacts, and location or a meeting link.
- Deduplicate calendar accounts and contacts, exclude the candidate’s own email addresses, and stop labeling fallback calendar titles as companies.
- Move event removal into Edit details and remove technical metadata and repeated source-account sections from the summary.

## 2.19.2 — 2026-11-04

Unify Accounts section headers

- Accounts uses consistent Settings-style section headings with relevant inbox, connection, team, and visibility icons.
- Bidder management and visibility headings sit above their cards, matching connected accounts and provider sections.

## 2.19.1 — 2026-11-04

Fix visibility refresh and settings reads

- Opening Accounts loads bidder settings without running application matching or scanning weekly payments.
- Bidder pages refresh saved visibility settings and discard cached team graphs when access changes.
- Preserve visibility drafts on failed reloads and keep successfully saved options when a follow-up read fails.

## 2.19.0 — 2026-11-04

Scoped bidder dashboards and visibility controls

- Bidders can view dashboard graphs for their assigned accounts without message lists or account status.
- Accounts now groups providers, bidder management, and per-bidder payment and coworker-work visibility options in Settings-style panels.
- Payment cells show gross totals before deductions and calculated net totals after deductions; saved records remain available in the admin editor.
- Enforce bidder identity and data redaction in both standalone and private workspace APIs; reject stale visibility edits.

## 2.18.2 — 2026-11-04

Match header badge to checked daily application totals

- Use today's checked application total for the header badge, matching the first number in the daily breakdown instead of received replies.

## 2.18.1 — 2026-11-04

Protect deduction edits and payment review from stale data

- Preserve unsaved deduction drafts during refresh and reject conflicting rule edits.
- Require payment review again when deduction rules or calculated net amounts change, including daily-count changes with the same weekly total.

## 2.18.0 — 2026-11-04

Add workspace daily minimum and payment deductions

- Admins can save a daily checked-application minimum and flat dollar deduction for all bidders.
- Highlight completed assigned weekdays below the minimum and deduct their fees from calculated pay, preserving recorded payments and manual confirmed amounts.

## 2.17.3 — 2026-11-04

Collect interview-related calendar events only

- Exclude holidays, birthdays and unrelated calendar meetings while keeping interview-tagged events, recruiter calls and recognized interview updates.
- Hide previously imported unrelated bookings after a successful sync without deleting saved records or changing Outlook; preserve complete-sync safeguards and availability checks.

## 2.17.2 — 2026-11-04

Show checked counts only to bidders

- Limit bidder payment views and API responses to checked-application counts; admins retain checked applications and received replies.
- Hide received-reply header badges and historical review-count notices from bidders on Bidder management, including expanded account rows and totals.

## 2.17.1 — 2026-11-04

Harden checked-application matching and optimize accounting

- Require unambiguous account-wide job matches, preserve meaningful company and role distinctions, and prevent new automatic receipt reuse across jobs.
- Fix removed-bidder reply weights, zero-dollar settlements, mixed-offset time filters and stale payment-count warnings while preserving saved records.
- Group accounting queries, add date and message indexes, and avoid unchanged report and refresh writes; add a reproducible synthetic performance benchmark.

## 2.17.0 — 2026-11-04

Base bidder payments on checked applications

- Calculate weekly application totals and pay from checked job-link rows using the editable payment rate and adjustment, preserving recorded payments and manual amount overrides.
- Show checked applications first in bright text and received replies second in grey throughout bidder and account breakdowns; update totals, payment review counts and documentation.

## 2.16.0 — 2026-11-04

Search Triage mail by text

- Search subjects, senders, companies, roles, summaries and stored message text within the selected Triage filters.

## 2.15.0 — 2026-11-04

Add Today to Triage time ranges

- Filter Triage mail to today using America/Chicago midnight, matching bidder accounting, or choose the last 24 hours.

## 2.14.2 — 2026-11-04

Restore v2.13.5 classification behavior

- Restore the v2.13.5 implementation, including improved email classification, before later reconciliation and classifier rollback changes.
- Require automatic version updates for future runtime changes and preserve published history when restoring older behavior.

## 2.14.1 — 2026-11-04

Preserve historical receipt counts when reclassification fails

- Keep previous valid email labels and receipt estimates when historical model attempts fail; report the failures in run logs.
- Avoid loading message bodies during historical reclassification preflight.

## 2.14.0 — 2026-11-04

Restore original classification and rebuild historical estimates

- Remove application reconciliation and platform-copy deductions; restore original email classification behavior.
- Add admin actions to reclassify a week or all stored emails, log the run and rebuild estimates while preserving saved payments and manual checks.

## 2.13.7 — 2026-11-04

Fix platform and employer receipt double counting

- Count a confirmed platform/employer receipt pair once while preserving both application-received emails, interview detection and raw evidence.
- Correct daily badges and estimated payment counts consistently; keep existing recorded payments unchanged and retain reversible copy evidence.

## 2.13.6 — 2026-11-04

Reconcile confirmation emails with verified applications

- Separate raw receipt emails, verified applications, possible extra confirmations and unmatched receipts while keeping receipt-based payments unchanged.
- Prevent one receipt from checking multiple jobs, review repeated links across dates and improve safe seniority title matching.

## 2.13.5 — 2026-11-04

Keep activity chart tooltips fully readable

- Prevent bidder activity tooltips from being clipped by charts; keep them inside the viewport with scrollable lists.

## 2.13.4 — 2026-11-04

Harden on-premises authentication and Cloudflare Tunnel deployment

- Remove implicit default owner credentials, prevent failed-login budget resets, and enforce bounded HTTP requests with browser security policies.
- Add loopback-only tunnel startup with HTTPS cookies and a documented origin firewall and Cloudflare Access deployment path.

## 2.13.3 — 2026-11-04

Improve interview and application receipt classification

- Protect important mail from sender-only noise filtering and improve bounded interview context and classification validation.
- Preserve stored mail labels during ordinary checks and provide a rollback reference and synthetic evaluation corpus.

## 2.13.2 — 2026-11-03

Daily application badge across workspace pages

- Keep the daily application-confirmation badge visible on all workspace pages and mobile headers, including Admin management and Settings recovery.

## 2.13.1 — 2026-11-03

Clipboard, privacy and sourcing save fixes

- Preserve normal text copy and paste while editing a sourcing cell, while keeping whole-row copying outside editors.
- Load bidder editor forms only when first expanded and retain drafts afterward.
- Mask international and quoted email addresses in bidder-management display labels.
- Limit checked-row protection queries to the rows being saved, avoiding scans of unrelated sourcing history.

## 2.13.0 — 2026-11-03

Streamlined bidder management and sourcing rows

- Open one bidder editor at a time and mask account emails in Bidder management.
- Keep replies manual by removing the assisted drafting interface and generation APIs.
- Reduce the sign-in layout size while preserving viewport fitting.
- Select, copy and delete whole sourcing rows; checked rows have distinct styling and locked cell contents.

## 2.12.0 — 2026-11-03

Per-account role filters and Junk/Spam collection

- Add a Roles by account section to Job link filters, with independent blocked role keywords for each email account and matching across its new job rows.
- Include read and unread messages from Outlook Inbox and Junk Email and configured IMAP folders plus detected Junk/Spam, with safe checkpoint backfill and folder status reporting.

## 2.11.1 — 2026-11-03

Fitted sign-in and unique bidder usernames

- Sign-in scales to fit the available viewport without page scrolling, including smaller and zoomed screens.
- Bidders sign in with their username alone; duplicate names are rejected across admin workspaces when registering, renaming or enabling access.

## 2.11.0 — 2026-11-03

Removable admin workspaces and reliable Outlook tests

- Owners can remove added admin workspaces, stop their jobs and revoke access while retaining stored data offline.
- Outlook connection tests now check Inbox access with the existing mail permission, avoiding false profile-permission warnings.

## 2.10.3 — 2026-11-03

Private username sign-in and refreshed login design

- Type usernames instead of selecting published account names; account directories now require authentication.
- Refresh the responsive sign-in layout with a dark glass panel and password visibility control.

## 2.10.2 — 2026-11-02

Simplify collapsed bidder rows

- Show only bidder names and combined work totals in collapsed rows. Email account names appear in the expanded account detail rows.

## 2.10.1 — 2026-11-02

Harden retry windows and speed up bidder reports

- Honor a wider first-check lookback after a failed attempt. Load account checkpoints and bidder payment overrides in bulk, and reuse indexed assignment and account totals when building reports.

## 2.10.0 — 2026-11-02

Separate bidder work by email account

- Expand a bidder in the daily breakdown to see each account’s daily estimated confirmations, checked applications, and weekly total. Shared-account figures use that bidder’s allocated share.

## 2.9.0 — 2026-11-02

Resume mail checks from saved checkpoints

- Choose a fixed lookback window or resume each account from its last successful check. Manual and automatic mail checks share the saved mode.
- Keep per-account checkpoints across restarts and backups, preserve failed checks for retry, and show the last successful mail-check timestamp on account cards.

## 2.8.0 — 2026-11-01

Search and remember calendar timezones

- Type to find a calendar timezone, select it with the mouse or keyboard, and confirm it is saved for future browser visits. Show a warning when browser storage is blocked.

## 2.7.1 — 2026-11-01

Harden calendar display and mailbox reconnects

- Ignore malformed event dates in calendar weekend notices and close IMAP connections after failed sign-in or folder selection.

## 2.7.0 — 2026-11-01

Reconnect Gmail and IMAP mailboxes

- Reconnect existing Gmail and other IMAP accounts with a new app password. The connection is tested before credentials are saved, preserving mailbox history and assignments.

## 2.6.1 — 2026-11-01

Keep info requests out of the action queue

- Info request emails remain available in All mail but no longer appear in the Queue, its category filters, or action counts.

## 2.6.0 — 2026-11-01

Selectable interview calendar timezone

- Choose and save a calendar display timezone, with consistent event positions, date grouping, details, and shared links.

## 2.5.1 — 2026-10-31

Explain and resolve missing bidder payment amounts

- Show an explicit missing-rate explanation instead of unexplained payment dashes, with an admin Set rate action directly on Bidder management.
- Refresh estimated and payable amounts after saving a rate while preserving paid amounts, manual overrides and read-only bidder access.

## 2.5.0 — 2026-10-31

Clear interview opportunity tracking

- Track separate interview opportunities with confirmed stages, outcomes, attendance, tasks and evidence-backed next actions.
- Replace the default interview-process timeline with a compact worklist, four filters and progressively disclosed detail; keep the legacy timeline available.
- Review existing evidence and reminders before activation, preserve corrections and history, and keep calendar and mail data scoped to each profile.

## 2.4.6 — 2026-10-30

Windows HTTP listener reliability

- Use the native Windows IOCP event loop instead of the forced selector loop that could repeatedly log WinError 10022 and stop accepting requests.
- Finish cleanup after closing-connection resets and shut down clearly if a Windows listening socket fails, while keeping application errors visible.

## 2.4.5 — 2026-10-30

Cleaner sourcing toolbar

- Remove thin vertical dividers between job-sourcing toolbar button groups.

## 2.4.4 — 2026-10-30

Job filtering progress

- Show live row-based progress while pasted jobs and CSV imports are filtered for duplicate links and blocked companies.
- Show 100 percent only once the saved filtered sheet is rendered, with clear failure states that preserve existing content.

## 2.4.3 — 2026-10-30

Faster calendar pages and resilient page loading

- Batch calendar source resolution to avoid repeated full-history scans and database queries on calendar and interview process pages.
- Avoid unused full-mail reads on process pages and load Triage code only when its route is opened.
- Prevent overlapping status polls and bound page-read requests with a clear timeout while preserving write completion behavior.

## 2.4.2 — 2026-10-30

Prevent endless spreadsheet loading

- Prevent overlapping sheet refreshes from discarding slow responses and leaving the spreadsheet loading indefinitely.
- Cancel obsolete sheet requests and show a retryable error after 30 seconds while preserving existing data and drafts.

## 2.4.1 — 2026-10-30

Reliable Outlook calendar synchronization

- Refresh now collects current Outlook events instead of only reloading saved data.
- Reconcile deleted bookings after complete successful calendar snapshots, preserve other account copies and manual corrections, and apply updated meeting details.
- Correct Microsoft Graph calendar requests and sync a year of calendar history independently of the mail lookback.

## 2.4.0 — 2026-10-29

Portable installation backup and restore

- Owner-only plain ZIP backups include the original database, all admin workspaces, settings, and sign-in accounts.
- Daily automatic backups retain seven successful archives by default, with owner-managed scheduling and downloads.
- Offline restore validates files and databases, rebases paths, preserves business status, creates rollback backups, and supports interrupted-restore recovery.
- Restored installations use fresh credential namespaces and require mail-account reconnection.

## 2.3.26 — 2026-10-29

Check early applications on future job lists

- Match recent confirmations to pre-registered future job dates during automatic checks and manual Check applications, preserving account and role matching.
- Include future rows in selected-week refresh and rebuild while keeping completion counts on the actual Chicago receipt date.
- Show future-dated checked totals in the manual verification result without changing scheduled job dates.

## 2.3.25 — 2026-10-29

Full-height triage reading area

- Remove excess bottom spacing and allow the triage mail list and reader to fill the available content height.

## 2.3.24 — 2026-10-29

Retention safety and faster activity reporting

- Protect the whole date-based fetch window from pruning so early-day messages keep their saved Done state.
- Reuse confirmation data and batch-load checkpoint samples to reduce database work without changing graph counts.
- Keep the graph's default date within the selected payment week and reset the day selection when changing weeks.

## 2.3.23 — 2026-10-29

Midnight-to-midnight bidder activity

- Use Chicago calendar days, from 12 AM to the next 12 AM, for confirmation graphs and check-run timelines to align dates with the daily breakdown.
- Use today's date before 6 AM and honor 23-hour and 25-hour daylight-saving days.

## 2.3.22 — 2026-10-29

Aligned check controls and scheduled calendar collection

- Match Check now and Auto-check button heights, spacing, typography, and corner styling.
- Automatic checks now collect native calendar events and inbox mail together, reporting calendar failures without stopping mail collection.

## 2.3.21 — 2026-10-29

Owner-visible admin online status

- Show Online or Offline for each admin based on recent visible browser activity, independently of workspace server health.
- Keep Admin management and presence listings owner-only; expire presence after 90 seconds and clear it when access is revoked.

## 2.3.20 — 2026-10-29

Collect read and unread inbox messages

- Normal mail checks now include read and unread messages for Outlook and IMAP within the configured lookback, without changing mailbox read status.
- Keep full message bodies and Outlook links for inclusive checks, and follow every mail page rather than silently stopping after 2,000 messages.
- Report fetched messages accurately instead of labeling all fetched mail as unread.

## 2.3.19 — 2026-10-28

Distinctive OfferPath sign-in branding

- Place a larger decorated OfferPath mark and wordmark above the sign-in panel, with responsive sizing and theme-aware lighting.

## 2.3.18 — 2026-10-28

Content-only workspace scrolling

- Keep the workspace header and banner outside the main page scrollbar while preserving dedicated calendar and sourcing scroll areas.

## 2.3.17 — 2026-10-28

Simplified bidder week controls

- Remove visible Week of and Bidder labels while preserving accessible control names.

## 2.3.16 — 2026-10-28

Consistent sourcing toolbar surface

- Use one continuous theme-aware background across date navigation and editing controls.

## 2.3.15 — 2026-10-28

Bottom-aligned triage controls

- Align mail-view tabs and header controls to the bottom of the triage heading block.

## 2.3.14 — 2026-10-28

Unified bidder totals and week filters

- Place Today, weekly estimated confirmations, and recorded payments beside right-aligned week and bidder controls in a single compact desktop row.

## 2.3.13 — 2026-10-28

Unified job sourcing command bar

- Combine date navigation and editing tools in one compact desktop row while retaining accessible controls on smaller screens.

## 2.3.12 — 2026-10-28

Balanced triage header spacing

- Group mail tabs beside the heading and align filters, counts, and Undo in a compact continuous header.

## 2.3.11 — 2026-10-28

Single-row triage navigation

- Center mail-view tabs, filters, and message count beside the triage heading on wide screens, with responsive wrapping on smaller screens.

## 2.3.10 — 2026-10-28

Sign-in availability and pending request safeguards

- Prevent sign-in until a valid enabled account is selected and its directory is available.
- Lock account and password controls during sign-in to avoid conflicting submissions.

## 2.3.9 — 2026-10-28

Compact workspace and admin account selection

- Reduced heading sizes, toolbar spacing, and summary card height across the workspace.
- Choose an enabled admin username from a sign-in selector, with password authentication preserved.
- Simplified sign-in and moved workbook creation into a collapsible section.

## 2.3.8 — 2026-10-28

Fixed job sourcing column headers

- Replaced spreadsheet letters and the duplicate header row with fixed Company, Role, Job link and Check headings, and removed the Insert/edit menu while preserving job editing, paste and CSV workflows.

## 2.3.7 — 2026-10-28

Modern Dashboard activity chart

- Redesigned the main Dashboard chart with rounded gradient stacks, accurate total badges, a subtle trend overlay, polished tooltips and legend, and responsive range controls.

## 2.3.6 — 2026-10-28

Reliable workspace and page recovery

- Fixed owner Settings recovery when bootstrap fails and added a way to clear invalid Dashboard filters.
- Fixed overlapping admin suspension and re-enabling that could leave an enabled workspace stopped.

## 2.3.5 — 2026-10-28

Clear gateway error recovery

- Replaced raw proxy HTML and malformed responses with concise connection errors, preserved API validation messages and CSV downloads, and verified Dashboard recovery without automatically retrying writes.

## 2.3.4 — 2026-10-28

Professional workspace design

- Refined the entire interface with calm slate and white surfaces, clearer typography, neutral dividers, cohesive cards, controls, tables, dialogs, and responsive layouts.
- Improved visual hierarchy across dashboards, sourcing, calendars, accounts, bidder management, Settings, and admin workspaces while preserving existing actions and access permissions.

## 2.3.3 — 2026-10-28

More space for sidebar navigation

- Removed the sidebar's privacy card and repeated application/account footer to give navigation more room.

## 2.3.2 — 2026-10-28

Refined sidebar selection

- Refined sidebar navigation with soft selected surfaces, a slim accent rail, inset icon emphasis, quieter badges, and distinct hover and keyboard-focus states in both themes.

## 2.3.1 — 2026-10-28

Clearer sidebar navigation icons

- Replaced repeated and mismatched sidebar icons with workflow, briefcase, mailbox, settings gear, and admin shield symbols.

## 2.3.0 — 2026-10-28

Read-only bidder job sourcing

- Bidders can browse their own saved sourcing workbook by date and account tab, search their jobs, and copy links or a day's rows without editing or refreshing data.

## 2.2.0 — 2026-10-28

Read-only bidder team accounts

- Added Admin and Bidder sign-in options with workspace-qualified bidder names and admin-managed passwords.
- Bidders can view their admin's whole team on Dashboard and Bidder management, with server-enforced read-only access and revocable sessions.

## 2.1.3 — 2026-10-28

Refined OfferPath identity

- Refined the OfferPath icon with a sculpted ascending-path mark, a navy tile, and a cyan-to-blue finish across the app and browser tab.

## 2.1.2 — 2026-10-28

Consistent light and dark themes

- Improved shared scrollbars, keyboard focus, form controls, selection colors, and theme-specific chart contrast.
- Fixed light-mode calendar colors and date-input styling while preserving each account's calendar color identity.

## 2.1.1 — 2026-10-28

Clearer version history

- Improved release history with colored category dots, readable labels, clearer release cards, and a latest-version highlight.

## 2.1.0 — 2026-10-28

OfferPath workspace release

- Isolated admin workspaces with owner-managed accounts and shared settings.
- AI-assisted email drafts for follow-ups, availability, and rescheduling, with manual review and sending.
- Unified interview calendars and interview-process follow-up actions.
- Bidder management with weekly confirmation estimates, editable payments, wallet information, and copyable payment reports.
- Selected-week refresh and full rebuild of automatic application matches.
- Job sourcing filters for duplicate links and blocked companies.
- Faster gateway connections, cached application assets, and optimized weekly reconciliation.
- Visible application version and update history. Version tracking begins with this release.
