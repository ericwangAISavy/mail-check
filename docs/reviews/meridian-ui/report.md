# OfferPath interface: research and craftsmanship report

Covers 3.34.2 to 3.34.7 on `architecture/rabbitmq-shared-workers`, on top of the
3.34.0 redesign and the 3.34.1 state pass. Presentation only. The rules are in
[specification.md](specification.md); per-fix evidence is in
[craftsmanship-3.34.2.md](craftsmanship-3.34.2.md) and the `r3/` to `r6/` folders.

Status words: **researched** (sources inspected), **implemented** (in CSS),
**verified** (rendered and checked), **blocked** (no usable source or needs code).

## 1. Research coverage by module

Product screens came from official help and documentation articles that embed
real interface screenshots. All were public; no account was used.

| Module | Product interfaces inspected | Design-system guidance | Gate (2 products) |
| --- | --- | --- | --- |
| Shell, navigation | Linear (docs: Inbox, Triage, settings), Front (help: new inbox) | Atlassian elevation, Spectrum app frame | Met |
| Triage | Linear Inbox, Front inbox | Primer ActionList, Carbon structured list | Met |
| Dashboard, Bidder analytics | Grafana (time series, heatmap), Linear Insights, Datadog (time series) | Carbon data viz (anatomy, axes, legends, color) | Met |
| Interview calendar | Fantastical (help), Google Calendar (2024 redesign post) | W3C APG grid | Met |
| Interview pipeline | Ashby (candidate pipeline, activity status) | Carbon data table | One product only (blocked) |
| Job sourcing, Job links | Clay (University docs), Notion (table views) | AG Grid theming, W3C APG grid | Met |
| Settings | Linear (preferences, notifications), Vercel (environment variables) | Carbon form, Radix, Primer FormControl, Helios | Met |
| Accounts, Admin | Vercel (members, roles), Linear (settings list) | Helios, Atlassian lozenge | Met |
| Dialogs | Vercel (role dialog), Google Calendar (event dialog) | Radix dialog, Primer dialog | Met |
| Sign-in | None (Linear and Mercury pages rendered empty; Vercel text only) | Primer border tokens | Blocked |
| Bidder management (finance) | Linear Insights table only | Carbon data table | One product only (blocked) |
| Loading, feedback | None with screenshots | Primer spinner, skeleton, banner | Blocked |

## 2. Component-family coverage

Researched with sources: buttons, text fields, selects, switches, dialogs,
badges and lozenges, status indicators, tables, spreadsheet cells, selection
and focus, calendar events, chart axes and legends, heatmaps, toasts, loading
(Primer spinner delay and skeleton text, Carbon skeleton guidance).

Reviewed in renders without outside research (3.34.6): menus (calendar colors),
avatars (bidders, senders), pagination (Job links), chart tooltips, scrollbars.
No defect found in these. Date pickers are native browser controls; only their
field box is styled.

## 3. Inspected references

Product: linear.app/docs/inbox, /docs/triage, /docs/display-options,
/docs/account-preferences, /docs/notifications, /docs/insights;
help.front.com/en/articles/3889728; docs.ashbyhq.com/candidate-pipeline,
/understanding-candidate-activity-statuses; university.clay.com/docs/manage-cell-data;
notion.com/help/tables; flexibits.com/fantastical/help/calendar-views;
workspaceupdates.googleblog.com/2024/10/new-look-and-feel-and-dark-mode-google-calendar.html;
grafana.com/docs/grafana/latest/panels-visualizations/visualizations/time-series/
and /heatmap/; docs.datadoghq.com/dashboards/widgets/timeseries/;
vercel.com/docs/projects/environment-variables, /docs/rbac/managing-team-members.

Design systems: primer.style (color, button, label, dialog, banner, spinner,
skeleton, action list, form control); carbondesignsystem.com (data table, form,
structured list, button, data-viz anatomy, axes, legends, color palettes);
atlassian.design (elevation, badge and lozenge examples); radix-ui.com/themes
(dialog, text field, switch, select, badge, tooltip); helios.hashicorp.design
(text input); w3.org/WAI/ARIA/apg (grid, treegrid); ag-grid.com (theming,
compactness, colors).

## 4. Significant findings

1. Linear and Front show one-line previews and right-aligned times; OfferPath
   wrapped previews to two lines, costing a message per screen.
2. Linear and Front show navigation counts as plain figures; OfferPath tinted
   them in the brand color, which is reserved for selection and action.
3. Clay and Notion put status in its own cell and never recolor row content;
   OfferPath recolored every link in checked rows green.
4. Clay rings the focused cell; OfferPath's row mode showed no focused cell for
   keyboard users (15 focus stops without an indicator).
5. Fantastical and Google Calendar mark today with a filled date; both align
   hour labels to the grid.
6. Grafana and Linear Insights show no boxed per-bar values; OfferPath put a
   bordered pill on every bar.
7. Ashby pairs every status color with words; OfferPath's pipeline status has
   no attribute to color by (needs code).
8. Vercel and Linear give each settings group its own action and right-aligned
   controls; OfferPath already follows this.

## 5. Decisions taken from research

| Finding | Treatment | Status |
| --- | --- | --- |
| 1 | Triage preview clamped to one line (full text stays in the reader and the DOM) | Verified |
| 2 | Plain sidebar counts, foreground when active | Verified |
| 3 | Checked rows: green edge, number and check mark only; normal links and fill | Verified |
| 4 | Keyboard-only focus ring on spreadsheet cells and headers in row mode | Verified |
| 5 | Filled today mark; right-aligned hour labels kept below their line | Verified |
| 6 | Bar totals as plain figures; values kept | Verified |
| 7 | 3.34.7 adds `data-status` to the pipeline status pill; Active cyan, On hold amber, Offer received and Accepted green, closed outcomes a muted ring, always beside the word | Verified |
| Loading flashed for fast loads and gave no sense of shape | 300 ms delay, cyan spinner, three-line placeholder (Primer, Carbon); still when reduced motion is on | Verified (`r7/loading.png`) |
| Sign-in error was a saturated magenta block unlike every other error | Same tint, red edge and text as in-app errors | Verified (`r7/signin-error.png`) |
| Pressed buttons moved 2 px (two rules stacked) | One 1 px nudge, already off for reduced motion | Verified (`r7/pressed.png`) |
| High contrast: selected spreadsheet row text drawn black on a black backplate | Selected cells opt out of the backplate and use Highlight / HighlightText | Verified (`r7/high-contrast-grid.png`) |
| Earlier passes | Triage urgency dot, aligned summary figures, Paused amber, event detail hue, disclosure style, quieter sign-in border, shadow scale, compact and stacked bidder table, phone calendar and section menus, offline ring, Sync label, tertiary Link history | Verified |

## 6–7. Comparative and before/after screenshots

`r3/` (3.34.2), `r4/` (3.34.3), `r5/` (3.34.4), `r6/` (3.34.5): before on the
left in each image. Reference product screenshots are not stored in the
repository; they are at the URLs in section 3.

## 8. Interaction states

- Keyboard focus: 306 focus stops on 10 pages, both themes, every one with a
  visible indicator after the fix (15 missing before, all in spreadsheets).
- Hover: rendered for primary, outline, tertiary and remove buttons, message
  rows, table rows, navigation, text fields and dropdowns. Dropdown hover was
  cyan and became neutral to match fields.
- Selected, checked, selected-and-checked, unchecked: rendered in the
  spreadsheet with mixed data (`r6/grid-states.png`).
- Disabled and read-only: rendered in dialogs, Admin and Settings.
- Error: rendered toast and inline error.
- Pressed: rendered for primary, outline and segmented buttons (`r7/pressed.png`).
- Loading: rendered with held server responses on Dashboard, Bidder management
  and Accounts (`r7/loading.png`).
- High contrast (forced colors, emulated in Chrome): Triage, Sourcing,
  Settings, Dashboard, Calendar and Accounts rendered; one defect fixed.
- Not rendered: spreadsheet editing mode (hidden by the app).

## 9. UI assessment

The language is coherent: one brand color for action and selection, status
always with a word or shape, separate channels for hover, selection, focus and
done. Weakest areas: sign-in (artwork-led, no product reference; its error now
matches the app), Interview pipeline (status not colorable). No score is given.

## 10. UX assessment (scripted, not human testing)

Same data, 3.34.0 build vs. current:

| Measure | 3.34.0 | 3.34.5 |
| --- | --- | --- |
| Triage messages fully visible, 1440 / 800 / 390 px | 5 / 5 / 3 | 6 / 6 / 4 |
| Phone calendar: share of each event title visible | 20 % | 43 % |
| Bidder table width hidden at 800 px | 126 px | 0 px |
| Bidder table width hidden at 390 px | 476 px | 306 px |
| Phone page scroll to reach the table end | 377 px | 483 px (cost of stacked amounts) |
| Tab presses to first message / Date range / Copy links | 21 / 17 / 27 | unchanged |
| Reply and Done visible; account actions visible | yes; 6 of 6 | unchanged |

No people were tested. Task effort beyond these measures was not assessed.

## 11. Functional parity

20 page-and-width views, 901 to 903 controls depending on the seeded data: no
differences in controls, disabled states or the Tab order, against the 3.34.0
build on the same data (rerun for 3.34.5, 3.34.6 and 3.34.7).

3.34.7 is the only release with markup changes, all without behavior change:
`data-status` on the pipeline status pill; `className="inline-loading"` on 13
loading lines (text and `role="status"` unchanged); the sourcing sheet tabs
wrapped in their own `role="tablist"` with Add and Delete outside it (arrow
keys still move between tabs); `role="img"` on the calendar now-line and heatmap
cells; `role="group"` on the activity chart and heatmap container. Two tests
were added (648 in total). Keyboard focus: 306 stops
on 10 pages, all with a visible indicator, in both themes. All changes
are CSS; no component, route, API or data file was edited.

## 12. Responsive and accessibility

No overflow or page errors at 1920, 1440, 1280, 1024, 800 and 390 px (dark) and
1920, 1440, 1024, 800 and 390 px (light). axe-core
WCAG A/AA on 10 pages in both themes: no findings of any kind since 3.34.7 (the
three earlier ARIA findings were fixed in markup).

## 13. Tests and build

TypeScript, production build, 648 of 648 frontend tests, 14 theme-contrast and
release tests, `release.py --check`: all passed for 3.34.7.

## 14. Remaining material design defects

- Sign-in layout and artwork are unchanged beyond borders and the error; no
  product reference was available to judge it against.
- On phones the bidder table still scrolls sideways (with a cue).

## 15. Blocked or inaccessible sources

Superhuman help (HTTP 403); Attio, Shopify and GitHub help (no images);
Airtable help (logo only); Retool, Ramp, Vercel dashboard docs, Linear settings
docs, Spectrum component pages (404); Cloudscape component bodies (not
rendered); Mobbin, Refero, SaaSFrame, Nicelydone, Pageflows (account needed or
403); Linear and Mercury sign-in pages (empty); Stripe dashboard docs (video
banner only).

## 16. Unverified

Spreadsheet editing mode; local monitoring screens; real phone touch scrolling;
Windows display scaling; forced colors on a real Windows high-contrast theme
(only Chrome's emulation was used).

## 17. Modified files

`frontend/src/design/` (foundation, shell, components, states, triage,
analytics, operations, workspaces, auth-monitoring), release files written by
`tools/release.py` (releases.json, docs/CHANGELOG.md, pyproject.toml,
mailcheck/__init__.py, frontend/package.json, frontend/package-lock.json), the
regenerated `mailcheck/web/frontend_dist/`, and `docs/reviews/meridian-ui/`.

## 18. Recommendations that need functional or markup changes

- Show stage counts on the pipeline filter tabs (Ashby).
- Offer a day or three-day calendar view on phones.
- Replace browser confirm dialogs for removals with app dialogs.
- Settings mixes instantly saved switches with an explicit Save.
