# Meridian visual redesign (3.34.0)

Presentation-only redesign of the OfferPath web console. Screenshots use an
isolated instance with synthetic data. Admin management uses mocked owner
responses. In each comparison, the previous build is on the left.

## Direction

Three compositions were injected over the running app (`exploration.png`):

| Option | Idea | Outcome |
| --- | --- | --- |
| A | Brand and navigation share one canvas; work sits in an inset sheet with a compact title bar | Selected |
| B | Separate solid chrome with large headings and boxed panels | Rejected: more framing, less data per screen |
| C | Icon-only navigation rail with a flat work plane | Rejected: hides navigation labels |

## Comparisons

- [Triage](triage.png)
- [Dashboard](dashboard.png)
- [Bidder management](payments.png)
- [Accounts](accounts.png)
- [Settings](settings.png)
- [Interview calendar](interviews.png)
- [Job sourcing](sourcing.png)
- [Admin management](admin.png)

## Where the design system lives

| File | Owns |
| --- | --- |
| `frontend/src/professional.css` | Color tokens, checked by `tests/test_theme_contrast.py` |
| `frontend/src/design/foundation.css` | Type, density, shape, motion |
| `frontend/src/design/shell.css` | Header, navigation, workspace sheet, footer |
| `frontend/src/design/components.css` | Buttons, fields, tabs, badges, dialogs, states |
| `frontend/src/design/triage.css` | Mail queue and reader |
| `frontend/src/design/analytics.css` | Dashboard, charts, bidder activity |
| `frontend/src/design/operations.css` | Bidder management, Accounts, Settings, Admin |
| `frontend/src/design/workspaces.css` | Calendar, pipeline, spreadsheets |
| `frontend/src/design/auth-monitoring.css` | Sign-in and monitoring surfaces |

`design/` replaces `dark-glow.css`. Older layers still provide layout behavior.

## Verification

- Frontend: 646 tests in 67 files passed; TypeScript and production build passed.
- Python: 82 selected tests passed (theme contrast, release, frontend API, static
  files, web server). The full Python suite was not run.
- Parity: on one shared dataset, 20 page and width combinations (1440 and 800 px)
  exposed the same 901 controls, links, fields and disabled states, with the same
  order over the first 30 Tab presses.
- axe-core WCAG A/AA, 10 pages, both themes: color-contrast findings went from 6
  to 0. Two ARIA findings exist in both builds and need markup changes.
- Layout: no document or page overflow at 1920, 1440, 1280, 1024 and 800 px, or at
  390, 720 and 960 px.

## Not verified

- Local system monitoring screens (they need the monitoring service).
- Real mailboxes, Microsoft sign-in, a live model, and Windows display scaling or
  forced-colors mode on hardware.
- The desktop wrapper.

## Follow-ups that need markup, script or build changes

- `aria-label` on elements without a supporting role: heatmap cells, activity
  chart wrapper, calendar now-line.
- Sourcing tab list contains a button that is not a tab.
- The build inlines one small font as a `data:` URL, which the content security
  policy (`font-src 'self'`) blocks.
