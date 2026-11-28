# Meridian specification

The visual rules OfferPath follows as of 3.34.6. Presentation only: no rule here
changes behavior, data or controls. Tokens live in `frontend/src/professional.css`
(color) and `frontend/src/design/foundation.css` (everything else); component
rules live in `frontend/src/design/*.css`.

## 1. Surfaces

Four levels, lighter as they rise in the dark theme (Atlassian elevation):

| Level | Token | Use |
| --- | --- | --- |
| Canvas | `--background` | Brand bar, navigation, segmented-control tracks |
| Sheet | `--card` | The inset content area, tables, reading panes |
| Panel | `--surface` | Grouped content: metric strips, settings cards, table headers |
| Raised | `--surface-raised` | Selected segment, menus, toasts, tooltips |

Dialogs use `--card` with `--shadow-floating-md`. Borders: `--border` for panels and
containers, `--input` (stronger) for fields, `--ui-hairline` inside a container.
A container never has a stronger border than the controls inside it.

## 2. Type

| Role | Size / weight |
| --- | --- |
| Page title | 18 px / 620, −0.022em |
| Section title | 15 px / 620 |
| Body, table cells, field values | 13 px / 400–430 |
| Labels, buttons, disclosure summaries | 12–12.5 px / 550 |
| Help text, captions, metadata | 11.5 px / 400, muted |
| Eyebrows | 10 px / 600, uppercase, 0.09em |
| Metrics | 28–30 px / 600, −0.035em, tabular figures |

All numbers in tables, metrics, charts and calendars use tabular figures.

## 3. Sizes

Controls 32 px (default) and 28 px (small, toolbars); phones 40 px for fields and
34 px for small buttons. Control radius 7 px, panel radius 10 px, sheet 12 px,
dialogs 14 px. Gutter 24 px (18 px at 1024–1250, 16 px at 701–900, 14 px on phones).
Page title bar 56 px. Icons 14–15 px at 1.75 stroke.

## 4. Color roles

| Role | Color | Never used for |
| --- | --- | --- |
| Brand and primary action | Cyan `--primary` | Data values, status |
| Selection | Cyan wash + cyan edge | Status |
| Focus | 2 px cyan ring | Anything else |
| Done / success | Green `--state-done` | Selection, links |
| Attention / paused | Amber `--warning` | Brand |
| Urgent / error / destructive | Red `--destructive` | Categories that are not urgent |

Status is always color plus a word or a shape, never color alone.

## 5. Buttons

Primary (cyan fill, one per area), outline (bordered surface), secondary (selected
wash), tertiary (hairline border, softer text: view-only actions), ghost (no border:
toolbar and icon actions), destructive (red text, red wash on hover). Pressed
toggles use the selection wash. Recovery actions inside an error are outline, not red.

## 6. Status anatomy

- Lozenge: 19 px pill, 11 px / 550, tinted fill, for states in tables and headers.
- Dot + label: 6 px dot in the status color plus the word, for dense lists
  (triage rows, account rail). A hollow ring means inactive (paused, offline).
- In grids, status lives in its own cell (the check mark), not in row color.

## 7. States

| State | Treatment |
| --- | --- |
| Hover | Neutral 3.5–5 % foreground wash |
| Selected | Cyan wash + 3 px cyan edge |
| Focus | 2 px cyan ring (inset in grids and lists) |
| Checked / done | Green row-number edge, green number, green check mark |
| Read-only | No field fill, quiet border, full-strength text |
| Disabled | Muted fill and text, no shadow |
| Error | Red text and edge, recovery button outline |
| Loading | Hidden for 300 ms, then cyan spinner, label and three placeholder lines |
| Pressed | 1 px downward nudge (none with reduced motion) |

States use separate channels (fill, edge, ring, mark), so any two can combine.

## 8. Lists and tables

- Triage rows: tags and deadline, then title (13.5 / 600), account, one-line preview.
- Table headers 11 px / 600, muted, on `--surface`; rows 36–44 px; hover always on.
- Numeric columns use tabular figures; compact cell padding (6 px) below 1180 px.
- Sideways-scrolling regions fade at an edge only while content lies past it.

## 9. Spreadsheet

Row numbers muted; checked rows carry the green edge, number and check mark only
(links keep their link color); selected rows take the cyan wash; the active cell has
a 2 px ring; range cells a cyan tint with a 1 px inset; the editor a raised field
with a 2 px ring.

## 10. Calendar

Events: flat account tint, 3 px account edge, title 600, detail in the account's
own hue, times tabular. Past events lose saturation. Today: a filled cyan circle
behind the date number plus a faint column tint. Hour labels sit right-aligned on
their hour line. On phones days keep 112 px and the week scrolls under a pinned
hour column.

## 11. Charts

Faint dashed horizontal gridlines, no axis lines, muted 11 px tick labels. Bar
totals are plain numbers (no boxes). Stacked segments are separated by a 1 px
surface hairline. Legend swatches are 8 px squares; heatmaps keep a scale legend.

## 12. Forms

Labels above fields (12 px / 550), help text below (11.5 px). Fields size to their
content (money and counts ~104–148 px, URLs up to 520 px). Each independently saved
group keeps its own action beside its fields. Settings rows: label and description
left, control right.

## 13. Overlays and feedback

Dialogs: title 16 / 620, description 12.5 muted, footer actions right-aligned
(cancel then confirm). Toasts: raised surface, floating shadow, colored 3 px edge for
success and error. Disclosures: one style, matching field labels.

## 14. Responsive

Six checked widths: 1920, 1440, 1280, 1024, 800, 390. Navigation collapses to icons
at 701–900 px and to a drawer below 701 px. Wide tables compact, then stack paired
values, then scroll with an edge fade. No page-level horizontal scroll.
