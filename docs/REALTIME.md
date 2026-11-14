# Automatic email and calendar updates

OfferPath can collect account changes in the background and update open pages without
refreshing. Enable this separately for each account in **Accounts → Automatic updates**.
Collection remains read-only; notifications never send replies or mark mail as read.
The app must remain running. A sleeping/offline Windows host cannot receive notifications.

## Start the services without Docker

Install the optional dependency in the same Python environment as the app:

```sh
python -m pip install -e ".[realtime]"
```

OfferPath runs directly in Python. Redis is a separate service; it does not need a
container. Use Redis 7 or newer with Streams, consumer groups, XAUTOCLAIM, and Lua scripts.
For a local Redis server, [deployment/redis.conf](../deployment/redis.conf) binds only to
loopback and enables AOF persistence with fsync for each write. Start it from a private,
persistent data directory, since the configuration uses the current directory for data.
Do not publish Redis through Cloudflare or a router, or delete its data while jobs are pending.

### Windows host

Redis does not provide an official native Windows Redis 7 server. Choose one of:

- **WSL2:** run Redis inside a current Linux distribution, while OfferPath and cloudflared
  continue running directly on Windows. For example, install Ubuntu 24.04 using
  `wsl --install -d Ubuntu-24.04`, then install `redis-server` with that distribution's
  package manager and check `redis-server --version` reports version 7 or newer.
- **A native Windows Redis-compatible service:** confirm Redis 7 Streams, XAUTOCLAIM,
  consumer groups, Lua scripting and persistence support before choosing a product.
  Avoid obsolete unofficial Windows Redis builds. Configure its equivalent persistence
  and loopback settings; configuration syntax may differ from Redis.
- **A remote Redis service:** use an authenticated TLS endpoint (`rediss://`). Confirm
  support for blocking Streams reads, Lua scripts, and durable writes; an HTTP-only
  Redis API is not compatible with this implementation.

For WSL, stop any automatically started default Redis service before starting a custom
instance on the same port. In the WSL shell, create a private data directory and start
Redis with the supplied configuration (adjust the repository path):

```sh
mkdir -p ~/.local/share/offerpath-redis
chmod 700 ~/.local/share/offerpath-redis
cd ~/.local/share/offerpath-redis
redis-server /mnt/d/WorkSpace/mail-check/deployment/redis.conf
```

Keep that process running, or configure the Linux service manager to use this configuration
and data directory. Windows-to-WSL localhost forwarding normally permits the Windows app
to connect to port 6379; verify connectivity from Windows using the Python check below.

For Windows PowerShell, set these variables in the terminal used to start OfferPath:

```powershell
$env:OFFERPATH_REDIS_URL = "redis://127.0.0.1:6379/0"
$env:OFFERPATH_PUBLIC_URL = "https://app.offerpath.bid"
python -m mailcheck web --no-open --tunnel --allow-host app.offerpath.bid --max-workspaces 30
```

Use your actual domain. All workspace workers inherit these settings. Set the owner
password using `python -m mailcheck web-password` first if it is not initialized.
Existing strong passwords and user data are preserved. On POSIX export the same variables.

Verify the connection from the same Python environment before starting OfferPath:

```powershell
python -c "import os,redis; r=redis.Redis.from_url(os.environ['OFFERPATH_REDIS_URL']); print('Connected:',r.ping()); print('Version:',r.info('server')['redis_version'])"
```

The check reads the configured URL without printing credentials. For a compatible service,
also run the dedicated Redis integration tests below; the reported version alone does not
prove command compatibility. Provision the remote service's persistence settings separately.

### Native Linux server

Install Redis 7+ through the operating system's trusted package source, then start
`redis-server /absolute/path/to/deployment/redis.conf` from a private persistent data
directory, or configure a system service with the equivalent settings. A remote server
needs authentication, TLS, and network rules permitting only the app host; do not change
the local example to bind publicly without those controls.

Open Accounts and explicitly enable the desired accounts. Merely configuring Redis does
not enable mailbox collection or create provider subscriptions. Normal manual checks stay
available when this feature is disabled. Runtime startup is automatic in workspace workers;
there is no separate Celery or Kafka installation.

## Outlook and Cloudflare

Existing Microsoft delegated sign-in requires Mail.Read and Calendars.Read. Reconnect
through Accounts if the provider reports missing consent. OfferPath creates read-only
change subscriptions only for opted-in Outlook accounts and renews them automatically.
The notification endpoint is `POST /hooks/microsoft` on the configured HTTPS root URL.

Configure Cloudflare Tunnel's origin as HTTP `127.0.0.1:52400`, HTTP Host Header matching
the domain, and preserve forwarded HTTPS information. Disable buffering for the
`text/event-stream` response at `/api/realtime/events`; avoid cache rules on API/hooks.
If Cloudflare Access is enabled, the **exact** `/hooks/microsoft` callback path must be
reachable by Microsoft without interactive login. Keep Access protection for the app and
other APIs. The callback itself verifies the registered subscription and a random hashed
client-state secret; a browser cookie never authorizes a notification. Validation challenges
are echoed as plain text. A valid notification is acknowledged only after Redis accepts work.

The server fetches actual email/calendar data through Graph rather than trusting callback
contents. Mailbox-wide message notifications cover Inbox and Junk arrivals; the mail
collector continues to import only its supported Inbox/Junk folders. Existing subscriptions
are replaced when their resource or callback address changes. Calendar notifications use the
account events resource; periodic reconciliation includes calendars supported by the existing collector. New bookings,
reschedules, cancellation/deletion and recurring-instance reconciliation use that collector's
existing identity and manual-edit rules. The supported calendar window is the collector's
one-year past/future window, not a complete historical calendar archive.

Outlook recovery checks run every 120 seconds; IMAP mail checks run every 30 seconds.
IMAP uses bounded polling in this release, not IDLE or Gmail Pub/Sub. IMAP cannot read
calendar events. Collection saves mail before separate classification jobs, so a slow model
does not prevent new mail/calendar collection. Classification still needs the configured model.

## Delivery and recovery

Workspace-specific Redis Streams hold mail, calendar and classification hints; streams never
contain message bodies, passwords or model prompts. Workers renew job/account leases,
reclaim abandoned work, retry failures with bounded backoff and move repeatedly failing
jobs to dead-letter streams. Reconciliation schedules fresh catch-up work after an outage.
Paused/deleted accounts and accounts that opt out are checked again before commits.

SQLite triggers insert topic-only outbox rows in the same transactions as data changes.
The outbox publishes after commit and retains hints if Redis is unavailable. Repeated changes
coalesce to the newest pending identity for each topic, including sourcing, payments and
pipeline changes. Publication acknowledges only captured identities, preserving newer changes.
These are refresh hints, not a per-edit audit history. Change streams
retain a bounded replay window; each browser reads independently, refreshes on reconnect,
and performs ordinary authenticated API reads. Server-sent events have separate finite
capacity from page requests and worker heartbeats, periodic session checks, and slow-send
deadlines. Switching workspace/signing out closes the previous stream.

Accounts shows opt-in, recent sync, and degraded collection/subscription state. In a Redis
outage manual checks remain possible, but live browser delivery/queued processing pauses.
Do not replay arbitrary dead-letter jobs blindly; diagnose credentials, provider throttling,
model availability and the account's opt-in first. Queue keys use hashed workspace namespaces.

## Verify deployment

1. Confirm Redis health with the Python connection check above, or local `redis-cli ping`.
2. Enable a test account. Verify its subscription/sync status in Accounts.
3. Send a test email; verify it appears without page refresh, then receives classification.
4. Create, reschedule and cancel a test calendar event and verify each change.
5. Close all browser tabs and repeat; reopening must show collected changes.
6. Restart Redis/app and verify catch-up without duplicates or altered Done/manual states.
7. Test two admins and a bidder: only their authorized workspace/API data may appear.
8. Through the actual Windows tunnel verify live streaming, ordinary login/navigation,
   and callback delivery together. Synthetic development tests cannot prove provider/tunnel access.

To turn off provider monitoring, disable opted-in accounts and allow subscription cleanup
before removing environment settings or stopping Redis. Removing OFFERPATH_REDIS_URL and
restarting disables live processing while preserving existing mailbox records/manual checks.
Remote subscriptions that cannot be deleted expire naturally; no write permissions are used.

## Development checks

Use a dedicated test Redis instance, never a production broker. For example:

Start a separate native Redis process from a temporary test data directory:

```sh
redis-server /absolute/path/to/mail-check/deployment/redis.conf --port 56379
```

In a second terminal, from the repository:

```sh
OFFERPATH_TEST_REDIS_URL=redis://127.0.0.1:56379/0 python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

Stop the test Redis process with Ctrl+C after checks finish. In PowerShell set
`$env:OFFERPATH_TEST_REDIS_URL` before running pytest. Keep frontend
builds sequential with backend tests: Vite replaces bundled files that static-page tests
read. Real-Redis tests skip when the test URL is absent; synthetic provider tests never
create Microsoft subscriptions or connect to real mailboxes.
