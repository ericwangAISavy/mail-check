"""Which accounts real-time collection is currently keeping fresh.

Scheduled full checks and bidder live Inbox checks skip these accounts, so the
single shared model worker is not spent re-collecting mail that push
notifications and recovery checks already collected. Coverage is health-based:
an account counts only while its last real-time sync is recent, so if the
background service stops, the scheduled check becomes its safety net again.
"""
from __future__ import annotations

import sqlite3
import time

#: Real-time recovery checks run every 2 minutes (Outlook) or 30 seconds (IMAP).
#: A sync older than this means real-time is not keeping the account current.
FRESH_SECONDS = 10 * 60
#: Interval for full checks once real-time covers every enabled account. They
#: still verify sourcing sheets, prune retained mail and act as a safety net.
HOUSEKEEPING_MINUTES = 30


def _configured() -> bool:
    from .realtime.settings import Settings
    try:
        return Settings.from_env().enabled
    except ValueError:
        return False


def last_syncs(conn) -> dict[int, float]:
    """{account_id: last real-time sync (epoch seconds)} for opted-in, enabled accounts."""
    if not _configured():
        return {}
    try:
        rows = conn.execute('SELECT r.account_id, r.last_sync FROM realtime_accounts r '
                            'JOIN accounts a ON a.id=r.account_id WHERE a.enabled=1 AND r.enabled=1').fetchall()
    except sqlite3.Error:
        return {}
    syncs = {}
    for account_id, last_sync in rows:
        try:
            syncs[int(account_id)] = float(last_sync) if last_sync is not None else 0.0
        except (TypeError, ValueError):
            syncs[int(account_id)] = 0.0
    return syncs


def covered_accounts(conn, *, now: float | None = None) -> set[int]:
    now = time.time() if now is None else now
    return {account_id for account_id, last in last_syncs(conn).items()
            if last and 0 <= now - last <= FRESH_SECONDS}


def interval_minutes(conn, cfg) -> int:
    """Full checks slow to housekeeping only while real-time covers every enabled account."""
    from . import db
    enabled = {account.id for account in db.list_accounts(conn, only_enabled=True)}
    if enabled and enabled <= covered_accounts(conn):
        return max(cfg.watch.interval_minutes, HOUSEKEEPING_MINUTES)
    return cfg.watch.interval_minutes


def tightened(next_due: float | None, minutes: int, *, now: float | None = None) -> float | None:
    """Pull a long housekeeping wait in when coverage lapses; never push a check later."""
    if next_due is None:
        return None
    now = time.time() if now is None else now
    return min(next_due, now + minutes * 60)
