# Component craftsmanship pass (3.34.1)

Presentation-only refinement on top of the 3.34.0 direction. Screenshots use
synthetic data. In each comparison, 3.34.0 is on the left. The test data was
re-seeded between some captures, so counts and checked rows can differ between
the two sides; the grid and settings comparisons use matching data.

## State language

Each meaning has its own visual channel, so combined states stay readable.
Implemented in `frontend/src/design/states.css`.

| State | Treatment |
| --- | --- |
| Hover | Neutral wash |
| Selected | Cyan wash and cyan edge |
| Focus | 2px cyan ring |
| Checked (done) | Green row-number edge, green mark, faint green wash |
| Selected and checked | Cyan wash, green edge and mark remain |
| Read-only | No field fill, quiet border, readable text |
| Disabled | Muted fill and text |
| Error, removal | Red; recovery buttons are secondary |
| Warning | Amber; calendar feedback warnings keep their own treatment |

## Reference ledger

Findings come from pages rendered in a browser on November 26, 2026. "Text" means
guidance text was extracted and read. "Screenshot" means the image was reviewed.

| Reference | Pattern and finding | Decision | Evidence |
| --- | --- | --- | --- |
| Carbon, read-only states (text) | Transparent field, de-emphasized border, unchanged text contrast; distinct from disabled | Read-only inputs restyled; completed locked checks shown as a green mark instead of a grey control | `states/settings-fields.png`, `states/grid-range.png` |
| Carbon, status indicators (text) | Combine shape and color | Checked rows use edge, number color and check mark | `states/grid-range.png` |
| Helios, badge (text) | Do not rely on color alone; use explicit words | Account status keeps "Enabled" and "Paused" text; only Paused is amber | `states/chart.png` |
| Spectrum, states (text) | Consistent progression across default, hover, down and focus | Shared state tokens | `states.css` |
| W3C APG, grid (text) | Focus and selection are separate concepts | Separate ring and wash | `states/joblinks.png` |
| Atlassian, elevation (text) | In dark themes higher surfaces are lighter; sunken wells sit below | Field wells softened from near-black to slightly sunken | `states/settings-fields.png` |
| Notion Calendar (screenshot of product art) | Flat tinted events with a solid left edge | Gradients and glow removed; identity edge kept; past events lose saturation more than text strength | `states/calendar.png` |
| Raycast (screenshot of product art) | Related choices sit in one track with a raised selection | Bidder activity toggles grouped as segmented controls | `states/activity.png` |

My own judgment, not taken from a reference: quieter mail list tags, compact
pipeline rows, stacked-bar separators, the error banner layout, the editable
payment amount.

Considered and not applied:

| Reference | Pattern | Why not |
| --- | --- | --- |
| Primer DataTable (text) | Right-align numeric columns | Day cells hold a centered "checked / confirmed" pair; alignment kept |
| Helios and Carbon forms (text) | Content-sized fields, top labels | Already done in 3.34.0 |

### Reference coverage limits

- Not available: Pageflows (HTTP 403), Spectrum table pages (404). AG Grid demo
  and theme builder did not render their grid. Grafana Play showed no dashboard.
- Mobbin, Refero, SaaSFrame and Nicelydone: public front pages only; no screens
  were browsed.
- Linear, Attio, Superhuman, Front, Missive, Airtable, Clay, Mercury, Stripe,
  Ramp, Sentry, Datadog, Ashby and Fantastical: public marketing pages only. No
  signed-in product was used, so no design finding is attributed to most of them.
- Intercom, Figma, Retool, Coda, Wise, Shopify, Geist introduction and the
  Storybook testing page were captured but not reviewed for findings.

## Verification

- Frontend tests: 646 passed in two consecutive full runs. Two earlier runs, with
  the test server also running, had 3 and 1 timing failures in `App.test.tsx`;
  that file passed 55/55 alone.
- TypeScript and production build passed. 82 selected Python tests passed; the
  full Python suite was not run.
- Parity with 3.34.0 on one dataset: 20 page and width combinations, 911 controls,
  no differences in controls, disabled states or the first 30 Tab presses.
- axe-core WCAG A/AA, both themes: no color-contrast findings. Two ARIA findings
  remain from before.
- No overflow at 1920, 1440, 1280, 1024, 800, 960, 720 and 390 px.

## Not verified

- Spreadsheet cell editing and range editing: the app hides that grid mode, so
  those styles could not be rendered.
- Contrast of non-text indicators was judged visually; no tool measured it.
- Local monitoring screens, desktop wrapper, real mail providers, Windows display
  scaling and forced-colors mode.

## Recommendations needing functional or markup changes

- Pipeline status color: the status pill has no attribute that identifies the
  status.
- Settings mixes instantly saved switches with an explicit Save (Primer, saving).
- Job links empty state could offer "clear filters" (Cloudscape, table view).
- Removal confirmations use the browser dialog (Atlassian, forms).
- Add roles for the two ARIA findings.
- Let the security policy accept, or stop the build inlining, one small font.
