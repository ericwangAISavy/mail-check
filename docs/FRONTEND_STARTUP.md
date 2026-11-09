# Frontend startup recovery

The static startup screen must not depend on React or browser storage. A classic
same-origin script, `/assets/startup-recovery-v1.js`, runs before the module entry.
It is compatible with the existing `script-src 'self'` policy; no inline-script
exception is added. Keep this file independent of the app's module graph. Because
assets use immutable caching, future changes require a new versioned filename.

An initial script/runtime failure triggers one fresh-HTML navigation using a
`_offerpath_boot` URL marker. On a repeated failure the screen shows an accessible
recovery action. A 15-second startup timeout provides help without an automatic
reload loop. Recovery stops when React removes the startup marker, so it cannot
interrupt normal loading, API errors, or unsaved edits inside the running app.
The marker is removed before the router initializes, preserving route/filter/hash
behavior. No application records, credentials, or saved page preferences are cleared.

Storage reads at entry and for shell preferences use safe defaults. Failed theme
or sidebar writes do not stop the current view from changing.

Deploy the complete built frontend directory, including its recovery asset. After
updating a server whose browser is already stuck, reload the browser once. If the
recovery screen persists, check asset HTTP responses and the browser console; the
screen avoids displaying potentially sensitive JavaScript exception details.

Verification: 408 frontend tests, 29 frontend-delivery/release backend tests and
production build passed. Browser tests served real built files with production
CSP headers and exercised normal startup, blocked storage, authenticated startup,
one stale entry-script response, and persistent entry failure with bounded retry.
The live on-prem server and its browser console were not accessed during repair.
