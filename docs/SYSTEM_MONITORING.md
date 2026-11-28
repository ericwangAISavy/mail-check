# Independent system monitoring

Public HTTP probes request gzip-compressed responses and compare decompressed
entry-module bytes with the installed build. Responses remain limited to 4 MiB
before and after decompression. Each network operation has a five-second socket
timeout. Transport failures and HTTP 502/503/504 receive at most one immediate
retry; content mismatches and access restrictions do not. Evidence identifies
the shell or entry-asset stage, attempt count and first failure when retried.
An entry request that fails before receiving headers never inherits the shell's
HTTP 200. If headers arrived but reading the body timed out, evidence explicitly
identifies `read_body` and the actual response status. Restart the independent
monitor with `monitor.bat` to load probe changes.

Pool counts include workers currently processing a workspace job. Microsoft
subscription maintenance and background coordination report separately from the
consumer: a failed webhook subscription does not mean mail/calendar polling
stopped. Their Evidence shows the workspace, account ID, operation, HTTP status
and safe error category without provider responses or tokens. Subscription
clients retain Microsoft's retry delays between maintenance passes.
Disabled accounts whose Microsoft credentials require reconnection have their
stale local subscription routing removed; their remote leases expire without
renewal. Active accounts still report reconnection requirements as degraded.

A database marked **not initialized** has no file at its registered location;
this differs from a failed read query. Pending publication counts are a
point-in-time queue measurement. Dead-letter counts represent retained failed
jobs, rather than currently stopped services.

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

**Queue backlog** counts ready and retrying jobs. **Dead-lettered jobs** counts retained failed jobs separately; these are not waiting to run. A healthy broker or telemetry writer does not mean those jobs succeeded. Use the stage queue table and worker logs to investigate failures before deciding how to recover them.

Earlier gaps in the selected time range appear under **Earlier monitoring gaps**. Missing current job reporting remains a warning. The monitor displays its frontend version and checks the installed build every 30 seconds; **Reload monitoring** appears when a newer page is available. Refresh an older tab once to load this update detection.

New admin workspaces initialize their application database before they are
registered as enabled. A failed initialization cannot publish an apparently
ready workspace. Alerts identify the workspace name and the failed check reason.
The independent monitor remains read-only and continues warning about missing
databases; it never recreates a possibly lost database automatically.

For a workspace created by older versions that has never been accessed, run
this from a normal PowerShell in the repository on the server PC:

```powershell
.\.venv\Scripts\python.exe .\tools\initialize_workspace.py --workspace WORKSPACE_ID
```

The local repair checks the live registry, pending first setup, access history,
active sessions and workspace identity. It refuses existing database files,
SQLite recovery files and workspaces that have been accessed. For those cases,
investigate the missing file or restore a verified backup instead.
