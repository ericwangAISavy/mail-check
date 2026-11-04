# On-premises domain and tunnel hardening

User authorization: audit and fix verified security defects; users continue using
the existing domain. Preserve rollback and existing workspace/email data.

Threat model: unauthenticated internet requests through Cloudflare Tunnel; malicious
websites, compromised low privilege accounts and hostile email content. Application
fixes cannot prove the actual router, host firewall, Cloudflare Access configuration,
OS patch level or DNS history secure without access to those systems. No guarantee
of being unhackable or preventing inspection of browser-delivered assets.

Approaches: exposing a LAN listener behind a tunnel leaves an unnecessary bypass;
changing the whole authentication architecture risks user lockout. Retain existing
accounts and sessions, fix verified defects, and add an opt-in tunnel profile that
requires an explicit hostname, loopback bind and secure cookies. Recommend an
additional Cloudflare Access identity/MFA gate, with cloudflared validating Access
JWTs; user preference remains pending. Do not change their real edge policy here.

Changes:
- No implicit admin/admin account recreation. Explicit local password provisioning
  and startup refusal for missing or known default credentials.
- Bounded request bodies before JSON parsing; short idle read timeout and login
  payload limit. Apply safe response policies even to rejected requests.
- Exact host/origin checks and a tunnel-only public hostname boundary. Internal
  routes must not be reachable using the public domain, even with a worker token.
- CSP for React assets without inline JavaScript; preserve legacy template support
  in compatibility mode. Secure cookies and HSTS in the tunnel profile.
- Pin trusted proxy peers and disable server banners; bound HTTP concurrency.
- Fix verified login attempt reset bypass; retain current role/workspace boundaries.
- Supply a Cloudflare Tunnel sample and host/router verification steps, with
  inbound IPv4 and IPv6 protection and no port forwarding.

No live infrastructure modifications, scans against unrelated hosts, credential
reads or mailbox changes. Test all fixes with synthetic HTTP requests, existing
backend/frontend suites and production build. One release and reversible commit.

## Reviewed scope and results

Authentication defects were reproduced and fixed. Both gateway and standalone
app apply body/host limits and browser policies. The tunnel profile additionally
requires HTTPS on public requests and denies localhost/IP public hostnames.
The fresh independent reviewer found no critical/important bypass in reviewed
changes and identified one missing-error-policy issue, now regression-fixed.
Dependency advisory scans report zero known advisories after compatible tooling
updates and an isolated pip upgrade. The production Chromium check passed real
login cookies, CSP/assets, no server banner and sandboxed email layout.

Remaining deployment actions: use --tunnel on the real computer; close app/worker/
model ports and router forwarding for IPv4/IPv6; configure and test Cloudflare
Access/MFA if only invited users should load any page. These were not modified
or externally scanned here. Existing credentials, workspaces and mail were unchanged.
