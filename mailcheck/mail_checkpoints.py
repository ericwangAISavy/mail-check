"""Durable per-mailbox mail collection checkpoints, independent of run history."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

OVERLAP = timedelta(minutes=2)
SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_checkpoints (
 account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
 mailbox TEXT NOT NULL,
 checked_at TEXT,
 pending_since TEXT
);
"""


def mailbox_key(account):
    identity = ["inbox-and-junk-v1", account.provider, account.email.casefold(), account.imap_host,
                account.imap_port, account.use_ssl, account.folder]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def _valid_stamp(row, account, field, now):
    if not row or row["mailbox"] != mailbox_key(account):
        return None
    try:
        value = datetime.fromisoformat(row[field])
        if value.tzinfo is None or value > now:
            return None
        return value.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def checkpoint(conn, account):
    row = conn.execute("SELECT mailbox,checked_at FROM mail_checkpoints WHERE account_id=?", (account.id,)).fetchone()
    return _valid_stamp(row, account, "checked_at", datetime.now(timezone.utc))


def snapshot(conn, accounts):
    """Read account-card checkpoints together rather than issuing N queries."""
    rows = {row["account_id"]: row for row in conn.execute("SELECT account_id,mailbox,checked_at FROM mail_checkpoints")}
    now = datetime.now(timezone.utc)
    return {account.id: _valid_stamp(rows.get(account.id), account, "checked_at", now) for account in accounts}


def _pending(conn, account):
    row = conn.execute("SELECT mailbox,pending_since FROM mail_checkpoints WHERE account_id=?", (account.id,)).fetchone()
    return _valid_stamp(row, account, "pending_since", datetime.now(timezone.utc))


def begin(conn, account, since):
    """Anchor a first attempt so failures cannot slide its fallback window."""
    if checkpoint(conn, account):
        return
    instant = since if isinstance(since, datetime) else datetime.combine(since, datetime.min.time(), timezone.utc)
    stamp = instant.astimezone(timezone.utc).isoformat(timespec="microseconds")
    conn.execute("""INSERT INTO mail_checkpoints(account_id,mailbox,pending_since) VALUES(?,?,?)
        ON CONFLICT(account_id) DO UPDATE SET
            checked_at=CASE WHEN mail_checkpoints.mailbox=excluded.mailbox THEN mail_checkpoints.checked_at ELSE NULL END,
            pending_since=CASE WHEN mail_checkpoints.mailbox=excluded.mailbox AND mail_checkpoints.pending_since<excluded.pending_since
                               THEN mail_checkpoints.pending_since ELSE excluded.pending_since END,
            mailbox=excluded.mailbox""", (account.id, mailbox_key(account), stamp))


def window_start(value):
    return value if isinstance(value, datetime) else datetime.combine(value, datetime.min.time(), timezone.utc)


def window(conn, account, check, since_days, now):
    fallback = (now - timedelta(days=since_days if since_days is not None else check.lookback_days)).date()
    if since_days is None and check.mode == "since_last":
        previous = checkpoint(conn, account)
        if previous:
            return previous - OVERLAP
        pending = _pending(conn, account)
        if pending:
            # Preserve failed attempts, while honoring an explicitly widened
            # first-check lookback. Never slide a retry's lower bound forward.
            return min(pending, window_start(fallback))
    return fallback


def record(conn, account, started_at):
    stamp = started_at.astimezone(timezone.utc).isoformat(timespec="microseconds")
    now = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    conn.execute("""INSERT INTO mail_checkpoints(account_id,mailbox,checked_at) VALUES(?,?,?)
        ON CONFLICT(account_id) DO UPDATE SET mailbox=excluded.mailbox,checked_at=excluded.checked_at,pending_since=NULL
        WHERE mail_checkpoints.mailbox!=excluded.mailbox
           OR mail_checkpoints.checked_at IS NULL
           OR mail_checkpoints.checked_at<excluded.checked_at
           OR mail_checkpoints.checked_at>?""", (account.id, mailbox_key(account), stamp, now))
