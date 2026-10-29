# OfferPath version history

Generated from releases.json. Use tools/release.py to add a release.

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
