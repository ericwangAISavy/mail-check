# Reliable health evidence implementation plan

Goal: implement the monitoring corrections approved after the code review, on the existing Windows/SQLite deployment.

Architecture: retain the independent monitor and existing charts. Report scoped, timestamped evidence with safe error categories. Observe job progress independently of process survival. Unknown and degraded evidence must not become healthy. Keep diagnostics read-only against application databases and never restart jobs merely because they take longer than expected.

- [x] Add safe diagnostic evidence and worker progress tracking. Test disconnected consumers, stalled loops, long-running jobs, and healthy idle workers.
- [x] Preserve probe details and worker identifiers in independent reports. Distinguish database readability from writability and avoid claiming write health from a read-only probe.
- [x] Record degraded/unknown transitions and recovery, retaining identifiers and error categories across monitor restarts.
- [x] Probe public shell and asset integrity independently of the local gateway, with bounded network time and response size. Report blocked probes accurately without inferring a browser or authenticated journey succeeded.
- [x] Keep independent job and queue charts available during gateway outages; explicitly mark traffic measurements unavailable.
- [x] Correct frontend aggregation and expose service/incident evidence through accessible details.
- [x] Run targeted failure tests, broader monitoring tests, frontend suite, production build, and release consistency checks. Record one patch release for the completed correction.

Validation must cover unknown publication counts, missing workspace evidence, database contention, dropped service reports, broker disconnection with a living thread, threshold-exceeding operations without termination, public access denial/corrupt assets, and incident persistence.

Validation: 130 backend regression checks passed; 34 affected monitoring checks passed after the final database permission correction. All 591 frontend tests passed with TZ=UTC. TypeScript, frontend production build, release consistency and diff whitespace checks passed. Static review corrections covered middleware ordering, stale telemetry publication, and persisted coverage gaps. Live service failures were not injected into the running deployment.
