# Incremental Mail Checks Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Provide fixed lookback and saved per-account checkpoint modes for every mail check entry point.
**Architecture:** SQLite stores mailbox-bound successful check start times. The shared pipeline selects account windows and commits checkpoints only for durably processed accounts; provider adapters accept precise datetime windows.
**Tech Stack:** Python, SQLite, IMAP, Microsoft Graph, React, TypeScript.
**Spec:** docs/superpowers/specs/2026-11-02-incremental-mail-checks.md

## Global Constraints

- Existing configuration defaults to fixed lookback.
- Never mark mail read or skip read messages.
- Do not alter stored mail, credentials, or production settings for this implementation.
- Include schema migration, minor release, generated frontend, and relevant verification.

## Review Focus

- A failed mailbox must preserve its checkpoint without blocking healthy accounts.
- Midnight, UTC offsets, and stale sender dates must not lose arrivals.
- A deferred classification must remain eligible on the next check.
- Retention must not discard Done state within catch-up windows.
- Restart, account configuration changes, and explicit lookback overrides must be safe.

### Task 1: Persistent windows and pipeline

**Files:** mailcheck/mail_checkpoints.py (new), mailcheck/db.py, mailcheck/config.py, mailcheck/pipeline.py; tests/test_incremental_checks.py (new).
**Interfaces:** checkpoint(conn, account) -> datetime | None; record(conn, account, started_at) -> None; window selection passes date or UTC datetime to fetch_account.
- [x] Write tests for first/follow-up checks, partial failures, deferred classifications, explicit lookback, persistence, mailbox changes, and retention; confirm failure.
- [x] Add schema and helper, preserve default configuration, compute per-account windows, and advance safe checkpoints.
- [x] Run the focused tests and existing mail pipeline checks.

### Task 2: Provider precision

**Files:** mailcheck/sources/base.py, mailcheck/sources/outlook.py, mailcheck/sources/imap.py; tests/test_mail_collection.py.
**Interfaces:** fetch_unread(since: date | datetime, include_read=False) preserves date semantics and applies precise received-time semantics for datetime.
- [x] Test precise Graph filters, IMAP INTERNALDATE metadata filtering, read-only body fetch, missing metadata, and timezone boundaries; confirm failure.
- [x] Implement timestamp collection without filtering on sender Date headers.
- [x] Run provider regressions.

### Task 3: Saved settings and visibility

**Files:** mailcheck/web/app.py, frontend/src/lib/types.ts, frontend/src/pages/settings.tsx, frontend/src/pages/accounts.tsx and their tests.
**Interfaces:** settings check.mode is lookback | since_last; account.last_checked_at is optional ISO UTC text.
- [x] Test settings mode roundtrip and last-check display.
- [x] Add labeled mode options, first-check explanation, fallback lookback input, and per-account timestamp.
- [x] Run API/frontend checks, release minor, production build, and full backend suite.
