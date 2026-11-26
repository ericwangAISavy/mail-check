# Enterprise visual modernization implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task by task. This task is presentation-only; no functional implementation is authorized.

**Goal:** Give the current application a restrained enterprise appearance while preserving the exact existing application, workflows, controls and values.

**Architecture:** Refine the existing final screen stylesheet in place. Use scoped overrides for shell and shared visual presentation, with a small Bidder management stylesheet refinement. No component replacements, JavaScript changes, dependencies or API changes.

**Tech stack:** Existing React, Geist, CSS tokens, Vite, Vitest, TypeScript and pytest.

**Spec:** User attachment `93026cbe-496b-4601-a2ab-87d35449035f/Pasted text.txt`.

## Current problems and direction

The source still includes heavy italic branding and a glowing version pill, large
sidebar icons and 50px navigation rows, blue-tinted dark surfaces, gradient primary
buttons, 14?16px panel radii, and multiple competing control treatments. Bidder
management tables use large cell padding and equal visual emphasis across numeric
values and supporting copy. Page-specific operational colors communicate business
meaning and must remain intact. These source findings will be checked against the
actual signed-in shell and Bidder management screenshots before implementation.

Use neutral graphite surfaces, restrained teal accent, Geist typography, a 4px
spacing rhythm, 6px controls and 8px panels, subtle separators and minimal elevation.
Keep primary actions clear, supporting metadata quieter, and numerical columns
aligned using tabular figures. Existing page structure and control locations stay.

## Files expected to change

- `frontend/src/dark-glow.css`: existing final visual layer; semantic surface/text
  tokens, shell, compact sidebar, branding, shared controls, panels, dialogs,
  badges, headings, table presentation, responsive and accessibility presentation.
- `frontend/src/pages/payments.css`: existing Bidder management presentation;
  table spacing and summary/control alignment without moving or removing content.
- This document: audit evidence, decisions, risks, verification and changed files.
- Release metadata/generated assets through the required release tool and build:
  `releases.json`, `docs/CHANGELOG.md`, frontend package versions/lockfile,
  Python version metadata only, and `mailcheck/web/frontend_dist`.

No backend implementation, tests, TS/TSX, handlers, routes, requests, stored values,
permissions, state, or data-fetching code will be modified. Prior uncommitted work
is the baseline, not part of this task's change set.

## Tokens

Dark background #101114, work surface #18191e, raised surface #282930,
text #e7e7ee, secondary text #a0a1ad, subtle border #2d2e36, input border #4b4d59
and restrained teal #9bc4cb. Primary action buttons use neutral #e5e5ed with
dark text; semantic status colors remain separate. Light uses neutral #f6f7f9 / white surfaces, dark #20252c text,
#59616d secondary text and #176b7a accent. Existing warning, danger, calendar,
checked-row, chart-series and operational colors are not replaced.

Spacing: 4 / 8 / 12 / 16 / 20 / 24px. Controls 32?36px where already compact;
existing mobile touch sizing, calendar geometry and virtual-grid row heights stay.
Section headings 16?18px, page titles 24px, body 13?14px, support 12px.

## Risks and preservation strategy

- CSS cascade: reuse final stylesheet, scope selectors, preserve semantic status
  classes and check actual computed styles after lazy page CSS loads.
- Focus: style existing focus targets only; do not change tab order, handlers,
  semantics or composite field focus ownership.
- Layout: compact sidebar only above the existing 1023px drawer breakpoint; retain
  current collapsed width, mobile drawer, responsive rules and print styles.
- Tables: change paint and ordinary-table padding only; never change virtual row
  height or selection/expansion/pagination code.
- Warnings: retain distinct red/amber/green meanings and calendar profile colors.

## Execution

- [x] Capture actual shell/Bidder management before state; inspect the screenshot,
  record source-linked visual findings and control/value signatures.
- [x] Implement shell, tokens and Bidder management reference styling. Inject CSS
  into the same live DOM for equivalent-data after screenshots before publishing.
- [x] Review reference result, then refine the same visual language for existing
  remaining pages, dialogs, lists, fields and states. Capture desktop/mobile and
  light/dark views of accessible real pages; do not introduce mock business data.
- [x] Verify navigation, existing controls, dialog open/close, safe form focus,
  dropdowns and table affordances without submitting business mutations.
- [x] Run the complete existing frontend and backend suites, TypeScript, configured
  lint (none is currently configured), release check and production build.
- [x] Compare hashes against the task baseline to prove only the allowed CSS,
  report, generated build and required release metadata changed; preserve all
  earlier uncommitted changes. Record results and limitations below.

## Excluded recommendations

Relocating settings, merging/replacing controls, removing duplicate information,
changing table interaction modes, adding shortcuts, new filters or new navigation
are outside this visual-only brief. None will be implemented.

## Audit and validation

Actual authenticated screenshots captured in the user-approved isolated Chrome
review profile; no mock data or hardcoded business values were introduced.
Bidder management before/after control and business-value signatures matched.
Desktop screenshots use 1440?1000; mobile checks use 390?1000. Chart/date/page data
may change between later production captures because collection remains live.

### Reference reassessment after the implementation reminder

Inspected the official Linear sidebar and border comparison images, the Attio
recruitment table image, and the following primary documentation:

- [Linear interface refresh](https://linear.app/now/behind-the-latest-design-refresh):
  quieter navigation, smaller icons and softer structural lines. Applied to the
  existing sidebar without adding/removing navigation items or changing order.
- [Attio table views](https://attio.com/help/reference/managing-your-data/views/create-and-manage-table-views):
  precise row/column presentation and restrained record emphasis; used only as
  visual reference, not permission to add record actions or editing features.
- [Geist colors](https://vercel.com/geist/colors) and
  [typography](https://vercel.com/geist/typography): separate surface, border and
  text roles; use a consistent heading/label/body hierarchy and tabular numerals.
- [Ramp spend management](https://ramp.com/spend-management): reference for business
  summaries and supporting operational information, not its financial workflows.

The user's preferred influence composition is directional, not a literal layout
copy. Further refinements dim inactive navigation, neutralize calendar chrome
without changing account/event colors, and remove chart glow/sheen while retaining
category colors, legends, values, labels, tooltips and interactions.

### Verification

- Complete frontend suite: **646 passed** across 67 files; no test files changed.
- TypeScript project validation: passed.
- Release consistency: passed, version **3.33.5**.
- Production build: passed. Existing main-bundle >500kB advisory remains; code
  splitting is excluded because it would exceed this presentation-only change.
- Backend suite executed completely using workspace-local temporary folders:
  **1,524 passed, 54 failed, 22 skipped; 100 subtests passed**. The initial default
  pytest temporary folder was inaccessible. The complete rerun still has Windows
  chmod/path/locked-file assertions, credential/data path sandbox restrictions and
  other existing backend expectations failing. No backend implementation or test
  assertion was changed; backend verification is explicitly not green.
- Post-release focused frontend rerun: **113 passed**; an earlier focused run had
  one intermittent failure and was rerun unchanged. Do not report that first run
  as a clean pass.
- No lint command or linter configuration is present in the frontend package.
- Tracked-file hash comparison against the exact task-start working tree found
  only the two intended CSS files and six required release metadata files changed.
  Earlier uncommitted functional changes and test assertions were preserved.
- Live read-only checks: native dropdown contents, table expansion/collapse,
  release dialog open/Escape-close, mobile drawer open/focus/Escape/restore, light
  theme data parity and high-contrast selected range styling. No business forms
  were submitted and no clipboard contents were overwritten.

### Functional-parity limitations and excluded recommendations

The existing version-history dialog does not restore focus to its launch button
on Escape. It uses a controlled dialog without a DialogTrigger; this behavior was
not changed because changing focus management is outside the brief. Treat it as a
separate accessibility follow-up, not a successful focus-restoration check.

Tests and screenshots cannot establish complete accessibility compliance or
prove every production workflow. Safe read-only interactions and existing tests
cover the reviewed paths; real sign-in was performed by the user. No account,
workspace, email, feedback, payment or application status was mutated for review.
Operational warnings seen in real data remain visible.

### Exact task change scope

Runtime presentation changes:

1. `frontend/src/dark-glow.css`
2. `frontend/src/pages/payments.css`

Required release metadata:

3. `releases.json`
4. `docs/CHANGELOG.md` (generated)
5. `frontend/package.json`
6. `frontend/package-lock.json`
7. `mailcheck/__init__.py` (version constant only)
8. `pyproject.toml` (version metadata only)

Documentation: this plan/report. Generated production outputs:
`mailcheck/web/frontend_dist/index.html`, `assets/build-info.json`, and the Vite
asset bundle. The artifact manifest lists the built files. No component source,
handlers, routes, API contracts, databases, tests or dependency set changed.



## Follow-up after visual rejection of the first pass

The user judged the first pass substantially below Linear's visual standard. The
work continues under the same strictly visual scope. The reference was revised
rather than treating the earlier consistency pass as finished: one inset working
surface, a 56px desktop header, 34px sidebar rows with 18px icons, neutral high
contrast primary actions, neutral select chevrons, aligned headings and table
edges, and dividers in place of repeated configuration cards. Settings sections
are flatter; sufficiently wide desktop account rows place existing actions inline
without changing DOM/focus order or moving controls to another workflow.

The visual revision remains in the same two CSS files. No existing feature,
control, handler, route, state/data logic or dependency was changed. Smaller
screens retain existing drawer behavior and stacked account actions. Calendar
identity and warning colors, selected/checked data rows and financial values are
preserved. The earlier test totals above must not be mistaken for verification of
the final CSS revision; rendered comparisons, TypeScript/build and relevant tests
are being repeated before the final handoff. Release 3.33.5 remains the single
release for this continuing, not-yet-completed modernization batch; its published
entry is not rewritten.


### Final visual refinements and retained boundaries

The rendered reference was revised beyond palette/radii: desktop navigation and
header became smaller, context text quieter, repeated boxes were flattened, the
work surface became distinct from the outer shell, account rows gained inline
existing actions at wide widths, and settings became continuous sections. All
layout adjustments retain DOM/focus order and existing controls.

Sign-in now uses the same Geist typography, matte form surface, 6px field/action
radii and a neutral primary action. The original artwork, tiny falling lights,
role select, password visibility control, responsive fitting, validation and
submission behavior remain. No authentication code was touched.

Visual inspection caught clipped chart Y-axis digits after reducing card padding.
The final CSS exposes the chart SVG overflow within a reserved left gutter; this
restores the complete labels (including 1000) without changing any chart values,
scales, calculation, data or event handlers. Earlier padding-only screenshots are
not accepted as proof of the final correction.

A timing-sensitive full-suite run failed the App test for the Settings heading.
The unchanged App file rerun passed all 55 tests. No assertion, mock, timeout or
functional implementation was altered to make it pass. The final complete-suite
result is recorded in the artifact test log.


## Final acceptance record

The final complete frontend run passed **646/646 tests in 67 files** (83.06s).
TypeScript, release consistency and the final production build passed. The
unmodified backend suite remains **1,524 passed / 54 failed / 22 skipped**;
backend failures were reported, not fixed or concealed by this visual task.
No lint command is configured. Existing Vite bundle-size advice remains.

The final source hash comparison again found exactly the two planned stylesheet
changes plus required release metadata. No unexpected tracked changes since the
task-start working tree were found. An independent read-only CSS review found no
blockers; rendered review separately identified and corrected chart clipping.

Accepted rendered steps (actual production data, no mock records):

| Step | Surface | Visual review result |
| --- | --- | --- |
| 1 | Shell and Bidder management | Continuous surface, compact navigation and financial table checked; existing values/actions retained. |
| 2 | Triage | Existing category/severity colors, analysis warning, actions and reader retained. |
| 3 | Dashboard and profile quality | Flatter chart/summary hierarchy; complete numeric axis labels and category colors retained. |
| 4 | Interview calendar | Neutral chrome; original profile colors, warning indicators and event geometry retained. |
| 5 | Interview pipeline | Existing filter controls and actual empty state checked; no sample records introduced. |
| 6 | Legacy process history | Actual process cards, age colors, milestones and controls checked. |
| 7 | Job sourcing | Actual empty-day view, tabs, paste target and missing-links warning retained. |
| 8 | Job links | Dense real table, filters, pagination and existing incomplete-library warning retained. |
| 9 | Accounts | Existing actions inline at wide desktop widths, stacked on mobile; sync/status indicators retained. |
| 10 | Settings | Continuous configuration sections, existing fields and focus treatment checked without submitting. |
| 11 | Admin management and Backups | Existing directory/detail and backup tasks retained; owner controls remain in place. |
| 12 | Sign-in | Actual unauthenticated form captured after startup completed; artwork and existing controls retained. |
| 13 | Mobile and light/high-contrast views | 390px views had no document overflow; drawer, dropdown, table expansion and selected-range checks recorded. |
| 14 | Independent monitoring | Real warnings/health evidence remain visible; no service repair or warning suppression attempted. |

Earlier captures showing only loading/startup screens were rejected and replaced.
Some operational warnings remain in real data; this is presentation verification,
not a claim that all services or backend tests are healthy. Auth form submission,
mail sends, copy-to-system-clipboard and destructive actions were not exercised.
The pre-existing version-dialog focus restoration issue remains a separate
functional accessibility recommendation. No workflow changes were introduced.

All modified source/release files are enumerated above. Generated production files
are listed with sizes and hashes in `build-manifest.json` in the local artifact
folder. Accepted screenshots, before/after views and verification logs are retained
outside the repository; temporary browser credentials and test databases are not
part of the deliverable.


Local screenshot/report artifact: `C:/Users/Brian/AppData/Local/Temp/offerpath-enterprise-ui-20261126/report.html`.
The final production screenshot set was re-captured after the final build and
inspected. The local report rendered 15 sections with no broken image links.
The isolated review browser was closed and its profile/test databases removed
from the repository. Screenshots and logs stay in the local artifact folder.
