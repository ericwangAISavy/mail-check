# Origin availability behind Cloudflare Tunnel

A Cloudflare 502 across `/`, static files, sign-in, and business APIs means the gateway or the tunnel-to-origin connection is failing. An open terminal does not establish HTTP availability. This symptom alone does not establish CPU or memory exhaustion.

On Windows, run `start.bat --tunnel --allow-host app.offerpath.bid --no-open` after updating. The launcher now monitors the direct local HTTP listener and restarts only the child process it launched after three consecutive failed probes. It tolerates admission-pressure responses, stops on intentional shutdown or invalid startup, and limits recovery to five restarts per five minutes. Ctrl+C stops supervision. Single-admin compatibility mode and bindings to a specific non-loopback address use the original foreground launch.

Recovery events are shown in the terminal and saved in `logs/origin-supervisor.log` inside the installation's control directory. The exact path is printed at startup. Logs rotate at 1 MiB and retain two backups. Application output remains in the terminal; workspace output remains in the control directory's workspace logs. Recovery does not replay requests or email sends.

During a failure, run on the server PC:

```powershell
curl.exe --noproxy "*" --max-time 5 -i http://127.0.0.1:52400/_internal/origin-health
curl.exe --noproxy "*" --max-time 5 -i http://127.0.0.1:52400/login
```

The direct health probe should return HTTP 204 with `X-OfferPath-Health: 1`. It is available only to direct loopback requests; public/forwarded requests retain normal access controls. The login response should be HTTP 200.

- If both fail or time out, inspect terminal output and the origin recovery log. The listener or host is unhealthy.
- If health responds but login stalls, inspect gateway/application logs and disk/database contention.
- If both respond quickly while the domain returns 502, inspect cloudflared's corresponding errors and the configured ingress target. For the default bind, the service URL must be `http://127.0.0.1:52400`, not HTTPS or an IPv6 localhost address.

Cloudflared must run on the same machine for this loopback target. If it runs in a container or another machine, its `127.0.0.1` refers to that environment and requires an appropriate route instead. Keep the origin port private; opening it publicly is not a remedy.

The application cannot verify or repair an external tunnel's ingress configuration from this repository. Correlate local probe results and cloudflared errors at the same time as the client 502 before attributing the incident to a particular layer.

Workspace workers also receive authenticated local health checks during gateway monitoring. Three consecutive failures retire only the affected worker; the existing restart budget limits repeated recovery. HTTP 503 admission responses count as reachable so overload alone does not restart a worker. Network probes and process shutdown waits run outside the shared worker lock, keeping other workers' heartbeat authentication available.

The control database uses SQLite WAL journaling so session reads can continue during admin transactions. Each request still reads committed authorization state, including password resets and access revocation. Backups must include a live database through SQLite's backup API; copying only `control.db` while the server runs can omit committed WAL data. OfferPath's built-in backups already use SQLite snapshots.

Gateway page reads share a 25-second budget beginning before authentication. Session lookup has a five-second limit; temporary session-storage failures return HTTP 503 with `Retry-After` instead of masquerading as a sign-out or exposing database errors. The public login shell and static assets do not require session storage, but their protected APIs still authenticate normally. Dispatched writes are not subject to the page-read timeout.

Each worker-readiness wait is bounded to 20 seconds. A still-initializing process remains available for subsequent readiness checks, with a separate two-minute hard startup limit. This allows startup migrations to finish without retaining a page request indefinitely. Original-workspace backup verification is serialized separately from heartbeat authentication so slow backup disk access cannot block other workers' heartbeats.
