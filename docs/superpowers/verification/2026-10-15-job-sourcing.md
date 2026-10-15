# Job sourcing implementation verification

Implemented on `fix/page-specific-check`, preserving existing mail/calendar/payment
behavior and the pending page-heading cleanup. The cleanup is committed separately.

## Delivered

- Named Admin/Bidder sign-in, credential version rotation, enable/disable and password
  reset/change, with own-only bidder sourcing and payment access.
- One server-side Google OAuth connection, PKCE and browser-bound expiring single-use
  state, refresh tokens and generation-based atomic keyring replacement.
- Existing spreadsheet connections, stable worksheet IDs, assigned-profile mappings,
  header/column detection and overrides, unlinking without Google deletion, and
  retained historical profile labels when an account is removed.
- Spreadsheet grid, profile tabs, keyboard editing, rectangular TSV copy/paste,
  literal writes, protected formula/header cells, append, checked autosaves, current
  session undo/redo, conflict drafts/downloads and navigation warnings.
- Scoped application search, explicit refresh across sheets, freshness, result-to-row
  navigation and an interview Find application action.
- Bundled production frontend and [setup/recovery documentation](../../JOB_SOURCING.md).

## Evidence

- Python: `pytest -q` — **200 passed**, 59 subtests passed. The remaining warning is
  the existing Starlette/httpx test-client deprecation.
- Frontend: `npm --prefix frontend test` — **105 passed** across 17 files.
- Standalone smoke: `python -m tests.test_smoke` — **331 passed**.
- Production: `npm --prefix frontend run build` — passed.
- Chromium, synthetic Google workbooks: checked edits and acknowledged undo,
  rectangular clipboard copy/paste, conflict draft preservation, leave-page guard,
  append, search-to-row, admin settings, two bidder identities, own-password changes
  and cross-bidder API denial. Desktop 1440×950 and mobile 390×844 fit the viewport;
  no page errors. A separate overflow-paste check rejects the entire paste instead
  of silently cropping it. These checks use temporary databases and fake Google
  transports; they never alter production Google files.

## Review and fixes

A fresh reviewer identified keyring replacement and positional-undo bugs before its
usage limit interrupted review. A fallback reviewer completed the remaining review.
All Important findings were reproduced and fixed:

1. Mid-write keyring failure corrupting the previous working token bundle: stage a
   separate generation and switch its pointer after all chunks exist.
2. External Google sort/edit leaving old positional undo active: clear history when
   a clean refresh changes the revision.
3. Browser Back between same-path sourcing queries discarding a draft: block query
   transitions as well as pathname transitions.
4. Successful append followed by failed refresh breaking idempotent recovery: persist
   Google's acknowledgment before refresh and recover the completed operation without
   submitting another append.

Each has a regression test observed failing before the fix and passing afterward.
The complete suites passed after the fixes. Browser overflow-paste validation was
also observed failing before the guard and passing afterward.

## Implementation decisions

- Continue the approved implementation without another authorization pause; no
  irreversible integration is part of this task. Cost if the scope assumption is
  wrong: the local feature commit can be revised before sharing.
- Keep the existing feature checkout and preserve heading cleanup separately. Cost:
  the feature stays on the existing branch rather than a new feature branch.
- Keep public Google client ID/callback alongside private client configuration in
  the OS keyring to avoid splitting replacement credentials. Cost: Google settings
  require a working keyring even before token use.
- Commit dependent auth/schema/provider/editor modules together after verification.
  Cost: a larger feature commit, with tests and documentation included for review.
- Keep the branch locally; do not merge or push as part of implementation. These
  integration actions were not requested for this feature.

## Deferred minor polish

- The admin mapping API accepts an ended historical assignment and the profile
  selector can include future assignments. File ownership remains enforced.
- Interview lookup currently prefills company or role without automatic profile
  context. Admins can search all workbooks and refine the query manually.

## Setup-dependent verification

Live Google consent, permission checks and actual file writes remain unverified until
the user's OAuth application and spreadsheet mappings are configured. No credentials
or production sheets were available during implementation. Google UI edits between
preflight and write remain a documented API limitation; the app does not claim atomic
collaboration with external Google editors.
