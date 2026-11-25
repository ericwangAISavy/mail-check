# Service health recovery — 2026-11-25

Live investigation through the independent loopback monitoring API found that
both collection workers were running. In-flight job evidence included a
workspace, causing the frontend to exclude busy workers from pool totals.
Separately, Microsoft subscription maintenance replaced collection health with
a generic GraphError. The existing logs suppressed its underlying account and
error identity.

Separate dependency evidence revealed ReconnectRequired while deleting stale
subscriptions for disabled account 14 in workspace
56301cac7b4cc1ca4df87e26f71099c4. Cleanup now removes local routing for disabled
accounts when authentication cannot be renewed. Active-account reconnection
failures remain visible. No credentials or user settings were changed manually.

One registered workspace has no database file. Monitoring labels this as not
initialized, without creating an empty database or declaring it healthy.
Publication counts and retained dead letters are preserved.

Validation: 68 related backend/release tests, 22 monitoring frontend tests,
TypeScript and the production build passed. A reviewer found no important
regressions in the worker/dependency evidence changes. The disabled-account
regression failed before the cleanup fix and passed afterward, alongside an
active-account reconnection check. Release checks pass for 3.31.1. The existing
supervisor accepted graceful restart requests to load the fixes.

The independent monitor is a separately running process; run monitor.bat from
the original server account to load its updated dependency-report parser.
