# Portable OfferPath backup and restore

## Purpose and chosen approach

Move a complete OfferPath installation's stored state between PCs without copying folders manually. The user selected a plain backup archive rather than password protection. Archives contain private mail and password hashes, so the owner interface will identify them as sensitive files.

The approach is one portable ZIP format shared by scheduled backups, owner downloads, and offline restore. A DB-only export would omit workspaces, settings, and admin access. Live browser restore would risk replacing databases while workers are using them, so restore runs with the server stopped.

## Included state

- Owner's original database, config.toml, and web-auth.json, using the actual configured paths.
- Control database and every registered workspace, including suspended admins.
- Each workspace's identity marker, configuration, business database, and app authentication files where present.
- Manifest with format version, app version, UTC creation time, workspace inventory, and file hashes.

Preserve mail history, classifications, Done state, sourcing links and checks, assignments, bidders, calendar events, payments, account definitions, and password hashes. Clear browser sessions only in restored copies, so users sign in again after migration. Preserve source files and running-server sessions during backup.

Exclude Windows Credential Manager secrets, Outlook token caches, application binaries, Python environments, logs, runtime locks, existing backups, Cloudflare credentials, and Ollama models. Restore instructions explain reconnecting mail accounts and checking model/server addresses and network settings. Install the same application release on the destination PC first.

## Backup behavior

- Owner-only controls in Admin management show backup status, create/download a backup, and configure daily automatic backups.
- Builder choice: default schedule is once per 24 hours while the server runs, retaining the latest seven successful automatic backups. Allow disabling automatic backups and changing retention. Expose the local backup folder and a reconnect checklist.
- Use SQLite's online backup API for WAL-safe, transactionally valid database copies, never raw-copy an open database.
- Serialize backup jobs and registry mutations. Snapshot each workspace independently; the archive records its creation window rather than claiming a single simultaneous transaction across all workspaces.
- Verify manifest hashes and SQLite integrity before atomically publishing an archive. Rotate old automatic archives only after a new valid backup succeeds. A failed backup remains visible as an error and preserves prior backups.
- Keep the archive streaming/file-based so large installations do not require loading the whole archive into RAM. Downloads require the current owner session and workspace guard and use no-store responses.

## Restore behavior

Provide `python -m mailcheck backup inspect FILE.zip` and `python -m mailcheck backup restore FILE.zip`.

- Inspect displays archive version, date, and workspace inventory without modifying the installation.
- Restore requires a stopped server and exclusive maintenance access covering the gateway, standalone server, CLI writers, and surviving workers. Add a shared maintenance-lock contract for every writer; its lock file must be outside directories replaced by restore and acquired before initialization. Restore validates the complete archive before replacing any destination files.
- Reject invalid manifests, unsupported formats/application versions, missing required files, incorrect hashes, corrupt SQLite databases, unsafe archive paths, symbolic links, and excessive expansion.
- Restore into a staging directory; validate workspace IDs and rewrite registry paths to destination locations. Never use paths supplied by the archive as filesystem destinations.
- A fresh destination is the default. Replacing existing data requires an explicit replace option and a successfully created rollback backup first.
- Write and flush a durable restore journal before replacement. If applying restore fails, restore the prior destination files. On process termination or power loss, startup must detect the journal and recover or refuse normal startup until recovery finishes. Handle destination SQLite WAL/SHM sidecars explicitly so old transactions cannot replay into restored databases. Retain the rollback archive and report its path. Do not delete the source archive.
- Mark restored accounts as needing reconnect and use a new credential namespace on the destination. Never silently reuse pre-existing keyring entries with matching account labels or workspace IDs; preserve destination credentials for rollback. Reconnect writes credentials to the restored installation’s namespace.
- Report success only after all files and registry references validate. Show the start command and mail/model/network reconnect checklist.

## Compatibility and scope

Support owner-managed multi-admin installations and the legacy owner's original files. Use the existing configuration path helpers and explicit legacy path overrides. No business schema migration is needed for this feature. Do not edit real application data during development; tests use temporary installations.

## Verification

Test complete create/inspect/restore round trips, all admin workspaces and suspended users, preserved business rows and Done/check/payment state, rebased paths, fresh and replacement restore, lock refusal for every writer, interrupted restore recovery and WAL/SHM handling, rejection of pre-existing destination keyring credentials, authentication enforcement, daily scheduling/retention, interrupted backups, rollback after restore failure, and malformed or unsafe archives. Run relevant UI tests, backend regression tests, release consistency checks, and the production frontend build.

## Approval

Approved by the user: "go ahead implementation." Archive protection choice: plain ZIP.
