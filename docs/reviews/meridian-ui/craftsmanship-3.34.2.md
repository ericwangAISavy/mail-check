# Evidence pass (3.34.2)

Presentation-only. Each change below began with a defect seen in a rendered
screen (synthetic data, 1440×900, dark and light), not with a reference. The
references were used to choose the treatment. Before is on the left in every
image in `r3/`.

## Changes

| Seen in the render | Reference used | Treatment | Evidence |
| --- | --- | --- | --- |
| Every "Act now" row had a filled red pill, repeating the red tier heading 21 times; red stopped meaning urgent | Atlassian lozenge (danger is for blocked or critical states); Primer label variants | In the list, urgent badges become a red dot and label; the reader pane keeps the filled pill; the deadline now leads each row | `r3/triage.png` |
| Bidder summary: a wrapped label pushed "199" 18px below "46" and "$0.00" | None; own judgment | Label at top, value and caption pinned to the bottom of each tile | `r3/summary.png` |
| After-deduction amounts were bright blue while disabled, so they looked like links | Primer: accent foreground marks interactive text | Disabled amounts use foreground and weight; editable amounts use the brand color | `r3/summary.png`, payments page |
| "Paused" looked identical to the "IMAP" provider label | Helios badge (explicit words, not color alone); 3.34.1 dashboard treatment | Paused uses the amber warning color in both themes | `r3/accounts.png`, `r3/light.png` |
| Calendar detail text was one fixed blue on every account color (blue on magenta) | None; own judgment | Detail text mixes the event's own text and accent colors (dark theme; light theme already matched) | `r3/fri.png` |
| "Advanced inference settings" was larger and lighter than the field labels; seven disclosures across the app used five different styles | Carbon form (sentence-case, consistent label voice) | One disclosure style for text-only summaries, matched to field labels | `r3/settings.png` |
| The sign-in card border was as strong as the field borders | Primer border tokens (default for containers, emphasis for controls) | Quieter card border | `r3/login.png` |
| Shadows were ad hoc values | Primer resting and floating shadow scale | Shared shadow tokens for buttons, the content sheet, dialogs and toasts; success and error toasts get a colored edge | Visual only |

Considered and kept as is: "Link history" is a borderless button among outlined
ones in each account row. The code marks it as the lower-priority view action,
so matching it to the others would remove that hierarchy.

## Research coverage

Read in full and used: Primer color tokens, button, label, dialog, banner,
spinner and skeleton; Carbon data table, form, structured list, button, and the
chart anatomy, axes, legend and color pages; Atlassian elevation, badge and
lozenge examples; Radix Themes dialog, text field, switch, select, badge and
tooltip; Helios text input; W3C APG grid and treegrid; AG Grid theming,
density and color; Vercel environment variables docs; Linear changelog
(text only).

Product interfaces: almost none were inspectable. Front (404 and community
posts about the 2025 inbox redesign), Superhuman, Missive, Intercom, Clay,
Airtable, Coda, Ashby, Mercury, Sentry, Notion Calendar and Fantastical gave
marketing or review text only. Linear and Mercury sign-in pages rendered empty.
Ramp, Attio feature pages, Retool components, Vercel dashboard docs, Linear
settings docs and Shopify admin docs returned 404. Spectrum component pages and
Cloudscape table, loading and status pages were 404 or rendered no body.
Mobbin showed no screens without an account. So the module gate of two
production-interface examples was **not met for any module**. The decisions
above rest on design-system guidance and on defects visible in OfferPath's own
screens.

## Verification

- Frontend build and TypeScript passed.
- Frontend tests: first run 645 of 646 (one failure, not captured, with the QA
  server running); the next two runs passed 646 of 646.
- Theme contrast and release tests: 14 passed. `release.py --check` passed.
- axe-core WCAG A/AA on 10 pages in both themes: no color-contrast findings;
  the same pre-existing ARIA findings as 3.34.1 (calendar now-line, sourcing
  tab list, heatmap cells).
- No overflow or page errors at 1440×900 in either theme.

## Widths and remaining screens (3.34.3)

Rendered all pages at 1920, 1280, 1024, 800 and 390 px (dark), plus 14 open
states at 1440 px: Admin backups, activity and add-admin; Connect mailbox,
Outgoing mail, Clear link history, Add opportunity, Job link filters, interview
details and version history dialogs; an error toast; triage and dashboard
filter panels; the legacy interview history page.

| Seen in the render | Treatment | Evidence |
| --- | --- | --- |
| At 1024 px the bidder table needed 826 px in a 776 px box; the payment column was cut mid-figure with no scroll cue | Cell side padding 10 → 6 px below 1180 px (Carbon compact density); the table now fits (776/776) | `r4/payments-1024.png` |
| At ≤800 px the app hides the Online/Offline text in the workspace directory; offline was only a fainter grey dot | Offline becomes a hollow ring, so the two states differ in shape as well as color | `r4/admin-offline-800.png` |
| On phones the app hides the "Sync" label, leaving an unexplained switch beside labelled buttons | The label is shown; the grid already had room | `r4/accounts-sync-390.png` |

Reviewed with no change needed: the dialogs (clear field hierarchy, readable
disabled actions, `r4/dialogs.png`), the error toast (`r4/toast-error.png`),
Admin backups and activity tabs, filter panels, and the 1280 and 1920 layouts
at composition level.

## Narrow-screen follow-ups (3.34.4)

| Seen in the render | Treatment | Evidence |
| --- | --- | --- |
| At 800 px the bidder table needed 762 px in 700 px and scrolled with no cue | Below 900 px the before and after amounts stack (the header already names the order), the payment header wraps and the bidder column narrows; the table fits (700/700) | `r5/payments-800.png` |
| On phones the table must still scroll (656 px in 350 px) | A right-edge fade appears only while more columns lie to the right; the pinned bidder names are not faded | `r5/phone-table-calendar.png` |
| On phones the calendar squeezed five days into 350 px, leaving titles of 3 to 5 letters | Days keep at least 112 px and the week scrolls sideways inside the calendar, under a pinned hour column; event positions are unchanged (still relative to each day) | `r5/phone-table-calendar.png` |
| On phones the Settings and Accounts section menus ran off the edge with no cue | Each edge fades only when more items lie past it | `r5/phone-section-menus.png` |
| "Link history" looked like loose text among outlined buttons | Hairline border and softer text: a button, one step quieter than its neighbors | `r5/link-history.png` |

The fades follow the element's own scroll position (CSS scroll timelines,
supported by the Chromium engine the app runs in); without overflow, or in an
engine without support, nothing is faded.

Rechecked at proper scale with no change needed: 1920 px (Dashboard, Settings,
Bidder management, Accounts) and the light theme at 1920, 1024, 800 and 390 px.

## Verification (3.34.4)

- Frontend build, TypeScript and 646 of 646 frontend tests passed.
- Theme contrast and release tests: 14 passed. `release.py --check` passed.
- Control parity against the 3.34.0 build on the same data: 20 page-and-width
  views, 903 controls, no differences in controls, disabled states or Tab order.
- axe-core WCAG A/AA, 10 pages, both themes: no color-contrast findings; the
  same three pre-existing ARIA findings (calendar now-line, sourcing tab list,
  heatmap cells).
- No overflow or page errors at 1920, 1440, 1280, 1024, 800 and 390 px in
  either theme.

## Not verified

- The spreadsheet cell-editing mode (the app hides it) and the local
  monitoring screens (not reachable in this test setup).
- Touch scrolling on a real phone; phone widths were checked in a desktop
  browser at 390 px.
