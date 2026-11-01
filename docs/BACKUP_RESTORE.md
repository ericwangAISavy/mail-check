# Backup and move OfferPath to another PC

Backups are **plain ZIP files** containing private mail, workspace databases, settings, and sign-in password hashes. Keep them in a private folder or protected drive. Only the owner can create or download backups in Admin management.

## Back up

Open **Admin management → Backup & restore → Create backup**, then download the archive. The gateway also makes a daily automatic backup while running; the default retention is seven successful automatic backups. Manual backups are retained until you remove their files. A failed backup never rotates away older successful archives. The card shows the server-side backup folder, last result, and next due time. Keeping backups only on the server disk does not protect against that disk failing; copy downloaded archives to another drive or PC.

Online backups use SQLite's backup API, including committed WAL data. Each database is a consistent snapshot; independently active admin workspaces are not one simultaneous transaction. For the final migration snapshot, stop OfferPath and use the offline command:

```powershell
python -m mailcheck backup create E:\Backups\offerpath-move.zip
```

Stop background watch/CLI jobs too. The same archive includes the owner and all registered workspaces, including suspended admins, with existing mail history, Done states, sourcing checks, bidder assignments, calendar events, payments, and sign-in passwords. Application binaries, Python environments, OS keyring credentials, runtime logs/locks, existing backups, Cloudflare credentials, and Ollama models are excluded.

## Restore on the new Windows PC

1. Install Python and the **same OfferPath release** that created the archive. Create a new virtual environment and run `python -m pip install -e .` from the application folder.
2. Copy the ZIP to the new PC. Keep the original server stopped for the final move so the two installations do not diverge.
3. Inspect the archive before restoring:

   ```powershell
   python -m mailcheck backup inspect E:\Backups\offerpath-move.zip
   ```

4. Restore before starting the new server:

   ```powershell
   python -m mailcheck backup restore E:\Backups\offerpath-move.zip
   ```

   A fresh destination is the default. To replace existing destination data, use `--replace`. The command creates a rollback ZIP first and prints its location. It does not merge installations. Advanced destination overrides are `--config-path`, `--db-path`, and `--control-dir`; use the same overrides with recovery. The command prints PowerShell environment variables (`OFFERPATH_LEGACY_CONFIG_PATH`, `OFFERPATH_LEGACY_DB_PATH`, `OFFERPATH_CONTROL_ROOT`) that must also be set when starting the server with custom paths.
5. Start the server and sign in with the existing owner/admin/bidder passwords:

   ```powershell
   python -m mailcheck web --no-open
   ```

6. Reconnect Outlook accounts and re-enter IMAP credentials. Restored accounts use a fresh credential namespace, so similarly named destination credentials are not silently reused. Check Ollama/server addresses, firewall/LAN IP and startup options, and your Cloudflare tunnel independently.
7. Verify mail history, all workspaces, sourcing links, checked totals, payments and calendar events before retiring the old PC.

## Interrupted restore

Restore stages and verifies the complete archive before changing destination files. It rejects running OfferPath writers, corrupt databases, invalid checksums, missing workspace markers, unsafe ZIP paths and unsupported versions. It records replacements in a durable journal and handles SQLite WAL/SHM files explicitly.

If the PC shuts down or restore is interrupted, normal startup refuses to use a partially restored installation. Stop the server and run:

```powershell
python -m mailcheck backup recover
```

Recovery rolls back an incomplete replacement or completes cleanup after a committed restore. Keep the journal and rollback files until recovery succeeds. Do not manually delete the journal to bypass this check. The source archive and Windows Credential Manager entries are not deleted by restore or recovery.
