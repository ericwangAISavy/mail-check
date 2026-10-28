# OfferPath

**Every application, a step forward.**

OfferPath brings job sourcing, application tracking, email replies, interview
scheduling, and bidder management into one private workspace.

```
Act now  (2)
 Date   Type               Company / Role            What they want              Acct
 Jul 29 Interview invite   Acme - Backend Engineer   Offers a 30-min phone       gmail
                                                     screen; asks for 3 slots.
 Jul 29 Assessment         Hooli - Senior SRE        HackerRank test, ~90 min.   gmail
                           due 2026-08-05

For information  (2)
 Jul 28 Application recei… Globex - Data Engineer    Application received.       gmail
 Jul 27 Rejection          Initech - Platform Eng.   Declined after review.      gmail

3 noise email(s) hidden - use --all to show them.

12 unread | 4 classified | 5 cached | 3 prefiltered  across 1 account(s) in 6.2s
```

**Collection stays read-only.** Mail checks never mark messages as read. You can explicitly send replies from the Triage reader using Outlook or SMTP; nothing is sent by automatic checks. See [Replying from the app](docs/REPLIES.md).

## Install

```bash
pip install -e .
```

## Setup

Everything can be done from the web console — connecting a model, adding mailboxes,
running checks, and reading results:

```bash
python -m mailcheck web
```

It opens `127.0.0.1:52400` and walks you through setup if nothing is configured yet.
Prefer the terminal? The same steps are below.

On Triage, **Check now** and automatic web checks fetch and classify unread mail
from all enabled accounts using the existing categories. On Interview, both
**Check now** buttons collect native calendar bookings from
connected Outlook calendars through Microsoft Graph. Teams, Google Meet, Zoom,
phone and in-person bookings are included without reading inbox messages or running
classification. Calendar
collection requires read-only `Calendars.Read`; reconnect existing Outlook accounts
in Accounts after adding that permission to your Microsoft application. IMAP does
not expose calendar events and is not used as a fallback. See
[Interview tracking](docs/INTERVIEWS.md). CLI mail-triage commands retain their
existing behavior.

The web console supports one **Owner** and additional **Admins**, each with a
private workspace. Sign in as **owner** using your existing admin password, then
open **Admin management** to create admins. Added admins must change their temporary
password before accessing their own email accounts, bidders and application data.
Bidders are managed records and no longer sign in.

The owner's existing database/configuration/OS-keyring entries stay in place.
New workspaces have separate databases, credential namespaces and worker
processes. Only the owner can access Settings; all admins inherit that shared
configuration while connecting their own email accounts. A separate control database manages admin identities and revocable
12-hour HttpOnly sessions. See [Multi-admin setup and rollback](docs/MULTI_ADMIN.md)
for capacity limits, backups and returning to the previous single-admin version.

For a new installation without `web-auth.json`, first start locally with
`python -m mailcheck web --single-admin`, sign in with username `owner` and the
legacy initial password `admin`, change it in Settings, then stop and restart
without `--single-admin`. Existing installations do not need this bootstrap step.

### Share from your own server or computer

For other devices on your local network, use your computer's actual LAN IP in
`--allow-host`, and allow inbound TCP port 52400 through its firewall:

```bash
python -m mailcheck web --no-open --host 0.0.0.0 --allow-host 192.168.1.50
```

Other devices can then use `http://192.168.1.50:52400`. Replace the example IP with
your own. `0.0.0.0` is the listening address, not the address visitors enter. Repeat
`--allow-host` to allow additional hostnames/IPs; unknown Host headers are rejected.

For internet access, point a domain at your server's public IP, put an HTTPS reverse
proxy in front of the app, and keep port 52400 private. For example, with Caddy on the
same computer, replace `mail.example.com` with your domain:

```bash
python -m mailcheck web --no-open --allow-host mail.example.com --secure-cookies
```

```caddyfile
mail.example.com {
    reverse_proxy 127.0.0.1:52400
}
```

Caddy obtains and renews HTTPS certificates. Allow public TCP ports 80 and 443.
On a home network, forward those ports from the router to this computer as well;
DNS must point to the router's public IP. If your ISP uses carrier-grade NAT, use a
publicly reachable server or an HTTPS tunnel instead. Binding to `0.0.0.0` alone
does not create a public URL. A tunnel must forward the visitor's Host header and
HTTPS scheme correctly and its public hostname must be included in `--allow-host`.

**Before opening public access, change the default admin password locally.** Use HTTPS
for internet access and `--secure-cookies` so browser sign-in cookies are sent only
over HTTPS. Leave that flag off for local HTTP development. The app trusts forwarded
scheme/client information from a loopback reverse proxy; keep the proxy on the same
computer and do not expose private worker ports. Each added admin sees only their
workspace; the owner can explicitly open another workspace. The Dashboard includes
stored email subjects, summaries and message bodies, so give each admin their own
login instead of sharing the owner password. These web passwords are separate from mailbox
app passwords, which still use the OS keyring.

After startup, an unauthenticated `GET /api/dashboard` must return HTTP 401. Sign in
as an added admin and verify their workspace is empty and owner-management APIs return HTTP 403.
The React/Vite development server is for local development; share the Python app
and its bundled console through the HTTPS proxy.

**1. Point it at your Ollama server.** There is no model to configure: each check uses
whichever model the server has loaded:

```bash
mail-check init
# Ollama server URL: http://192.168.2.230:11440
```

Use the server root with no `/v1` or API path. mail-check uses Ollama's native
`POST /api/chat` API without an auth token. `init` sends a JSON health request to test it
and reports which model answered.

**How the model is chosen.** Before classifying, mail-check asks `GET /api/ps` what is
loaded and uses the most recently used chat model, skipping embedding-only models
(checked with `POST /api/show`). Load or switch models on the server (`ollama run <model>`)
and the next check follows. If nothing is loaded, typically because keep-alive expired
between checks, it reloads the model that last classified your mail. On a brand-new
install with nothing loaded, the check defers its mail to the next run and says why.
Settings → Model shows which model the next check will use.

For this LAN server, start with these settings:

```bash
mail-check config set llm.num_ctx 8192
mail-check config set llm.think false
mail-check config set llm.batch_size 5
mail-check config set llm.concurrency 1
mail-check config set llm.timeout_seconds 60
mail-check config set llm.classification_deadline_seconds 300
mail-check config set llm.keep_alive 5m
```

When migrating an existing installation, stop `watch` and pause automatic checks.
An old `/v1` endpoint prevents Settings from loading; recover it from the terminal:

```bash
mail-check init --base-url http://192.168.2.230:11440
```

This backs up the existing configuration, replaces the endpoint, drops any old `model`
setting (no longer used), and tests
the connection. Apply the runtime settings above before restoring your schedule. Mailboxes,
local rules, privacy acknowledgement, stored messages, and Done states are preserved.
Old router credentials can remain in the OS keyring; mail-check no longer reads them.

**2. Add a mailbox:**

```bash
mail-check account add
```

It detects the provider from your address and tells you how to get an app password.
Gmail needs one from [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
(2-Step Verification must be on) — your normal password will not work.

**3. Run it:**

```bash
mail-check check
```

## Usage

```bash
mail-check check                  # triage unread mail, print the report
mail-check check --since 7d       # only the last week
mail-check check --all            # include job-board noise
mail-check check --no-cache       # re-classify everything
mail-check check --json           # machine-readable output

mail-check watch                  # re-check every 10 min, notify on urgent mail
mail-check watch -i 30

mail-check web                    # management console on 127.0.0.1:52400

mail-check account list | test <label> | remove <label> | enable <label> --off
mail-check config show | set llm.batch_size 5 | set check.retain_days 30 | test
```

## The console

Three pages, all of it local:

- **Queue** (default) — only what needs you: unhandled interview invites, assessments,
  offers, info requests and recruiter outreach. The list is on the left and whatever is
  selected opens on the right: subject and sender, the model's one-line summary, company,
  role, account, and the cleaned body, with **Open in Gmail/Outlook** and **Done**. Each
  row leads with its category and deadline, then company and role, then the mailbox it
  arrived in, then the summary. Move with <kbd>↑</kbd> and <kbd>↓</kbd>, and press
  <kbd>E</kbd> to mark the selected mail done — the selection lands on the next one, so a
  full queue clears without touching the mouse.
- **All mail** — the same list, every category, grouped by urgency.
- **Completed** — what you've marked Done, with Restore.
- **Accounts** — connect an IMAP mailbox with an app password, or sign in to a personal
  Outlook account with Microsoft. Test, pause, or remove any of them.
- **Settings** — Ollama server (the model in use is shown, not chosen); thinking, context, keep-alive, request timeout,
  and classification deadline;
  automatic checks; batch size, concurrency, body length,
  lookback, retention and interval; and local sender rules that label mail before it
  ever reaches the model.

Turn on **Check automatically** in Settings and the console runs the check itself on your
interval. A live countdown — *Next check in 7:24* — sits in the toolbar on every page;
click it to switch automatic checks back off. It is off by default, because opening a page
should never start spending tokens on its own. The schedule belongs to the running console,
so closing it stops the checks; use `mail-check watch` for unattended background runs.

It binds `127.0.0.1` by default and requires owner or admin sign-in. For network
access, follow the server instructions above. Host headers are checked against the
configured allowlist, and non-GET requests carrying a foreign `Origin` are rejected.

Colours follow the light or dark setting of your OS. Status hues are contrast-validated for
text in both modes, and no tier is identified by colour alone — every one is also named.

For a scheduled run, point Task Scheduler or cron at `mail-check check` — that is all
`watch` does under the hood.

## Categories

| Tier | Category | Meaning |
|---|---|---|
| 🔴 Act now | `interview_invite` | Interview or phone screen offered |
| 🔴 | `assessment` | Coding test / take-home — **usually has a deadline** |
| 🔴 | `offer` | Offer or terms |
| 🟡 Reply | `info_request` | Wants references, salary expectations, availability |
| 🟡 | `recruiter_outreach` | Cold inbound, not from an application you sent |
| ⚪ Info | `rejection` | Declined |
| ⚪ | `application_ack` | Automated "we received your application" |
| ⚫ Noise | `job_alert` | LinkedIn/Indeed digests |
| ⚫ | `other` | Not job-related |
| ❓ | `unclassified` | The model failed — surfaced for a manual look, never dropped |

Each email also gets **company, role, deadline, action_required and a one-line summary**
extracted, which is what turns the report into a to-do list.

## Performance and reliability

Classification is cached in SQLite per `(message_id, prompt_version)`, so re-running
skips inference for cached messages. Each result also records the model that produced it,
but the cache does not depend on it: the loaded model can change on its own, and that should
not re-classify everything. Bumping `PROMPT_VERSION` (or `check --no-cache`) uses fresh
classifications on the next check; old cache records remain.

Emails go to the model **4 per request** by default with bodies stripped of HTML, quoted replies and
footer boilerplate, then truncated to 1200 characters. Known job-board senders are labelled
locally and never sent at all.

Models can return malformed JSON, so the parser handles it: it strips code fences,
pulls JSON out of surrounding prose, accepts results either listed or keyed by id, and
closes a reply that stopped mid-answer so the fields that did arrive still count. Each item
is validated on its own; missing ones are retried singly with more room and a stricter
prompt, and only then does it fall back to `unclassified`. One malformed entry cannot cost
you the other results.

Thinking starts disabled and can be enabled for a supporting model in Settings or with
`mail-check config set llm.think true`. Larger batches, contexts, and thinking can increase
memory use and response time. Output budgets map to Ollama's `num_predict`; truncated
responses retain their completion reason for recovery. If results hit the token limit,
send fewer at a time:

```bash
mail-check config set llm.batch_size 2
```

A single Ollama request defaults to 60 seconds, and the complete classification stage
defaults to five minutes. A read timeout, HTTP 429, or HTTP 503 opens the busy-server
circuit: unresolved mail stays visible as `unclassified` and is retried by the next
scheduled check. Successful and permanently malformed results remain cached.

Privacy-safe performance records are written to `performance.jsonl` in the application
data directory. The log rotates at 2 MB with three backups and contains timings, token
counts, batch sizes, and error categories only. It never records subjects, addresses,
bodies, prompts, credentials, or model output.

## Privacy

**Sender, subject, and truncated email bodies are sent to your configured Ollama server.**
With the LAN configuration above, inference runs on `192.168.2.230`; mailbox connections
still contact your email provider. Job-application mail can contain names, phone numbers,
and salary discussion. Local prefilter rules keep matching messages off the model server.

You can exclude a sensitive mailbox without deleting it:

```bash
mail-check account enable work --off
```

## Notifications

Turn on **Notify me about urgent mail** in Settings and the browser announces interview
invites, assessments and offers as they arrive — the three things worth interrupting you for.
Each message is announced once, and clicking the notification opens it in Gmail or Outlook.

Permission is granted per browser, so the switch is per browser too. Alerts fire after any
check, including automatic ones, as long as a console tab is open. Use the **Test** button to
confirm popups actually reach you: a granted permission does not by itself guarantee a
visible notification, since Windows can suppress your browser's notifications independently
(Settings → System → Notifications, and Do not disturb).

## Done is local

**Done** marks an item finished in mail-check's own database. It does not mark the message
read, move it, label it, or change anything in Gmail or Outlook — provider mail is only ever
read. Re-running a check never resurrects something you finished, and Completed can restore
it for as long as the message is kept.

## Email analytics dashboard

Open **Dashboard** to explore locally collected mail by received date. Daily category charts,
summary cards, and a searchable 50-item email list share account, category, status, action,
and date filters. Select a chart segment to narrow the list to a day and category. Filters
remain in the URL, and the existing reader supports Done, Restore, and classification retry.

Ranges cover up to 90 inclusive calendar days in the browser's timezone. Missing received
dates use collection time and are marked estimated. Dates before the first completed
collection are marked partial: deleted mail and previously uncollected mail are unavailable.
Browsing uses stored SQLite data and makes no mailbox or model requests.

This installation retains 90 days of local history. It starts with stored mail and future
checks; it does not backfill old mailbox messages or widen the fetch window.

## Local retention

The local database is a rolling window, not an archive. **Every check deletes triaged mail
older than the configured retention window**, Completed included, so a queue you have been running for months
does not turn into an unlimited archive. New configurations default to seven days;
the retention setting controls how much local history the dashboard can show.

```bash
mail-check config set check.retain_days 30    # keep a month instead
```

This only ever deletes from mail-check's own database. The message itself is untouched in
Gmail or Outlook, still unread, exactly as it was — deleting the local copy is not a
mailbox operation and never becomes one.

A check never prunes inside its own fetch window, even when `lookback_days` is set wider
than `retain_days`; the effective window is whichever is longer. That is what keeps Done
from quietly undoing itself: a message deleted and re-downloaded on the same run would
come back as a new row with nothing marked on it. The one way to resurface finished mail
is to deliberately reach back past the retention window — `mail-check check --since 30d`
will re-fetch anything still unread that has already been pruned, and it arrives as new.

## Outlook

Personal **Outlook.com, Hotmail and Live** accounts sign in with Microsoft instead of a
mailbox password — Microsoft disabled basic-auth IMAP, so app passwords cannot work there.

One-time setup: register a **public client** application in the Microsoft Entra admin
center with delegated `Calendars.Read`, `Mail.Read` and `Mail.Send` permissions and device-code flow enabled, then paste its
Application (client) ID into Settings → Outlook. That ID is a public identifier, not a
secret; no client secret is used or stored. Accounts → *Outlook.com, Hotmail, Live* then
shows a code to enter at Microsoft's sign-in page. Tokens live in the OS keyring and are
deleted with the account.

Microsoft 365 work and school accounts are out of scope.

## Known limitations

- Each email is classified in isolation; replies within a thread are not grouped.
- The Outlook sign-in flow is covered by tests against a stand-in Graph server, but has not
  been run against a real Microsoft tenant.

## Development

```bash
python tests/test_smoke.py
python -m unittest discover -s tests
python -m tests.benchmark_analytics
```

The React console lives in `frontend/` and is built with Vite, TypeScript,
Tailwind CSS, and shadcn/ui. Use Node.js 20 or newer while developing:

```bash
npm --prefix frontend install
npm --prefix frontend run test
npm --prefix frontend run build
```

The build writes the bundled, self-contained UI to `mailcheck/web/frontend_dist/`;
it is included in Python package builds so installed users need only Python. For
hot reload, run `mail-check web --no-open` in one terminal and
`npm --prefix frontend run dev` in another, then open <http://127.0.0.1:5173>. The Vite server
forwards API requests to the local FastAPI console.

Runs the whole pipeline against a fake mailbox and a fake model — including the malformed-JSON
paths — with no network and no credentials. See [docs/DESIGN.md](docs/DESIGN.md) for the
architecture and the reasoning behind each decision.

### Bidder payments

Admins can assign accounts to bidders and manage their daily/weekly application totals
and payment records inside their own workspace. Bidders do not sign in. Weeks run
Monday–Sunday in America/Chicago. See [Bidder payments](docs/BIDDER_PAYMENTS.md)
for setup, counting rules, and payment history behavior.


### Native Job sourcing

Use Job sourcing to keep bidder job applications in mail-check’s own spreadsheet
workspace: profile tabs, rectangular copy/paste, formatting, sorting/filtering, checked
autosaves, CSV import/export, and application search from interview details. Each
workspace keeps its bidders’ workbooks separate from other admins. No Google connection is required.
See [Job sourcing setup, import and backups](docs/JOB_SOURCING.md).

OfferPath's current version is available beside the app name; select it to read
update history. See [release history](docs/CHANGELOG.md) and
[versioning instructions](docs/VERSIONING.md) for future updates.
