# OfferPath version history

Generated from releases.json. Use tools/release.py to add a release.

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
