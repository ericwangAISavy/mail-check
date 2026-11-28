# Remembered page filters and views

Each page remembers its latest filters and view preferences while this browser tab
is open. Navigating to another page and returning restores those choices; reloading
the tab also preserves them when session storage is available.

Preferences are separate for each workspace, signed-in user, role and bidder.
Closing the tab ends this saved session. When storage is blocked or full, an
in-memory fallback still remembers preferences during navigation.

Remembered options include Dashboard and Triage filters/search, Interview calendar
filters/view/date, interview timeline and pipeline filters, payment week/bidder and
activity views, sourcing workbook/tab/day and per-tab find/filter/sort, and the
expanded bidder on Accounts. Explicit links with query parameters take priority.
Clearing a filter remains cleared. Back and Forward preserve visited URL choices.

Password fields, reply drafts, unsaved payment/rule edits, data-editing drafts,
modal dialogs, and message bodies are never saved by this mechanism. Data continues
to load through the normal permission-checked APIs; remembering a filter grants no
access to records. Invalid or obsolete saved preference values fall back to defaults.

Verification for this release: 401 frontend tests, 6 release metadata tests, type
checking and production build passed. Desktop/mobile browser checks exercised real
Triage navigation, reload, clear-filter behavior and identity separation with
synthetic API responses. No server-side business behavior or production data changed.
