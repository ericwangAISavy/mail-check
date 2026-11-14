"""Realtime collection durability and independent classification contracts."""
from contextlib import contextmanager
from datetime import datetime, timezone
import threading

import pytest

from mailcheck import db
from mailcheck.config import Config
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.realtime import storage
from mailcheck.realtime.settings import Settings


class FakeLease:
    def __bool__(self): return True
    def ensure_owned(self): pass


class FakeBroker:
    def __init__(self): self.jobs = []; self.published = []; self.fail_publish = False
    @contextmanager
    def lease(self, account_id, **kwargs): yield FakeLease()
    def enqueue(self, kind, account_id, reason='notification'): self.jobs.append((kind, account_id, reason))
    def publish(self, topics, event_id):
        if self.fail_publish: raise RuntimeError('private Redis URL')
        self.published.append((topics, event_id))
    def close(self): pass


@pytest.fixture
def setup(tmp_path):
    from mailcheck.realtime.runtime import Runtime
    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        aid = db.add_account(conn, label='primary', email='person@example.com')
        storage.set_account(conn, aid, True)
        storage.set_publishing(conn, True)
    broker = FakeBroker()
    runtime = Runtime(Settings('redis://example', ''), 'workspace', storage.Registry(tmp_path / 'registry.db'),
                      db_path=path, broker=broker, config_loader=Config, job_lock=threading.Lock())
    return runtime, path, aid, broker


def message(aid):
    return NormalizedMessage(account_id=aid, account_label='primary', message_id='one', uid='1', folder='INBOX',
        from_addr='recruiter@example.com', from_name='Recruiter', subject='Interview',
        date_utc=datetime.now(timezone.utc), body='We would like to interview you.')


def test_collection_commits_placeholder_before_classification_and_preserves_done(setup, monkeypatch):
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
    monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: None)
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.reclassify', lambda *a, **k: pytest.fail('collection classified mail'))
    runtime.collect_mail(aid)
    with db.session(path) as conn:
        row = conn.execute('SELECT id FROM messages').fetchone()
        assert row
        assert conn.execute('SELECT category,retryable FROM classifications').fetchone()[:] == ('unclassified', 1)
        conn.execute("UPDATE messages SET handled_at='done' WHERE id=?", (row[0],))
    assert broker.jobs == [('classify', aid, 'reconcile')]
    runtime.collect_mail(aid)
    with db.session(path) as conn:
        assert conn.execute('SELECT COUNT(*),handled_at FROM messages').fetchone()[:] == (1, 'done')
        assert conn.execute('SELECT COUNT(*) FROM classifications').fetchone()[0] == 1
        assert conn.execute('SELECT checked_at FROM realtime_checkpoints WHERE account_id=?', (aid,)).fetchone()


def test_prefilter_persisted_without_model_and_disabled_account_never_fetches(setup, monkeypatch):
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
    monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: Classification('other', source='prefilter'))
    runtime.collect_mail(aid)
    assert not broker.jobs
    with db.session(path) as conn:
        assert conn.execute('SELECT source FROM classifications').fetchone()[0] == 'prefilter'
        storage.set_account(conn, aid, False)
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: pytest.fail('disabled provider call'))
    runtime.collect_mail(aid)
    runtime.collect_mail(9999)


def test_failed_enqueue_leaves_committed_mail_for_recovery(setup, monkeypatch):
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
    monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: None)
    monkeypatch.setattr(broker, 'enqueue', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('Redis offline')))
    with pytest.raises(RuntimeError): runtime.collect_mail(aid)
    with db.session(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1
        assert conn.execute('SELECT COUNT(*) FROM classifications WHERE retryable=1').fetchone()[0] == 1


def test_outbox_delete_only_after_successful_publication(setup):
    runtime, path, aid, broker = setup
    with db.session(path) as conn:
        db.upsert_message(conn, message(aid))
    broker.fail_publish = True
    with pytest.raises(RuntimeError): runtime.publish_outbox()
    with db.session(path) as conn:
        pending = storage.pending_outbox(conn)
        assert pending
    broker.fail_publish = False
    runtime.publish_outbox()
    assert broker.published[0][1] == max(r['id'] for r in pending)
    with db.session(path) as conn: assert not storage.pending_outbox(conn)


def test_busy_classification_does_not_block_collector(setup, monkeypatch):
    from mailcheck.realtime.runtime import WorkDeferred
    runtime, path, aid, broker = setup
    runtime.job_lock.acquire()
    try:
        with pytest.raises(WorkDeferred): runtime.classify_account(aid)
        monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
        monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: None)
        runtime.collect_mail(aid)
    finally: runtime.job_lock.release()
    with db.session(path) as conn: assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1


def test_calendar_errors_retry_instead_of_acknowledged(setup, monkeypatch):
    runtime, path, aid, broker = setup
    with db.session(path) as conn: conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?", (aid,))
    def collect(*a, **kwargs):
        assert kwargs['defer_analysis'] is True
        return {'errors': ['provider credentials details']}
    monkeypatch.setattr('mailcheck.realtime.runtime.interviews.collect_calendar_events', collect)
    with pytest.raises(RuntimeError, match='Calendar collection unavailable'):
        runtime.collect_calendar(aid)


def test_opt_out_during_fetch_prevents_persistence(setup, monkeypatch):
    from mailcheck.realtime.runtime import AccountDisabled
    runtime, path, aid, broker = setup
    def fetch(*args):
        with db.session(path) as conn: storage.set_account(conn, aid, False)
        return [message(aid)]
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', fetch)
    with pytest.raises(AccountDisabled): runtime.collect_mail(aid)
    with db.session(path) as conn:
        assert not conn.execute('SELECT 1 FROM messages').fetchone()
        assert not conn.execute('SELECT 1 FROM realtime_checkpoints').fetchone()
    assert not broker.jobs


def test_lost_lease_rolls_back_classification_commit(setup, monkeypatch):
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
    monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: None)
    runtime.collect_mail(aid)
    lost = False
    class Lease(FakeLease):
        def ensure_owned(self):
            if lost: raise RuntimeError('lost lease')
    @contextmanager
    def lease(*a, **k): yield Lease()
    monkeypatch.setattr(broker, 'lease', lease)
    def classify(conn, cfg, *, pks):
        nonlocal lost
        conn.execute("UPDATE classifications SET category='other',retryable=0")
        lost = True
        conn.commit()
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.reclassify', classify)
    with pytest.raises(RuntimeError, match='lost lease'): runtime.classify_account(aid)
    with db.session(path) as conn:
        assert conn.execute('SELECT category FROM classifications').fetchone()[0] == 'unclassified'


def test_failed_fetch_never_advances_checkpoint(setup, monkeypatch):
    runtime, path, aid, broker = setup
    def unavailable(*a): raise RuntimeError('credentials private provider body')
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', unavailable)
    with pytest.raises(RuntimeError): runtime.collect_mail(aid)
    with db.session(path) as conn:
        assert not conn.execute('SELECT 1 FROM realtime_checkpoints').fetchone()


def test_reconcile_enabled_only_and_recovers_pending_classification(setup, monkeypatch):
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
    monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: None)
    runtime.collect_mail(aid)
    with db.session(path) as conn:
        db.add_account(conn, label='not-opted-in', email='another@example.com')
    broker.jobs.clear()
    runtime.reconcile()
    assert broker.jobs == [('mail', aid, 'reconcile'), ('classify', aid, 'reconcile')]
    runtime.reconcile()
    assert len(broker.jobs) == 2


def test_account_routes_require_explicit_boolean_and_report_safe_status(setup, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mailcheck.realtime.routes import install
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.config.db_path', lambda: path)
    monkeypatch.setenv('OFFERPATH_REDIS_URL', 'redis://private:password@example')
    monkeypatch.setenv('OFFERPATH_PUBLIC_URL', 'https://public.example')
    app = FastAPI()
    app.state.realtime = runtime
    install(app)
    with TestClient(app) as client:
        state = client.get('/api/realtime/accounts').json()
        assert state['configured'] and state['public_ready']
        assert state['accounts'][0]['subscription_status'] == 'polling'
        assert 'password' not in str(state)
        runtime.queue_error = 'Live updates queue unavailable; retrying.'
        assert client.get('/api/realtime/accounts').json()['accounts'][0]['last_error'] == runtime.queue_error
        assert client.post(f'/api/realtime/accounts/{aid}', json={'enabled': 'false'}).status_code == 422
        assert client.post('/api/realtime/accounts/999', json={'enabled': False}).status_code == 404
        assert client.post(f'/api/realtime/accounts/{aid}', json={'enabled': False}).json()['enabled'] is False
        monkeypatch.delenv('OFFERPATH_REDIS_URL')
        assert client.post(f'/api/realtime/accounts/{aid}', json={'enabled': True}).status_code == 503
        assert client.post(f'/api/realtime/accounts/{aid}', json={'enabled': False}).status_code == 200


def test_disabled_environment_has_no_broker_and_disables_capture(setup, monkeypatch):
    from mailcheck.realtime.runtime import Runtime
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.config.db_path', lambda: path)
    monkeypatch.delenv('OFFERPATH_REDIS_URL', raising=False)
    monkeypatch.setattr('mailcheck.realtime.runtime.Broker', lambda *a: pytest.fail('disabled Redis initialized'))
    assert Runtime.from_env() is None
    with db.session(path) as conn:
        assert conn.execute('SELECT enabled FROM realtime_runtime').fetchone()[0] == 0


@pytest.mark.parametrize('fail_first', [False, True])
def test_notification_burst_coalesces_only_successful_scan_start_hints(setup, monkeypatch, fail_first):
    runtime, path, aid, broker = setup
    calls, acked, failed = [], [], []
    jobs = [(f'{i}-0', {'account_id': str(aid)}) for i in range(1, 5)]
    class Redis:
        def xrevrange(self, *a, **k): return [('3-0', {})] if len(calls) < 2 else [('4-0', {})]
    broker.redis = Redis()
    broker.stream_name = lambda kind: kind
    broker.claim = lambda *a, **k: [jobs.pop(0)] if jobs else []
    @contextmanager
    def processing(*a, **k): yield FakeLease()
    broker.processing = processing
    def ack(kind, message_id, *, consumer):
        assert consumer
        acked.append(message_id)
        if message_id == '4-0': runtime._stop.set()
    def fail(kind, message_id, fields, *, consumer): failed.append(message_id)
    broker.ack, broker.fail = ack, fail
    def collect(*a):
        calls.append(a)
        if fail_first and len(calls) == 1: raise RuntimeError('provider unavailable')
    monkeypatch.setattr(runtime, 'collect_mail', collect)
    runtime._consume('mail')
    assert len(calls) == (3 if fail_first else 2)
    assert acked == (['2-0', '3-0', '4-0'] if fail_first else ['1-0', '2-0', '3-0', '4-0'])
    assert failed == (['1-0'] if fail_first else [])


def test_real_redis_runtime_retries_classification_and_publishes_independent_replay(tmp_path, monkeypatch):
    import os
    import time
    import uuid
    from types import SimpleNamespace
    from mailcheck.realtime.queue import Broker
    from mailcheck.realtime.runtime import Runtime
    url = os.environ.get('OFFERPATH_TEST_REDIS_URL')
    if not url: pytest.skip('set OFFERPATH_TEST_REDIS_URL to exercise real Redis')
    broker = Broker(url, 'runtime-' + uuid.uuid4().hex, reclaim_idle_ms=1000, retry_base_ms=30)
    broker.redis.ping()
    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        aid = db.add_account(conn, label='primary', email='person@example.com')
        storage.set_account(conn, aid, True)
    runtime = Runtime(Settings(url, ''), broker.workspace_id, storage.Registry(tmp_path / 'registry.db'),
                      db_path=path, broker=broker, config_loader=Config)
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', lambda *a: [message(aid)])
    monkeypatch.setattr('mailcheck.realtime.runtime.prefilter.apply', lambda *a: None)
    attempts = []
    def classify(conn, cfg, *, pks):
        attempts.append(pks)
        if len(attempts) == 1:
            return SimpleNamespace(errors=['model busy'], retryable=1)
        for pk in pks:
            db.save_classification(conn, pk, Classification('other'), 'synthetic-test-model', 'test')
        return SimpleNamespace(errors=[], retryable=0)
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.reclassify', classify)
    try:
        runtime.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with db.session(path) as conn:
                rows = conn.execute("SELECT 1 FROM classifications WHERE category='other'").fetchall()
                pending = storage.pending_outbox(conn)
            changes = broker.read_changes('0-0')
            if rows and not pending and changes: break
            threading.Event().wait(.025)
        assert len(attempts) >= 2
        assert rows and not pending
        first = broker.read_changes('0-0')
        second = broker.read_changes('0-0')
        assert first == second and first
        assert runtime.queue_error == ''
        assert broker.redis.xlen(broker.deadletter_stream('classify')) == 0
        with db.session(path) as conn:
            assert conn.execute('SELECT last_sync FROM realtime_accounts WHERE account_id=?', (aid,)).fetchone()[0]
    finally:
        runtime.stop()
        # stop() closes redis-py; its pool reconnects only for isolated key cleanup.
        keys = list(broker.redis.scan_iter(broker.prefix + '*'))
        if keys: broker.redis.delete(*keys)
        broker.close()


def test_actual_calendar_savepoint_cannot_commit_after_lease_loss(setup, monkeypatch):
    from types import SimpleNamespace
    from mailcheck import interviews
    from mailcheck.calendar_events import CalendarBooking
    runtime, path, aid, broker = setup
    with db.session(path) as conn:
        conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?", (aid,))
        storage.acknowledge_outbox(conn, [r['id'] for r in storage.pending_outbox(conn)])
    booking = CalendarBooking('graph-event:lease-test', 'lease-test', 'Technical Interview',
                              datetime.now(timezone.utc), None)
    source = SimpleNamespace(fetch_calendar=lambda *a, **k: iter([booking]))
    monkeypatch.setattr('mailcheck.pipeline.build_source', lambda *a: source)
    lost = False
    class Lease(FakeLease):
        def ensure_owned(self):
            if lost: raise RuntimeError('lost calendar lease')
    @contextmanager
    def lease(*a, **k): yield Lease()
    monkeypatch.setattr(broker, 'lease', lease)
    original_save = interviews._save_calendar_booking
    def lose_after_save(*args, **kwargs):
        nonlocal lost
        result = original_save(*args, **kwargs)
        lost = True
        return result
    monkeypatch.setattr(interviews, '_save_calendar_booking', lose_after_save)
    with pytest.raises(RuntimeError, match='lost calendar lease'): runtime.collect_calendar(aid)
    assert lost
    with db.session(path) as conn:
        assert not conn.execute('SELECT 1 FROM interview_events').fetchone()
        assert not conn.execute('SELECT 1 FROM interview_sources').fetchone()
        assert not storage.pending_outbox(conn)


def test_permanent_unclassified_mail_waits_for_manual_retry(setup, monkeypatch):
    runtime, path, aid, broker = setup
    with db.session(path) as conn:
        pk = db.upsert_message(conn, message(aid))
        db.save_classification(conn, pk, Classification('unclassified', retryable=False), 'test-model', 'test')
    runtime.reconcile()
    assert broker.jobs == [('mail', aid, 'reconcile')]
    broker.jobs.clear()
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.reclassify', lambda *a, **k: pytest.fail('permanent failure auto-retried'))
    runtime.classify_account(aid)
    assert not broker.jobs


def test_failed_initial_fetch_keeps_durable_window_beyond_lookback(setup, monkeypatch):
    from datetime import timedelta
    runtime, path, aid, broker = setup
    clock = datetime(2026, 1, 1, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None): return clock
    monkeypatch.setattr('mailcheck.realtime.runtime.datetime', Clock)
    windows = []
    def fetch(account, since, cfg):
        windows.append(since)
        if len(windows) == 1: raise RuntimeError('provider unavailable')
        return []
    monkeypatch.setattr('mailcheck.realtime.runtime.pipeline.fetch_account', fetch)
    with pytest.raises(RuntimeError): runtime.collect_mail(aid)
    with db.session(path) as conn:
        assert conn.execute('SELECT since FROM realtime_pending_windows WHERE account_id=?', (aid,)).fetchone()[0] == windows[0].isoformat()
        assert not conn.execute('SELECT 1 FROM realtime_checkpoints').fetchone()
    clock += timedelta(days=730)
    runtime.collect_mail(aid)
    assert windows[0] == windows[1]
    with db.session(path) as conn:
        assert not conn.execute('SELECT 1 FROM realtime_pending_windows').fetchone()
        assert conn.execute('SELECT checked_at FROM realtime_checkpoints WHERE account_id=?', (aid,)).fetchone()[0] == clock.isoformat()


def test_subscription_status_requires_current_callback_url(setup, monkeypatch):
    import time
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mailcheck.realtime.routes import install
    runtime, path, aid, broker = setup
    monkeypatch.setattr('mailcheck.config.db_path', lambda: path)
    monkeypatch.setenv('OFFERPATH_REDIS_URL', 'redis://example')
    monkeypatch.setenv('OFFERPATH_PUBLIC_URL', 'https://new.example')
    with db.session(path) as conn:
        conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?", (aid,))
    for kind in ('mail', 'calendar'):
        runtime.registry.save(kind, runtime.workspace_id, aid, kind, 'state', time.time() + 86400,
                              callback_url='https://old.example/hooks/microsoft')
    app = FastAPI()
    app.state.realtime = runtime
    install(app)
    with TestClient(app) as client:
        assert client.get('/api/realtime/accounts').json()['accounts'][0]['subscription_status'] == 'pending'
        for kind in ('mail', 'calendar'):
            runtime.registry.save(kind, runtime.workspace_id, aid, kind, 'state', time.time() + 86400,
                                  callback_url='https://new.example/hooks/microsoft')
        assert client.get('/api/realtime/accounts').json()['accounts'][0]['subscription_status'] == 'pending'
        for kind in ('mail', 'calendar'):
            runtime.registry.save(kind, runtime.workspace_id, aid, kind, 'state', time.time() + 86400,
                                  callback_url='https://new.example/hooks/microsoft', resource=runtime.graph.resources[kind])
        assert client.get('/api/realtime/accounts').json()['accounts'][0]['subscription_status'] == 'subscribed'
        monkeypatch.delenv('OFFERPATH_PUBLIC_URL')
        assert client.get('/api/realtime/accounts').json()['accounts'][0]['subscription_status'] == 'polling'


def test_outbox_publish_does_not_acknowledge_concurrent_replacement(setup, monkeypatch):
    runtime, path, aid, broker = setup
    with db.session(path) as conn:
        conn.execute("UPDATE accounts SET label='before-publish' WHERE id=?", (aid,))
    def publish(topics, event_id):
        with db.session(path) as conn:
            conn.execute("UPDATE accounts SET label='during-publish' WHERE id=?", (aid,))
    monkeypatch.setattr(broker, 'publish', publish)
    runtime.publish_outbox()
    with db.session(path) as conn:
        rows = storage.pending_outbox(conn)
        assert len(rows) == 1 and rows[0]['topic'] == 'accounts'
