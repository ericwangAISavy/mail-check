# Bidder, reply and sourcing usability review

Prepared for OfferPath 2.13.0 from the latest 2.12.0 feature branch state.

- Accounts bidder editors now behave as a single-open accordion. Inactive panels
  stay mounted but hidden, preserving unsaved form drafts across switches.
- Bidder-management email masking covers account rows, accessible labels and account
  chart selectors/legends/tooltips/tables. Underlying account identity is unchanged;
  masking is a display treatment, not a new API-access restriction.
- Assisted reply UI and externally exposed generation/context/preferences APIs are
  removed. Manual draft/delivery/idempotency paths and independent followups remain.
  The dormant assistant module/schema is retained for historical data compatibility.
- Sign-in uses a maximum 85% layout scale, with further fitting for constrained
  viewports. This does not change browser zoom or reintroduce page scrolling.
- Sourcing cell clicks select the full row; copying produces all columns as TSV.
  Checked rows have distinct styling and locked values/formatting in the save API.
  Initial checked-row pastes remain atomic; failed mixed saves roll back fully.
  Explicit row deletion/date moves remain available as requested.

Independent review found a row-number keyboard gap: Delete/Backspace was excluded
for the ID column. It is fixed and covered by a regression. Browser checks verified
real clipboard copying, row-number deletion, checked-row edit refusal, unchecked
editing, ordinary link-click selection, and nonselectable rendered text.

Validation: 607 backend tests and 83 subtests passed; 324 frontend tests passed.
Production build and release consistency checks pass. Chromium also passed 28
sign-in viewport/state combinations with the reduced scale. Existing Starlette
HTTP client deprecation and Vite bundle-size advisories remain nonblocking.

Browser fixtures used synthetic rows and responses; no user account, workspace,
stored status, mailbox, or email delivery was changed during validation.
