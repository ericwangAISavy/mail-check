# Independent system monitoring

Open **http://127.0.0.1:52401** on the server PC. The monitor is a separate process and remains available when the OfferPath gateway stops. `start.bat` starts it; `monitor.bat` starts or replaces an outdated monitor. Monitoring APIs are local only and do not require the application sign-in server.

Health tiles refresh every five seconds. Expand **Evidence** to inspect the check scope, source timestamp, duration, reason, OS/SQLite error codes, process ID, and active job identifiers where available. Unknown or stale evidence is never counted as healthy. Database totals represent readable databases, with incomplete workspace inventory explicitly identified.

- **Gateway** checks the local HTTP liveness endpoint. It does not establish that workspace routes or the public domain work.
- **Public site** separately requests the configured `OFFERPATH_PUBLIC_URL` shell and entry JavaScript, comparing its bytes with the installed build. Access denial is unknown, not healthy or proof the origin crashed. This check runs every 30 seconds with bounded requests. It does not execute JavaScript, load every lazy module, sign in, or contact mailbox/model providers.
- **API pool** checks direct HTTP responsiveness and control-database readability. Individual source timestamps and process IDs are available in Evidence. Workspace database availability is measured separately.
- **Collection/model workers** report broker polling, loop age, and active job age and identifiers. More than 30 seconds without consumer polling is degraded. An operation running longer than 15 minutes is degraded, without terminating it. Coordinator/subscription loop checks allow 180 seconds between polls. These thresholds identify suspicious progress, not a proven deadlock.
- **Databases** use bounded read-only queries. Evidence explicitly leaves write availability unknown. Monitoring never modifies application databases to test writes. Actual job failures preserve SQLite busy/error codes.
- **RabbitMQ** passively reads queue counts. This establishes queue access, not end-to-end processing or provider reachability.
- **Publication** reports pending outbox rows and unknown workspace counts. Zero rows means no pending outbox rows, not proof of browser delivery.

Degraded, unavailable, and unknown transitions and subsequent recovery are retained in `monitor-incidents.json` (up to 200 entries), including safe diagnostic fields. Job events include worker/PID, job ID, attempt, error class and source location where available. Failed requests carry an `X-Request-ID` response header; gateway and shared-worker logs use the same identifier. Logs omit query strings, request payloads, credentials, and provider response messages from these diagnostic records.

Independent job metrics and queue observations continue when gateway metrics are unavailable. Traffic and latency then display unavailable rather than invented zero values. Metric snapshots, queue history, and per-minute job coverage are saved under the control directory for monitor recovery. Missing coverage remains a gap across minute changes and restarts; historical recorded totals remain available. Telemetry writer stalls, failed persistence, and recent dropped events are exposed as separate evidence. Fresh job telemetry requires the updated workers to be running. Events and metrics remain bounded, best-effort operational evidence, not a complete audit trail.

The monitor does not consume jobs, acknowledge messages, invoke providers/models, or restart active jobs because of a warning. Use the timestamps and identifiers to correlate an incident with the worker and gateway logs; a health status alone cannot prove every possible root cause.
