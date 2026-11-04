# Plain bidder usernames and fitted sign-in review

## Username behavior

Bidder login now accepts the bidder's name alone, normalized with Unicode NFKC,
case folding and trimmed whitespace. A new indexed normalized key is backfilled
from existing credentials without changing passwords or workspace identities.
Existing conflicting names fail closed and require an admin rename; no account is
silently selected or reassigned.

Registration and rename check existing bidders in every non-removed workspace,
including suspended workspaces and bidders without login credentials. Credential
setup uses the same guard. A gateway lock serializes the duplicate check with the
worker's completed mutation; unrelated reads remain asynchronous. SQLite reads
run off the event loop and stream rows rather than loading all workspaces' rosters
into memory. Login uses an indexed credential lookup rather than scanning business
databases.

Review found and fixed a stale reservation for removed bidders named “Removed
bidder”. Removed credentials no longer reserve that normalized key. Canonicalized
encoded/trailing-slash bidder write routes cannot bypass validation or post-write
login-name synchronization. Regression coverage includes concurrent cross-workspace
creation, duplicate rename, Unicode/case matching, suspended workspaces, legacy
credentials and removed-name reuse.

## Sign-in fit

The sign-in page owns a fixed viewport and scales its natural layout down only
when needed. It follows visual viewport, font and content changes. Root/body
scrolling and minimum widths are locked only while sign-in is mounted, and restored
when it unmounts. The user's browser zoom setting is not modified.

Chromium checked 28 viewport/state combinations: 1672×847, 1338×678, 1115×565,
844×390, 390×844, 320×480 and 390×280; each with admin, bidder, error and required
password-change states. Root scroll dimensions fit and every form control remains
inside the viewport. Reduced CSS viewport dimensions model desktop zoom; the
browser zoom setting itself was not controlled. Tiny/keyboard-sized viewports
necessarily use a smaller rendered form to honor the no-scroll requirement.

Evidence: `/tmp/plain-browser-fit.log`, `/tmp/signin-fit-1115x565.png`,
`/tmp/signin-fit-390x280.png` and the remaining size-specific captures in `/tmp`.

## Final validation

Full backend: 592 passed, 76 subtests passed. Full frontend: 319 passed. Final
sign-in focused run: 13 passed after extending the viewport wrapper to the initial
loading state. Production build and release consistency pass for 2.11.1. Existing
Starlette/httpx deprecation and Vite chunk-size advisories remain nonblocking.
