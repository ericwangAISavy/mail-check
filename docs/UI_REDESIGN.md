# Cyber UI redesign and interaction review

The supplied dark dashboard image is the visual reference. The implementation keeps
the existing application, routes, APIs, authentication, SQLite schema, mail pipeline,
classification, credential storage, and scheduling rules. No Python application code
or API contracts were changed.

## Visual system

- Shared near-black/navy surfaces, cyan borders and focus rings, restrained purple
  secondary accents, panel corner details, and a subtle grid.
- Locally bundled Geist throughout headings, navigation, metrics, and body text.
  No remote font service, image dependency, Earth graphic, donut, or fabricated sparkline.
- Follow-up typography uses only four sizes across the app: 14px secondary text,
  16px body/controls, 20px section headings, and 26px page titles/metrics. These live
  in `frontend/src/typography.css`; scattered responsive font-size rules were removed.
- Timeline quick buttons select 1 week, 2 weeks, 1 month, or 3 months through the
  existing date filters. The date dropdown also supports 14 days and stays synchronized.
- The same buttons, panels, inputs, badges, navigation, dialogs, lists, and error/loading
  states across sign-in, Triage, Dashboard, Accounts, Settings, and message readers.
- Dark is the initial preference; the existing light/system theme controls still work.
- All four real metrics remain, including Unclassified. Category counts and filtering
  remain in the chart legend and message-explorer controls, including zero counts.
- Recent Mail Events uses the current page of stored mail, with received dates explicitly
  labeled. It is not a fabricated event log. The existing last-run summary is also shown.
- Account Status uses the existing account labels and, for admin, enabled/paused state.
  The API has no persistent live-health or per-account message-count field, so the UI
  does not invent a connection-health state or message count. Guests never request
  the admin accounts endpoint.

## Interaction mapping

| Component | Existing handler / state | API / server function / source |
| --- | --- | --- |
| Sidebar, breadcrumb, responsive navigation | React Router; Workspace collapsed/mobile state | Existing Triage, Dashboard, Accounts, Settings routes; role guards unchanged |
| Theme control | ThemeControl; localStorage `mailcheck.theme` | Existing dark/light/system preference |
| Sign in / Sign out | AuthGate; api.login / signOut | `/api/auth/login`, `/api/auth/session`, `/api/auth/logout`; existing file-backed auth |
| Password settings | PasswordSettings save | `/api/auth/password`; existing admin authorization and role-session revocation |
| Check now | JobStatus runCheck, existing pollNow | `/api/check` → `_run_check` → `check_once` |
| Auto-check toggle | JobStatus toggle | `/api/autocheck` → saved watch config and `_reschedule` |
| Next check / progress | JobStatus poll, Countdown | `/api/status` → `_job`, `_sched`, saved watch settings |
| Refresh | Existing dashboard query refetch | `/api/dashboard` → DashboardFilters and dashboard_data |
| Date range, account, status, advanced action | Existing update / URLSearchParams | Existing DashboardFilters parameters and SQL scope |
| Group by / chart grouping | Same URL `interval` and existing weekly aggregation | Existing daily API series; no new aggregation rules |
| Chart segment | focusChart | Existing `focus_date` / `focus_category`; explorer-only focus |
| Category legend / chips | Existing toggleCategory and category URL values | Existing category scope and count response |
| Search / reset / pagination | Existing query parameters and page controls | Existing search, page, page-size, and normalized API filters |
| Recent mail row / explorer row | Existing openMessage → Reader | `/api/messages/{pk}`; sanitized body and original metadata |
| Done / Restore / Undo | useDoneMutation and existing undo shortcuts | Existing `/api/messages/{pk}/handled` and `/api/messages/undo-last` |
| Retry classification | Existing Reader / ReclassifyBanner handlers | `/api/reclassify`; existing background job |
| Account filter labels | Existing dashboardAccounts query | `/api/dashboard/accounts` |
| Account details and status | Existing shared accounts query | `/api/accounts`; existing enabled/paused fields |
| Account Test / inclusion / removal | Existing AccountRow change | Existing `/api/accounts/{label}/test`, `/toggle`, `/delete` |
| IMAP provider lookup / add | Existing preset and submit operations | `/api/preset`, `/api/accounts`; unchanged provider and keyring behavior |
| Outlook device sign-in / status / cancel | Existing start / poll / cancel | Existing `/api/outlook/start`, `/status`, `/cancel` |
| Save settings / privacy acknowledgement | Existing settings payload and privacy operation | `/api/settings`; same setting names and persistence |
| Test model / detected model | Existing testModel and activeModel query | `/api/settings/test`, `/api/settings/model` |
| Rules | Existing addRule / removeRule mutations | Existing `/api/rules` and `/api/rules/{index}/delete` |
| Notifications | Existing permission, local preference, notification test and acknowledgement | Browser Notification API; existing `/api/notifications` and `/ack` |

## Confirmed UI bugs fixed

1. Dashboard Refresh announced success before the network request finished. It now
   reports the real outcome and shows a useful stale-results error on failure.
2. Dashboard query changes unmounted the whole view, including the search input.
   Previous results now remain visible while the next scope loads.
3. The search input did not follow URL history. It now synchronizes with navigation.
4. A focused date could remain outside a newly selected range and cause an API error.
   Date-range changes now clear obsolete focus parameters.
5. A weekly bucket could send a Monday before the selected date range. It now focuses
   the first visible day, preserving explorer-only day-focus semantics and leaving
   chart/metric scope unchanged. The weekly helper text explains this behavior.
6. Chart-level and segment-level click handlers could overwrite each other's category
   focus. Only the existing segment action now controls that selection.
7. Filtered legend colors used filtered positions rather than their series positions.
   The legend now uses the same color as the corresponding chart series.
8. Dashboard readers used incomplete row metadata instead of the full reader response.
   Reader now uses the real message metadata; Done/Undo and check completion invalidate
   the corresponding reader cache.
9. An immediately completed manual check could leave page data stale until the next
   status poll. Manual checks now trigger the existing shared polling handler, which
   invalidates the page queries on completion.
10. Saving scheduling settings did not promptly synchronize the header. The existing
    header polling handler now also responds to successful settings saves.
11. Provider lookup ran on every keystroke and late responses could replace a newer
    provider or manually entered server. Lookups are debounced, aborted on changes,
    and respect subsequent manual edits.
12. An account toggle remained available during another account action. It now disables
    while the action is pending, and account changes invalidate dashboard account labels.
13. Outlook polling/cancellation failures were swallowed. They now surface a useful
    message; a failed cancellation does not pretend the flow was cancelled.
14. Saving privacy acknowledgement discarded unrelated unsaved settings. It now retains
    those edits and rolls back the checkbox on failure. A general save also preserves
    edits made while the request was in flight.
15. Failed status polling could leave an "All systems ready" message visible. The
    header now identifies unavailable status instead.
16. Test connection used the saved model configuration even when the form showed a
    different unsaved URL. The control now asks for model changes to be saved first,
    so it cannot misleadingly test the previous server.

## Validation and limits

See the repository-root `design-qa.md` for screenshot comparison and browser evidence.
Automated regression coverage includes the existing suites plus focused Dashboard,
Accounts, Settings, and fast manual-check completion tests.

Populated browser checks use a separate SQLite/config directory under
`/workspace/.mail-check-design/fixture-runtime`, served on port 8766. Its synthetic
messages, process-local test keyring, and mailbox stand-in are test fixtures only;
they are not production application data or application code. The normal runtime
on port 8765 keeps its existing data and credentials.

The full smoke suite retains its pre-existing Outlook failure: `fetch_unread` does
not include `isRead eq false` in the Graph filter. That unrelated provider behavior
was deliberately left unchanged. Real external mailbox, Microsoft tenant, OS keyring,
and live Ollama acceptance remain unverified; the repository's stand-in integration
tests and isolated browser workflow exercise the application wiring without them.

## Changed source files

- `frontend/src/cyber.css`, `index.css`, `main.tsx`: shared tokens, themes, fonts and layout.
- `frontend/src/App.tsx`: existing header/navigation presentation and poll synchronization.
- `frontend/src/components/common.tsx`, `ui/button.tsx`, `ui/card.tsx`: reusable primitives
  and reader-query invalidation.
- `frontend/src/pages/dashboard.tsx`, `triage.tsx`, `accounts.tsx`, `settings.tsx`:
  shared styling, real dashboard information panels and the targeted fixes above.
- `frontend/src/App.test.tsx` and the added `pages/dashboard.test.tsx`,
  `accounts.test.tsx`, `settings.test.tsx`: regression coverage.
- `frontend/package.json`, `package-lock.json`: the locally bundled display font only.
- `mailcheck/web/frontend_dist/`: regenerated production UI and font assets.
