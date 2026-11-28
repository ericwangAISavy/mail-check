# On-prem Security Implementation Plan

> For agentic workers: use superpowers:executing-plans for inline integration.

Goal: harden the on-prem app while users keep the registered domain.
Spec: docs/superpowers/specs/2026-11-04-on-prem-security-design.md
Architecture: shared ASGI security boundary, existing identity stores, opt-in tunnel
startup profile. Keep data and account passwords unchanged unless user explicitly
runs local provisioning. Tech stack: Python/FastAPI, pytest, existing frontend.

Global constraints: no firewall/Cloudflare account access available; no false
security guarantees; existing domain workflow; rollback tag before edits.
Review focus: chunked oversized auth bodies, duplicate/malformed Host, public
internal paths, missing auth file failclosed, forged forwarding headers, valid
user used to reset failed guesses, HTTPS/same-origin behavior, frontend CSP.

- [x] Reproduce request/body/header and startup configuration defects in tests.
- [x] Implement shared security boundary and CLI tunnel profile/local provisioning.
- [x] Independently fix auth bootstrap and login budget bypass with regression tests.
- [x] Write deployment guide and cloudflared example; distinguish manual host controls.
- [x] Full regression/security review, release build, commit and push.

Ledger: baseline d5f920a. User authorized fixes; choice of edge Access gate pending.

Verified defects: implicit admin/admin recreation, successful-login reset of prior
failed guesses, unbounded auth JSON before validation, missing policies on denied
and unexpected-error responses, public-domain internal-route exposure with a valid
worker token, malformed/duplicate Host handling and plain-HTTP acceptance in the
new tunnel profile. All have regression coverage.

Independent reviews: auth/workspace and content/SSRF audits, then fresh whole-change
review. No tenant escape or stored XSS found in inspected paths; existing email
sandbox/sanitization and backup validation remain intact. Reviewer found policies
missing on generated 500 responses; explicit private 500 handler now applies them.

Ruling: users continue on the current domain/app login; Access/MFA is recommended
and documented rather than remotely enabled without Cloudflare account access.
Cost: unauthenticated visitors can still inspect the public login assets until
Access is configured. Firewall/router/DNS settings remain a host operator step.
Ruling: update patched development tools too — npm audit exposed advisories in
Vite, Vitest/mocker, tinypool and source-map-js. Patched compatible versions removed
all reported advisories; the updated runner exposed mock-history leakage in an
existing download test, fixed with standard afterEach cleanup. Browser code unchanged.
Ruling: installed pip had advisories; upgraded this isolated environment to26.3 and
documented host upgrade requirements. This does not update the user's real host.

No minor findings deferred in application code. Origin exposure and edge Access
cannot be verified from this workspace; never label the deployment fully secured.

Final verification: 662 backend tests and84 subtests passed; 337 frontend tests
passed; production build, release consistency and git diff checks passed.
Production Chromium verified CSP/assets, real login cookies, banner suppression
and sandbox email layout. Actual local HTTP listener test verified forwarded HTTPS,
Secure cookie auth, plain HTTP and public-internal rejection, and private worker
heartbeat. Neither test contacts Cloudflare or the user's on-premises machine.
Both dependency audits report zero known advisories (Python54 installed packages).
Existing Starlette/httpx deprecation and Vite bundle-size advisory remain nonblocking.
Release2.13.4 is one app commit; rollback tag security-before-hardening-2.13.3.
