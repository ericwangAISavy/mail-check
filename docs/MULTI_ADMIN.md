# Owner-managed OfferPath workspaces

## Sign in and add admins

Run the same command as before:

```powershell
python -m mailcheck web --no-open --host 0.0.0.0 --allow-host 192.168.1.76
```

Sign in with username **owner** and your existing admin password. No new owner
password is created. The original `web-auth.json` must exist and be readable;
if it is missing in an existing installation, recover it from your trusted backup.
For a fresh installation only, start locally with `--single-admin`, sign in as
`owner` with the legacy initial password `admin`, change the password in Settings,
then stop and restart normally. Do not expose this initial setup server to the network.

Open **Admin management**. Create a username, workspace name, and temporary
password of at least 12 characters. Give those credentials to the admin yourself;
OfferPath does not email credentials. The new admin must replace the temporary
password before accessing workspace data. They start with no email accounts or
bidders and connect their own email accounts. Only the owner can open or edit
Settings; all workspaces use the owner’s Model, Outlook client ID, local rules,
and checking preferences. Added admins can change their own login password from
the header. Automatic checking is managed by the owner; manual checks remain
available to every admin.

Only the owner can create/reset/suspend admins or explicitly open another
workspace. The workspace banner always identifies whose data is open. Opening
another workspace revokes the previous session and records an audit event.
Other tabs detect the changed workspace and reload their identity before loading
private data. Finish edits in other tabs before switching.

Bidders are records managed by admins. The new public gateway does not support
bidder login, password management, public bidder-name lookup, or old bidder
session cookies. Historical bidder records and legacy authentication files are
retained for compatibility and rollback.

## Isolation and capacity

Each enabled workspace has its own local worker process, SQLite database,
check scheduler, email-send ledger and credential namespace. Settings are shared
from the owner’s configuration file; any older workspace settings files remain
preserved but are not used by managed workers. Owner settings changes update
running workspace schedules without restarting their jobs. New
workspaces live inside `offerpath-control/workspaces/<id>` beside the original
configuration directory. The original workspace keeps its existing database,
configuration and OS-keyring names. New workspace IDs are server-generated.

The gateway alone listens on the requested network address. Private workers bind
to loopback and require random per-launch authentication. Never expose worker
ports or copy worker secrets. Authentication cookies are HTTP-only and SameSite
Strict. Use HTTPS with `--secure-cookies` when deploying behind a reverse proxy.

Default capacity is **4 enabled workspaces, including the owner**. Increase it
explicitly, for example `--max-workspaces 8`, only after measuring available RAM
and workload on the actual host. Keep the same capacity flag in future startup
commands when you have more than four enabled workspaces. Workers stay running so scheduled checks do not
depend on an open browser. Suspending an admin revokes their sessions and stops
their worker; it preserves data. Already dispatched email cannot be recalled.
A single gateway instance is enforced by an OS file lock.

Model generation/loading is queued across workspaces with one active request at
a time. Prompts and results remain inside their originating worker. Failed-worker
leases are recovered; worker startup retries use backoff and a bounded retry
budget. Admin management shows unavailable/restarting worker health. Local worker
logs are under `offerpath-control/logs`; do not share logs without checking them
for private operational information.

This is a bounded single-host design, not a claim of unlimited capacity or a
multi-host deployment. Tests exercise two real workers on Linux. Native Windows
multi-process and production load verification are required before expanding the
workspace limit; Windows web servers keep the existing selector-loop workaround.

## Reverting the feature

Before the original worker starts for the first time, OfferPath creates a
read-only-source SQLite online backup and copies the original configuration and
authentication file to **`offerpath-control/rollback-original`**. The manifest
records original paths and backup hashes. An incomplete backup blocks original
worker startup. Backup creation does not rewrite source files. New business-table
columns/migrations are not introduced by the multi-admin feature.

**Code rollback that preserves current business data:**

1. Stop OfferPath with Ctrl+C and let its workers stop.
2. Check out pre-feature commit **`8c320f0`**:
   `git switch --detach 8c320f0` (or the local branch
   `rollback/pre-multi-admin-2026-10-27` where available).
3. Reinstall editable code if needed: `python -m pip install -e .`.
4. Run your original web command and sign in with your existing admin password.

The original app still finds its original database/configuration/credential keys.
The new control database and added-admin workspaces stay separate and can be kept
for a future return to multi-admin mode. Do not merge them into the original DB.
The development repository also has `/workspace/offerpath-pre-multi-admin.bundle`
as an independent Git backup; this file is not a backup of your production data.

For a temporary startup fallback without checking out old code, the new version
accepts `--single-admin`. It runs the original standalone backend; it is a
compatibility/rollback mode and does not provide multi-workspace isolation.
The current UI remains the new owner/admin UI, so checking out `8c320f0` is the
complete UI/behavior rollback.

**Restoring the exact pre-activation business snapshot** is a separate operation:
stop all processes, retain a backup of the current files, then restore the files
listed in the rollback manifest to their original paths. Restoring an older SQLite
database also requires managing its WAL/SHM files while all connections are closed.
Do not overwrite a live database. A snapshot restore discards work received or
entered since that snapshot. Feature rollback cannot recall emails already sent
or undo later changes made to external accounts or the OS keyring.

## Backing up added-admin workspaces

For a complete host backup, stop the gateway and all workers first. Preserve the
control directory (including `control.db` and each workspace's `config`/`data`
directory), plus the original workspace files at their original locations. Keep
the OS credential store intact: mailbox passwords and OAuth refresh tokens are
not exported to SQLite or configuration backups. Moving to another machine may
require reconnecting mail accounts. The original-workspace activation snapshot
is a rollback checkpoint, not a replacement for ongoing backups.

## Refreshing bidder counts

Bidder management provides two actions for the displayed Monday–Sunday week in
America/Chicago. **Refresh this week** adds/repairs matching stored confirmations
and recalculates estimates without removing existing checks. **Fully rebuild this
week** also clears automatic checks in that week whose supporting match no longer
exists. Both include archived sheets that contribute to accounting and older
sourcing dates whose completion falls in the selected week. Neither action
fetches new mail, reclassifies messages, deletes retained confirmation receipts,
rewrites historical check-run samples, or changes recorded payment amounts.
Use Check now first when new mailbox messages are needed.

Manual checks with recorded manual/baseline provenance remain protected, including
manual checks that later acquire an automatic confirmation match. Older releases
could overwrite that provenance with `confirmation`; the original manual origin
of those older records cannot be reconstructed reliably. Use **Refresh this week**
when every historical check must be retained.
