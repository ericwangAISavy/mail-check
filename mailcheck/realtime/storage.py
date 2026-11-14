"""SQLite opt-ins, transactional invalidation outbox and subscription registry."""
from __future__ import annotations

import hashlib
import hmac
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path


def initialize(conn: sqlite3.Connection) -> None:
    """Install inside the caller's migration transaction, without executescript."""
    conn.execute('''CREATE TABLE IF NOT EXISTS realtime_accounts (
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
        enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)),
        last_sync REAL, last_error TEXT NOT NULL DEFAULT '')''')
    conn.execute('''CREATE TABLE IF NOT EXISTS realtime_runtime (
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0,1)))''')
    conn.execute('INSERT OR IGNORE INTO realtime_runtime(id,enabled) VALUES(1,0)')
    conn.execute('''CREATE TABLE IF NOT EXISTS realtime_outbox (
        id INTEGER PRIMARY KEY AUTOINCREMENT, topic TEXT NOT NULL)''')
    # Keep the newest identity for each topic when upgrading an existing backlog.
    # Replacing a hint must allocate a new ID: a publisher may still be ACKing
    # the previous identity after another transaction changes the same topic.
    conn.execute('''DELETE FROM realtime_outbox WHERE id NOT IN
        (SELECT MAX(id) FROM realtime_outbox GROUP BY topic)''')
    conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS realtime_outbox_topic ON realtime_outbox(topic)')
    tables = {
        'accounts': 'accounts', 'realtime_accounts': 'accounts',
        'messages': 'messages', 'classifications': 'classifications',
        'interview_events': 'interviews', 'interview_event_removals': 'interviews',
        'interview_sources': 'interviews', 'interview_source_details': 'interviews',
        'interview_calendar_state': 'interviews',
        'interview_account_process_state': 'interviews',
        'interview_manual_processes': 'interviews',
        'interview_process_pins': 'interviews', 'interview_process_removals': 'interviews',
        'pipeline_opportunities': 'interviews', 'pipeline_links': 'interviews',
        'pipeline_attendance': 'interviews', 'pipeline_tasks': 'interviews',
        'pipeline_contacts': 'interviews', 'pipeline_history': 'interviews',
        'pipeline_review_decisions': 'interviews', 'pipeline_sync_state': 'interviews',
        'pipeline_settings': 'interviews',
        'sourcing_books': 'sourcing', 'sourcing_tabs': 'sourcing',
        'native_books': 'sourcing', 'native_tabs': 'sourcing',
        'native_columns': 'sourcing', 'native_rows': 'sourcing', 'native_cells': 'sourcing',
        'sourcing_blocked_roles': 'sourcing', 'sourcing_blocked_companies': 'sourcing',
        'sourcing_check_activity': 'sourcing', 'sourcing_activity_runs': 'sourcing',
        'sourcing_activity_samples': 'sourcing',
        'bidders': 'accounts', 'bidder_assignments': 'accounts',
        'payment_deduction_rule': 'payments', 'bidder_payment_amounts': 'payments',
        'application_receipts': 'payments', 'bidder_payments': 'payments',
        'mail_replies': 'messages', 'mail_outgoing': 'messages',
        'agent_followup_state': 'messages', 'agent_drafts': 'messages',
    }
    for table, topic in tables.items():
        for operation in ('INSERT', 'UPDATE', 'DELETE'):
            conn.execute(f'DROP TRIGGER IF EXISTS realtime_{table}_{operation.lower()}')
            # An outer UPSERT's conflict policy can override OR REPLACE inside
            # its trigger, so explicitly remove the prior hint before insertion.
            conn.execute(f'''CREATE TRIGGER realtime_{table}_{operation.lower()}
                AFTER {operation} ON {table}
                WHEN (SELECT enabled FROM realtime_runtime WHERE id=1)=1 BEGIN
                DELETE FROM realtime_outbox WHERE topic='{topic}';
                INSERT OR REPLACE INTO realtime_outbox(topic) VALUES('{topic}'); END''')


def set_publishing(conn: sqlite3.Connection, enabled: bool) -> None:
    """Enable capture while the configured runtime owns outbox publication."""
    conn.execute('UPDATE realtime_runtime SET enabled=? WHERE id=1', (int(enabled),))
    conn.commit()


def set_account(conn: sqlite3.Connection, account_id: int, enabled: bool) -> None:
    if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone():
        raise ValueError('Account does not exist')
    conn.execute('''INSERT INTO realtime_accounts(account_id,enabled) VALUES(?,?)
        ON CONFLICT(account_id) DO UPDATE SET enabled=excluded.enabled''',
                 (account_id, int(enabled)))
    conn.commit()


def enabled_accounts(conn: sqlite3.Connection) -> list[int]:
    return [row[0] for row in conn.execute('''SELECT r.account_id FROM realtime_accounts r
        JOIN accounts a ON a.id=r.account_id WHERE r.enabled=1 AND a.enabled=1
        ORDER BY r.account_id''')]


def status(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in conn.execute('''SELECT a.id AS account_id,
        COALESCE(r.enabled,0) AS enabled,r.last_sync,COALESCE(r.last_error,'') AS last_error
        FROM accounts a LEFT JOIN realtime_accounts r ON r.account_id=a.id ORDER BY a.id''')]


def set_status(conn: sqlite3.Connection, account_id: int, *, error: str = '',
               last_sync: float | None = None) -> None:
    """Persist caller-sanitized operational status, never provider error bodies."""
    conn.execute('''INSERT INTO realtime_accounts(account_id,last_sync,last_error) VALUES(?,?,?)
        ON CONFLICT(account_id) DO UPDATE SET last_error=excluded.last_error,
        last_sync=COALESCE(excluded.last_sync,realtime_accounts.last_sync)''',
                 (account_id, last_sync, error[:240]))
    conn.commit()


def pending_outbox(conn: sqlite3.Connection, limit: int = 100) -> list[sqlite3.Row]:
    return list(conn.execute('SELECT id,topic FROM realtime_outbox ORDER BY id LIMIT ?', (limit,)))


def acknowledge_outbox(conn: sqlite3.Connection, ids: list[int]) -> None:
    # Do not commit: publication and the caller's transaction boundaries stay explicit.
    conn.executemany('DELETE FROM realtime_outbox WHERE id=?', ((i,) for i in ids))


def _expires_timestamp(value: float | str) -> float:
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    return float(value)


class Registry:
    """Central route lookup: callback data never selects a workspace or account."""
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            # Workers and the gateway can open an old registry concurrently.
            # Serialize the additive migration before checking its columns.
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('''CREATE TABLE IF NOT EXISTS realtime_subscriptions (
                subscription_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                account_id INTEGER NOT NULL,kind TEXT NOT NULL,
                client_state_hash TEXT NOT NULL,expires REAL NOT NULL,
                callback_url TEXT NOT NULL DEFAULT '',resource TEXT NOT NULL DEFAULT '')''')
            if 'callback_url' not in {r[1] for r in conn.execute('PRAGMA table_info(realtime_subscriptions)')}:
                conn.execute("ALTER TABLE realtime_subscriptions ADD COLUMN callback_url TEXT NOT NULL DEFAULT ''")
            if 'resource' not in {r[1] for r in conn.execute('PRAGMA table_info(realtime_subscriptions)')}:
                conn.execute("ALTER TABLE realtime_subscriptions ADD COLUMN resource TEXT NOT NULL DEFAULT ''")
            conn.execute('CREATE INDEX IF NOT EXISTS realtime_subscription_workspace ON realtime_subscriptions(workspace_id)')

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def save(self, subscription_id: str, workspace_id: str, account_id: int,
             kind: str, client_state: str, expires: float | str, *, callback_url: str = '', resource: str = '') -> None:
        if not client_state or not subscription_id or not workspace_id:
            raise ValueError('Subscription identity and client state are required')
        state_hash = hashlib.sha256(client_state.encode()).hexdigest()
        with self._connect() as conn:
            conn.execute('''INSERT INTO realtime_subscriptions
                (subscription_id,workspace_id,account_id,kind,client_state_hash,expires,callback_url,resource)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(subscription_id) DO UPDATE SET workspace_id=excluded.workspace_id,
                account_id=excluded.account_id,kind=excluded.kind,
                client_state_hash=excluded.client_state_hash,expires=excluded.expires,
                callback_url=excluded.callback_url,resource=excluded.resource''',
                (subscription_id, workspace_id, account_id, kind, state_hash,
                 _expires_timestamp(expires), callback_url, resource))

    def validate(self, subscription_id: str, client_state: str) -> dict | None:
        if not isinstance(client_state, str) or not isinstance(subscription_id, str):
            return None
        with self._connect() as conn:
            row = conn.execute('SELECT * FROM realtime_subscriptions WHERE subscription_id=?',
                               (subscription_id,)).fetchone()
        if row is None or row['expires'] <= time.time():
            return None
        if not hmac.compare_digest(row['client_state_hash'], hashlib.sha256(client_state.encode()).hexdigest()):
            return None
        return dict(row)

    def update_expiry(self, subscription_id: str, expires: float | str) -> None:
        with self._connect() as conn:
            conn.execute('UPDATE realtime_subscriptions SET expires=? WHERE subscription_id=?',
                         (_expires_timestamp(expires), subscription_id))

    def delete(self, subscription_id: str) -> None:
        with self._connect() as conn:
            conn.execute('DELETE FROM realtime_subscriptions WHERE subscription_id=?', (subscription_id,))

    def list_workspace(self, workspace_id: str) -> list[dict]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM realtime_subscriptions WHERE workspace_id=?',
                                                      (workspace_id,))]
