# Compact workspace and sign-in review

Scope: compact UI, fixed sourcing headers, admin selector, bidder login, workspace permissions, and existing regression suites.

## Issues reproduced and fixed

- Bidder login remained enabled when its account directory failed. Disabled controls bypass native form validation, allowing an empty bidder identifier to be submitted. The form now requires a selected account in a successfully loaded directory for either role. The submit handler also checks readiness.
- Role, username, and password could change while a login request was pending. Those controls now stay disabled until the request finishes, and the submit handler rejects repeated submissions while busy.
- An authentication test's generic directory fixture also supplied fake inbox data after login, producing a React rendering warning. The auth tests now isolate the inbox component.

## Review evidence

Regression tests reproduce the first two failures before their fixes. Coverage also includes directory failure/retry, additional admin workspace routing, owner-only Settings, forced password changes, bidder navigation, sourcing row identity, paste/save, weekly calculations, and workspace suspension.

Desktop dark/light and narrow viewport captures from the compact-layout verification show no document-width overflow on the sampled routes. The sign-in capture confirms a selectable admin account and no editable username field. Data storage and calculation rules were not changed in this review.

These checks use local fixtures and temporary test databases. They do not diagnose the separate Windows host's historical local Dashboard outage or verify its live Cloudflare tunnel.
