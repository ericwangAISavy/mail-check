# System monitoring implementation plan

Goal: owner-only whole-system health and recent operational events across all admin workspaces.
Architecture: gateway-owned read-only snapshots; bounded Redis operational events; React polling every three seconds, with filtering and pause. Monitoring must remain usable without workspace bootstrap.

- [x] Add failing API tests for owner access, cross-workspace coverage, disabled Redis, safe unavailable states, and telemetry privacy.
- [x] Implement gateway monitoring collector with read-only SQLite queries and bounded Redis reads. Do not start workers or probe external mail/model services. Report unknown when direct health evidence is absent.
- [x] Add bounded best-effort operational events to the existing Redis broker. Never expose raw errors, credentials, mail bodies, or arbitrary event fields.
- [x] Add frontend tests, owner navigation and route, component cards, workspace status, and filterable recent event flow with pause/resume and stale/error feedback.
- [x] Run targeted and complete backend/frontend suites; bump minor release once to 2.29.0, rebuild bundled assets, and check release consistency.

Review focus: unavailable Redis must not block local health; missing databases must not be created; nonowners cannot reach the API; event buffers and reads are bounded; stale snapshots must be visibly stale.
