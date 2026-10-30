# Portable Backup and Restore Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for the main implementation and isolated parallel tasks for maintenance locking and owner UI. The user explicitly approved implementation; proceed without another approval gate.

**Goal:** Portable plain ZIP backups with owner controls, daily scheduling, and guarded offline restore.
**Architecture:** A file-based archive engine creates online SQLite snapshots and manifests. Offline restore validates and stages every file, rebases workspace paths, clears sessions, creates a rollback archive, and journals replacements. Shared maintenance locks exclude restore from running writers. A gateway manager provides owner-only archive downloads and daily retention.
**Tech Stack:** Python stdlib zipfile/sqlite3/hashlib, Typer, FastAPI, React Query.
**Spec:** docs/superpowers/specs/2026-10-29-backup-restore-design.md

## Global Constraints
- Plain ZIP, all workspaces including suspended admins, preserve business rows and statuses.
- No OS credential export; restored installation uses fresh credential namespaces.
- Default daily backups retain seven successful automatic archives.
- Restore is offline, requires validation and explicit replacement, and must retain rollback recovery.
- Never exercise development against real installation data.

## Review Focus
- Archive path traversal, duplicate names, symlinks and expansion limits: reject before writing destination data.
- Windows locks and WAL/SHM files: shared writers exclude exclusive restore; sidecars cannot replay old data.
- Interrupted replacement: durable journal blocks startup and supports recovery.
- Different destination paths and pre-existing credentials: rebase paths and use new namespaces.
- Unavailable or partial workspaces: fail backup if required registry identity or existing DB is unreadable; preserve old archives.

### Task 1: Maintenance boundary
- [x] Add shared/exclusive installation locking and journal guard in mailcheck/maintenance.py.
- [x] Wire gateway/server, CLI writers, database connections and configuration writes; inherit lock path into workers.
- [x] Test exclusion, shared nesting and incomplete-restore refusal.

### Task 2: Archive and offline restore
- [x] Add mailcheck/backups.py with create_archive, inspect_archive, restore_archive and recover_restore interfaces.
- [x] Test legacy/multi-admin round trips, integrity validation, unsafe ZIP rejection, path rebasing, session invalidation and fresh credential namespace.
- [x] Implement validated snapshots, manifests, staging and atomic archive publication.
- [x] Implement journaled replacement and rollback, including WAL/SHM handling and recover command.

### Task 3: Owner controls and scheduling
- [x] Add mailcheck/web/backup_routes.py and persistent scheduling settings; serialize creation with registry mutation.
- [x] Provide status, settings, create and authenticated download endpoints, default daily schedule and retention seven.
- [x] Add frontend owner backup card with sensitive-archive notice, status/history, daily setting, create/download and restore checklist.
- [x] Test nonowner denial, failed backup retention and successful rotation.

### Task 4: CLI, documentation and full verification
- [x] Add backup create/inspect/restore/recover Typer subcommands and destination/replacement options.
- [x] Document Windows migration/reconnect workflow and archive handling.
- [x] Add one release, rebuild frontend_dist, run backup/restore tests and complete regression suites.
- [x] Obtain an independent implementation review and resolve findings before completion.

Commits/push remain deferred until the user asks, consistent with this session's workflow.

## Completion evidence

- Native archive round trips, real admin-password/Done-state migration, WAL capture, failed replacement rollback, journal recovery, settings validation, ZIP traversal/duplicates, credential namespace isolation, scheduler retention, and single-use session-bound downloads tested with temporary installations.
- Independent review identified nested-directory durability and semantic settings validation gaps; both were reproduced with failing tests and fixed.
- Full backend suite: 474 passed and 76 subtests passed. Full frontend suite: 272 passed. Production build passed. A final focused safety run passed 28 tests, including writable-handle flushing after the full suite had started.
- No remaining important review findings. No commits or pushes requested during implementation.
- Windows-specific LockFileEx and MoveFileExW paths are implemented; tests ran on Linux, so actual Windows host validation remains a platform limitation.
