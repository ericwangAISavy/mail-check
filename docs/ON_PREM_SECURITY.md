# On-premises deployment behind Cloudflare Tunnel

Users keep accessing `https://YOUR_DOMAIN`. This guide removes the need for any
inbound app port. Code changes alone do not establish that your actual firewall,
router, Cloudflare settings or DNS records are safe. The commands below are for
the on-premises computer, not the development workspace.

## Start safely

Existing installations with a strong owner password retain it. Fresh installations,
missing authentication files and installations still using `admin` cannot start
through the CLI. To provision or reset the owner password **locally**, run:

```sh
python -m mailcheck web-password
```

Enter a unique password of at least 12 characters at the hidden confirmation prompt.
This command resets owner sessions; do not run it unless provisioning/reset is
intended. Missing or corrupt auth files are never recreated by HTTP requests.
Back up your auth file and data privately. Keep backup permissions restrictive.

Start the gateway using your actual hostname:

```sh
python -m mailcheck web --no-open --tunnel --allow-host YOUR_DOMAIN
```

`--tunnel` requires a loopback IP (default `127.0.0.1`) and an explicit public
domain. It enables Secure/HttpOnly/SameSite=Strict cookies and HSTS, rejects public
requests bearing localhost/IP hostnames and keeps the existing workspace login.
It cannot be combined with `--single-admin` or `--host 0.0.0.0`. The app uses a
same-origin browser policy, bounds HTTP bodies and concurrency, and hides API
schema/docs endpoints. Internal worker routes reject the public hostname.

Configure your Cloudflare Tunnel to forward the existing domain to
`http://127.0.0.1:52400`. See [cloudflared.example.yml](../deployment/cloudflared.example.yml).
The explicit `httpHostHeader` must match `--allow-host`. A catch-all 404 prevents
unexpected hostnames being forwarded. Dashboard-managed tunnels use the equivalent
Public Hostname / Service / HTTP Host Header settings; do not replace a working
tunnel credential or expose its token. Keep cloudflared on the same computer.

Enable Cloudflare Always Use HTTPS. The tunnel profile refuses plain HTTP public
requests, so Cloudflare must supply the correct original HTTPS scheme. Uvicorn explicitly
trusts forwarding headers only from loopback peers, ignoring wildcard environment
proxy trust. Do not put an untrusted local proxy in front of the gateway. For client
IP attribution, ensure Cloudflare replaces X-Forwarded-For with the actual visitor
chain rather than passing arbitrary client values. Never implement trust by simply
accepting a client-supplied `CF-Connecting-IP` header.

## Prevent bypass around Cloudflare

- Remove router/NAT port forwards for the app, workers and model endpoint. Do not
  forward 52400, private worker ports or Ollama ports to this computer.
- Host firewall: default deny unsolicited inbound traffic on **both IPv4 and IPv6**,
  retaining only explicitly needed administration/services. Remove earlier allow
  rules for app/worker/model ports. Keep administrator recovery access before
  changing firewall defaults; do not blindly enable a new firewall remotely.
- No inbound 80/443 is needed for this outbound tunnel. If the computer hosts other
  services, audit them separately rather than assuming the tunnel protects them.
- App and workers must listen on 127.0.0.1/::1, never wildcard/LAN/public addresses.
  On Linux inspect `ss -lntp`; on Windows use
  `Get-NetTCPConnection -State Listen`. Check firewall rules as well as listeners.
- DNS should use Cloudflare Tunnel routing (a CNAME to the tunnel), with no app
  A/AAAA record exposing the on-premises address. Audit alternate hostnames and
  historical exposure. Do not delete unrelated email/DNS records blindly.
- Keep the OS, Python environment, cloudflared and application dependencies patched;
  run as a dedicated non-administrator account with private data/backup directories.
  Keep Ollama private too: it receives message contents and may need LAN access
  from this host, but should not have a public forwarded port.

From a different external network, attempt access to **your own** public IP on the
app's configured port, including IPv6 if present. It must fail, while your domain
must work over HTTPS. Also verify other app/worker/model listeners are inaccessible.
These steps require your actual host/network and have not been executed remotely
by the code review. An IP can still be discovered through other services or DNS
history; the protection is denied connectivity, not relying on IP secrecy.

## Recommended extra gate: Cloudflare Access and MFA

The domain currently continues to use app login. If only invited users should even
reach the sign-in page or download frontend assets, add a Cloudflare Access
self-hosted application for the **entire hostname**, not just `/api`:

1. Configure an explicit allowlist of users/groups and require MFA at the identity
   provider (or an appropriate Access authentication method policy).
2. Avoid Everyone/Bypass policies and alternate unprotected hostname routes. Verify
   a signed-out/private browser is challenged before any app HTML/assets load.
3. Make cloudflared validate Access JWTs as well, using the settings supported by
   your installed cloudflared version. For locally managed tunnels, the origin
   request configuration supports:

```yaml
originRequest:
  httpHostHeader: YOUR_DOMAIN
  access:
    required: true
    teamName: YOUR_ACCESS_TEAM_NAME
    audTag:
      - YOUR_ACCESS_APPLICATION_AUDIENCE
```

Use the team name and application AUD from **your** Cloudflare account. Validate
this configuration with your cloudflared version before restarting. Enable the
Access application first and test with an allowed user to avoid lockout. For
remotely managed tunnels configure the corresponding Access validation options.
No unverified identity header should replace JWT validation. Retain the app login
as a second layer; Access authentication does not grant owner privileges.

Cloudflare edge rate limiting/WAF should protect login and large-request abuse;
never disable origin authentication because a WAF is present. An address-level
application limiter intentionally retains failed guesses even after a successful
login. A connector that reports all visitors as one IP can cause shared lockouts;
verify proxy attribution and use edge policies. Limits are process-local and reset
on restart; a distributed internet attack needs the edge layer too.

## Verification and rollback

Synthetic tests cover malformed/duplicate hosts, oversized chunked bodies,
security headers on failures, public internal-route denial, secure tunnel startup,
missing-file failclosed authentication, and successful-login brute-force reset.
Email scripts/remote resources remain blocked by sanitization and iframe policies.
This review is not proof of absence of vulnerabilities or a live penetration test.
Browser-delivered HTML/JS/assets can be inspected by anyone allowed to load them;
server secrets, mailbox tokens and config must never be included in frontend code.

The pre-hardening code is tagged `rollback/security-before-hardening-2.13.3`.
The hardening is a single app commit; revert it rather than resetting branch history.
Firewall/Cloudflare changes made separately need their own configuration backups.
No real firewall, Cloudflare account, credentials or mail data were changed here.

## Dependency audit baseline

The checked lockfile now uses patched Vite 6.4.5 and Vitest 4.1.12; compatible
transitive tooling was updated too. npm audit reports zero known advisories for
that lockfile. The local Python environment audit checked 54 installed packages
with zero reported advisories after upgrading pip to 26.3. These results are
point-in-time advisory checks, not an absence-of-vulnerabilities guarantee. A
Python environment on another computer may have different installed versions.

On the host, update its installer and application dependencies in the correct
virtual environment before deploying, then test the application:

```sh
python -m pip install --upgrade 'pip>=26.2'
python -m pip install --upgrade --upgrade-strategy eager .
```

Use trusted package indexes, retain a working environment backup for rollback,
and rerun dependency audits periodically. Node development tools are not served
by the production app; never expose the Vite or test-runner server through a tunnel.

## Distinguishing a tunnel 502 from app overload

A Cloudflare page showing browser/Cloudflare working and **Host error 502**
identifies a failure on the origin side of the connection. It does not by itself
identify a stopped app, a broken tunnel connection, or an application exception.
At the time of a failure, run this on the app host (use `curl.exe` in Windows
PowerShell), substituting your configured domain/port if different:

```sh
curl -i --max-time 10 -H "Host: app.offerpath.bid" -H "X-Forwarded-Proto: https" http://127.0.0.1:52400/api/auth/session
```

This public session check needs no password or cookie. Keep the origin bound to
loopback. A local connection failure points to the app listener/process; retain
the gateway terminal traceback and OS termination records. If this succeeds while
the domain still returns 502, retain the same-time cloudflared error and compare
its configured origin port and HTTP/HTTPS scheme. Retain the affected workspace's
`offerpath-control/logs/<workspace_id>.log` too. Remove secrets before sharing.
Do not expose worker ports or disable host/HTTPS validation to diagnose a tunnel.

The default server now separately bounds active requests (64 ordinary + 8 short
worker control calls) and transport/task headroom (256). Temporary active overload
returns JSON 503 with `Retry-After`; it does not require restarting healthy workers.
Capacity remains finite, and real host RAM/CPU/network limits still need monitoring.
