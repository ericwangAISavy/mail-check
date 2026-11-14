"""Opt-in workspace collectors, independent classification, and durable publication."""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from .. import config, db, interviews, mail_checkpoints, pipeline, prefilter
from ..llm import PROMPT_VERSION
from ..models import Classification
from ..sources.base import collection_scope
from . import storage
from .graph import GraphSubscriptions
from .queue import Broker
from .settings import Settings


class WorkDeferred(RuntimeError):
    pass


class AccountDisabled(RuntimeError):
    pass


class GuardedConnection:
    """Fence collector/model commits after lease loss, shutdown, or opt-out."""
    def __init__(self, conn, check):
        self.conn, self.check = conn, check

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, sql, parameters=()):
        # Releasing SQLite's outermost savepoint commits immediately, before
        # the collector's following commit() call can perform its fence.
        command = sql.lstrip().split(None, 1)[0].upper().rstrip(';') if sql.strip() else ''
        if command in {'RELEASE', 'COMMIT', 'END'}:
            self.check()
        return self.conn.execute(sql, parameters)

    def commit(self):
        try:
            self.check()
            self.conn.commit()
        except BaseException:
            self.conn.rollback()
            raise


class Runtime:
    def __init__(self, settings: Settings, workspace_id: str, registry: storage.Registry, *,
                 db_path=None, broker=None, config_loader=None, job_lock=None):
        self.settings, self.workspace_id, self.registry = settings, workspace_id, registry
        self.db_path = db_path
        self.broker = broker if broker is not None else Broker(settings.redis_url, workspace_id)
        self.config_loader = config_loader or config.load
        self.job_lock = job_lock if job_lock is not None else threading.Lock()
        self.graph = GraphSubscriptions(registry, workspace_id, settings.public_url)
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._threads = []
        self._due = {}
        self._horizons = {}
        self.subscription_error = ''
        self.queue_error = ''
        with db.session(self.db_path) as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS realtime_checkpoints (
                account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                mailbox TEXT NOT NULL, checked_at TEXT NOT NULL)''')
            conn.execute('''CREATE TABLE IF NOT EXISTS realtime_pending_windows (
                account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
                mailbox TEXT NOT NULL, since TEXT NOT NULL)''')

    @classmethod
    def from_env(cls, *, job_lock=None):
        settings = Settings.from_env()
        if not settings.enabled:
            # Disabled realtime must not initialize an otherwise unused data
            # directory (including the configuration recovery screen).
            path = config.db_path()
            if path.exists():
                with db.session(path) as conn:
                    storage.set_publishing(conn, False)
            return None
        workspace = os.environ.get('OFFERPATH_WORKER_ID') or os.environ.get('OFFERPATH_WORKSPACE_ID') or 'legacy'
        registry_path = os.environ.get('OFFERPATH_REALTIME_REGISTRY') or str(config.control_dir() / 'realtime.db')
        return cls(settings, workspace, storage.Registry(registry_path), job_lock=job_lock)

    def start(self):
        # Capture database changes even when Redis is down. Publishing retries.
        with db.session(self.db_path) as conn:
            storage.set_publishing(conn, True)
        for name, target in [('mail', lambda: self._consume('mail')), ('calendar', lambda: self._consume('calendar')),
                             ('classify', lambda: self._consume('classify')), ('maintenance', self._maintenance),
                             ('subscriptions', self._subscriptions)]:
            thread = threading.Thread(target=target, name='realtime-' + name, daemon=True)
            self._threads.append(thread)
            thread.start()

    def stop(self):
        self._stop.set()
        self._wake.set()
        deadline = time.monotonic() + 5
        for thread in self._threads:
            thread.join(timeout=max(0, deadline-time.monotonic()))
        if not any(t.is_alive() for t in self._threads):
            self.broker.close()

    def wake(self):
        self._wake.set()

    def _account(self, conn, account_id):
        if account_id not in storage.enabled_accounts(conn):
            return None
        return next((a for a in db.list_accounts(conn, only_enabled=True) if a.id == account_id), None)

    def _guard(self, conn, account_id, lease, processing=None):
        def check():
            if self._stop.is_set():
                raise AccountDisabled('Real-time runtime stopped')
            lease.ensure_owned()
            if processing is not None:
                processing.ensure_owned()
            if self._account(conn, account_id) is None:
                raise AccountDisabled('Real-time account disabled')
        return check

    def collect_mail(self, account_id, processing=None):
        with self.broker.lease(account_id, lane='collection') as lease:
            if not lease:
                raise WorkDeferred('Collection is busy')
            with db.session(self.db_path) as conn:
                account = self._account(conn, account_id)
                if account is None:
                    return
                cfg = self.config_loader()
                check = self._guard(conn, account_id, lease, processing)
                check()
                started = datetime.now(timezone.utc)
                row = conn.execute('SELECT mailbox,checked_at FROM realtime_checkpoints WHERE account_id=?', (account_id,)).fetchone()
                mailbox = mail_checkpoints.mailbox_key(account)
                since = started - timedelta(days=max(1, cfg.check.lookback_days))
                if row and row['mailbox'] == mailbox:
                    since = min(started, datetime.fromisoformat(row['checked_at'])) - timedelta(minutes=3)
                pending_window = conn.execute('SELECT mailbox,since FROM realtime_pending_windows WHERE account_id=?',
                                              (account_id,)).fetchone()
                if pending_window and pending_window['mailbox'] == mailbox:
                    since = datetime.fromisoformat(pending_window['since'])
                guarded = GuardedConnection(conn, check)
                conn.execute('''INSERT INTO realtime_pending_windows VALUES(?,?,?) ON CONFLICT(account_id)
                    DO UPDATE SET mailbox=excluded.mailbox,since=excluded.since''',
                    (account_id, mailbox, since.isoformat()))
                # Anchor catch-up before the first provider attempt so a long
                # outage cannot slide the initial lookback window forward.
                guarded.commit()
                with collection_scope(lambda _: check()):
                    messages = pipeline.fetch_account(account, since, cfg)
                check()
                for msg in messages:
                    pk = db.upsert_message(guarded, msg)
                    # Preserve every existing successful/manual classification.
                    if db.get_cached(guarded, pk, None) is not None:
                        continue
                    rule = prefilter.apply(msg, cfg.prefilter_rules)
                    if rule:
                        db.save_classification(guarded, pk, rule, pipeline.RULE_MODEL, PROMPT_VERSION, commit=False)
                    elif not conn.execute('SELECT 1 FROM classifications WHERE message_pk=?', (pk,)).fetchone():
                        db.save_classification(guarded, pk, Classification('unclassified', retryable=True,
                            summary='Waiting for classification.'), 'realtime-pending', PROMPT_VERSION, commit=False)
                conn.execute('''INSERT INTO realtime_checkpoints VALUES(?,?,?) ON CONFLICT(account_id)
                    DO UPDATE SET mailbox=excluded.mailbox,checked_at=excluded.checked_at''',
                    (account_id, mailbox, started.isoformat()))
                conn.execute('DELETE FROM realtime_pending_windows WHERE account_id=? AND mailbox=?',
                             (account_id, mailbox))
                guarded.commit()
                storage.set_status(conn, account_id, last_sync=time.time())
                pending = self._pending(conn, account)
            if pending:
                self.broker.enqueue('classify', account_id, reason='reconcile')

    def _pending(self, conn, account):
        return [row[0] for row in conn.execute('SELECT m.id FROM messages m '
            + db.LATEST_CLASSIFICATION
            + " WHERE m.account_id=? AND c.category='unclassified' AND c.retryable=1 ORDER BY m.id LIMIT 200", (account.id,))]

    def collect_calendar(self, account_id, processing=None):
        with self.broker.lease(account_id, lane='collection') as lease:
            if not lease:
                raise WorkDeferred('Collection is busy')
            with db.session(self.db_path) as conn:
                account = self._account(conn, account_id)
                if account is None or account.provider != 'outlook':
                    return
                check = self._guard(conn, account_id, lease, processing)
                check()
                with collection_scope(lambda _: check()):
                    result = interviews.collect_calendar_events(GuardedConnection(conn, check), self.config_loader(),
                                                               account_label=account.label, defer_analysis=True)
                if result.get('errors'):
                    raise RuntimeError('Calendar collection unavailable; retrying.')
                check()
                storage.set_status(conn, account_id, last_sync=time.time())

    def classify_account(self, account_id, processing=None):
        if not self.job_lock.acquire(blocking=False):
            raise WorkDeferred('Classification is busy')
        try:
            with self.broker.lease(account_id, lane='classification') as lease:
                if not lease:
                    raise WorkDeferred('Classification is busy')
                with db.session(self.db_path) as conn:
                    account = self._account(conn, account_id)
                    if account is None:
                        return
                    check = self._guard(conn, account_id, lease, processing)
                    check()
                    pks = self._pending(conn, account)
                    if not pks:
                        return
                    result = pipeline.reclassify(GuardedConnection(conn, check), self.config_loader(), pks=pks)
                    check()
                    if result.errors or result.retryable:
                        raise RuntimeError('Classification unavailable; retrying.')
                    if self._pending(conn, account):
                        self.broker.enqueue('classify', account_id, reason='reconcile')
        finally:
            self.job_lock.release()

    def publish_outbox(self):
        with db.session(self.db_path) as conn:
            rows = storage.pending_outbox(conn)
            if not rows:
                return
            self.broker.publish(sorted({r['topic'] for r in rows}), max(r['id'] for r in rows))
            storage.acknowledge_outbox(conn, [r['id'] for r in rows])
            conn.commit()

    def _consume(self, kind):
        consumer = uuid.uuid4().hex
        operation = {'mail': self.collect_mail, 'calendar': self.collect_calendar, 'classify': self.classify_account}[kind]
        while not self._stop.is_set():
            try:
                jobs = self.broker.claim(kind, consumer, block_ms=1000)
                self.queue_error = ''
                for message_id, fields in jobs:
                    account_id = int(fields['account_id'])
                    try:
                        with self.broker.processing(kind, message_id, consumer) as processing:
                            if not processing:
                                continue
                            key = (account_id, kind)
                            position = tuple(map(int, message_id.split('-')))
                            if kind != 'classify' and position <= self._horizons.get(key, (-1, -1)):
                                processing.ensure_owned()
                                self.broker.ack(kind, message_id, consumer=consumer)
                                continue
                            horizon = None
                            if kind != 'classify':
                                latest = self.broker.redis.xrevrange(self.broker.stream_name(kind), count=1)
                                if latest:
                                    horizon = tuple(map(int, latest[0][0].split('-')))
                            operation(account_id, processing)
                            processing.ensure_owned()
                            if horizon is not None:
                                # A successful full-account scan covers only hints
                                # already durable when that scan began.
                                self._horizons[key] = horizon
                            self.broker.ack(kind, message_id, consumer=consumer)
                    except AccountDisabled:
                        self.broker.ack(kind, message_id, consumer=consumer)
                    except Exception as exc:
                        if not isinstance(exc, WorkDeferred):
                            with db.session(self.db_path) as conn:
                                if self._account(conn, account_id):
                                    storage.set_status(conn, account_id, error={
                                        'mail': 'Mail collection unavailable; retrying.',
                                        'calendar': 'Calendar collection unavailable; retrying.',
                                        'classify': 'Classification unavailable; retrying.'}[kind])
                        self.broker.fail(kind, message_id, fields, consumer=consumer)
            except Exception:
                self.queue_error = 'Live updates queue unavailable; retrying.'
                self._stop.wait(2)

    def reconcile(self):
        now = time.monotonic()
        with db.session(self.db_path) as conn:
            enabled = set(storage.enabled_accounts(conn))
            accounts = [a for a in db.list_accounts(conn, only_enabled=True) if a.id in enabled]
            for account in accounts:
                kinds = ['mail'] + (['calendar'] if account.provider == 'outlook' else [])
                if self._pending(conn, account):
                    kinds.append('classify')
                for kind in kinds:
                    key = (account.id, kind)
                    if now >= self._due.get(key, 0):
                        self.broker.enqueue(kind, account.id, reason='reconcile')
                        self._due[key] = now + (30 if account.provider != 'outlook' and kind == 'mail' else 120)
            self._due = {k: v for k, v in self._due.items() if k[0] in enabled}

    def _maintenance(self):
        while not self._stop.is_set():
            try:
                self.publish_outbox()
            except Exception:
                self.queue_error = 'Live updates queue unavailable; retrying.'
            try:
                self.reconcile()
            except Exception:
                self.queue_error = 'Live updates queue unavailable; retrying.'
            self._stop.wait(1)

    def _subscriptions(self):
        while not self._stop.is_set():
            try:
                with db.session(self.db_path) as conn:
                    accounts = db.list_accounts(conn)
                    enabled = set(storage.enabled_accounts(conn))
                # A reserved non-account lease serializes subscription ownership
                # if two workspace processes briefly overlap during a restart.
                with self.broker.lease(0, lane='collection') as lease:
                    if not lease:
                        raise WorkDeferred('Subscription maintenance is busy')
                    self.graph.sync(accounts, enabled, self.config_loader())
                    lease.ensure_owned()
                self.subscription_error = ''
            except Exception:
                self.subscription_error = 'Microsoft subscription unavailable; polling continues.'
            self._wake.wait(60)
            self._wake.clear()
