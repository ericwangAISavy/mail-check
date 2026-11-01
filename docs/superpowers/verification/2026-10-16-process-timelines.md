# Horizontal interview process timelines

Replaces expanded event histories with a compact date-positioned timeline for each
organization. Calendar events are circular milestones; saved emails from that
organization's sender domain are square milestones. Closely spaced points use
separate lanes connected to the time axis. Preview information appears on hover,
focus or tap. Click/Enter activation focuses the preview, makes its actions
reachable by Tab, and Escape returns focus to the milestone. Previews follow
their anchor when scrolling or resizing.

Daily, Monday-based Weekly, Monthly and Two months windows use browser-local
calendar boundaries. Date/arrows/Today controls navigate the window. Start is
inclusive and end exclusive. Two months means the selected month and following
month. Pins persist in SQLite across admin sessions and devices, sort processes
first, and retain them even in an empty date window. Search still applies.

Saved mail joins only established calendar organization groups. It uses the latest
saved classification summary or a bounded text preview; no new provider or model
requests occur. Organization inference and ambiguous-domain Unassigned behavior
remain intact. Schema 17 adds pin storage; schema-16 event history is preserved.

## Verification

- Full backend suite: 227 passed, 59 subtests passed. Final process regression
  suite: 13 passed, including an additional schema-16 upgrade preservation test.
- Full frontend suite: 134 passed across 21 files.
- Standalone smoke: 331 passed, 0 failed.
- Production TypeScript/Vite build passed and bundled assets regenerated.
- `git diff --check` passed.

The existing Starlette/httpx deprecation warning remains. The passing frontend
account suite also emits jsdom's existing `window.open` not-implemented message.

Chromium used the real app, disposable SQLite and synthetic Graph responses.
Verified calendar collection, mixed event/email milestones, saved summary content,
hover and tap previews, Enter/Tab access to preview actions, Escape focus return,
pin ordering and persistence after reload, daily/weekly/monthly/two-month filters,
date navigation, pinned empty rows, ambiguous-domain search, event detail links,
and mobile width/horizontal scrolling. No page errors occurred. Desktop 1440×1000
and mobile 390×844 screenshots were inspected. Live Microsoft access and production
mailbox data were not used.

Independent review identified inaccessible portaled preview actions during keyboard
navigation; focus handling and a regression test resolve it. Browser checks exposed
a queued scroll event dismissing newly tapped previews; previews now reposition
instead of closing, with a regression test. Both fixes were verified in Chromium.
