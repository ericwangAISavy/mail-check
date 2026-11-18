"""Shared-mode business integration; all state is temporary.

Real AMQP tests require an explicitly isolated OFFERPATH_TEST_AMQP_URL.
No provider, model, production process, or production database is used.
"""
import asyncio
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
import uuid

import httpx
import pytest

from mailcheck import config, db
from mailcheck.control_store import ControlStore
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.realtime import storage
from mailcheck.shared.api import create_dispatcher
from mailcheck.shared.control import ControlReader
from mailcheck.shared.runtime import Consumer, execute_job, publish_outbox
from mailcheck.web.auth import AuthStore
from mailcheck.workspaces import WorkspaceContext, bind_workspace, provision


def message(account, identifier, subject):
    return NormalizedMessage(account.id, account.label, identifier, identifier,
        'INBOX', 'recruiter@example.test', 'Recruiter', subject,
        datetime.now(timezone.utc), f'private body for {account.email}')


def schema(path):
    with sqlite3.connect(path) as conn:
        return (conn.execute('PRAGMA user_version').fetchone()[0],
                conn.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall())


@pytest.fixture
def installation(tmp_path, monkeypatch):
    # Ignore any workspace selection inherited from a developer's shell.
    for key in ('OFFERPATH_WORKSPACE_ID', 'OFFERPATH_WORKSPACE_ROOT', 'OFFERPATH_SHARED_CONFIG_PATH'):
        monkeypatch.delenv(key, raising=False)
    legacy = (tmp_path/'original'/'config.toml', tmp_path/'original'/'mailcheck.db',
              tmp_path/'original'/'web-auth.json')
    legacy[0].parent.mkdir()
    legacy[0].write_text('[watch]\nauto_check = false\n')
    legacy[2].write_text('untouched owner authentication sentinel')
    store = ControlStore(tmp_path/'control', AuthStore(lambda: legacy[2]))
    contexts, snapshots, existing = {}, {}, {}
    for index in (1, 2):
        wid = uuid.uuid4().hex
        root = provision(store.root/'workspaces', wid)
        with store.connect() as conn:
            conn.execute('INSERT INTO workspaces VALUES(?,?,?,1)', (wid, f'Admin {index}', str(root)))
            conn.execute('INSERT INTO users(username,workspace_id,owner,enabled,version,must_change) VALUES(?,?,0,1,?,0)',
                         (f'admin{index}', wid, uuid.uuid4().hex))
        context = WorkspaceContext.from_record(store.workspace(wid), legacy, store.root)
        # Explicitly provision the current schema before a shared context is bound.
        path = root/'data'/'mailcheck.db'
        conn = db.connect(path)
        account_id = db.add_account(conn, label='same-label', email=f'admin{index}@example.test')
        assert account_id == 1
        account = db.list_accounts(conn)[0]
        storage.set_account(conn, account_id, True)
        storage.set_publishing(conn, True)
        old = message(account, 'existing', 'Preserved manual decision')
        pk = db.upsert_message(conn, old)
        db.save_classification(conn, pk, Classification('interview', summary='human decision'), 'manual', 'manual')
        conn.execute('UPDATE messages SET handled_at=? WHERE id=?', ('2026-01-01T00:00:00+00:00', pk))
        conn.commit()
        existing[wid] = conn.execute('SELECT m.handled_at,c.category,c.summary,c.model FROM messages m JOIN classifications c ON c.message_pk=m.id WHERE m.id=?', (pk,)).fetchone()
        conn.close()
        assert schema(path)[0] == db.SCHEMA_VERSION
        contexts[wid] = context
        snapshots[wid] = schema(path)
    original_files = {path: path.read_bytes() for path in (legacy[0], legacy[2])}
    return SimpleNamespace(root=tmp_path, legacy=legacy, store=store,
        reader=ControlReader(store.root, legacy), contexts=contexts,
        schemas=snapshots, existing=existing, originals=original_files)


def test_actual_shared_app_reads_same_account_ids_in_two_admin_workspaces(installation):
    env = installation
    app = create_dispatcher(env.reader, 'test-worker', env.legacy)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            async def read(wid, index):
                response = await client.get('/api/accounts', headers={
                    'x-offerpath-worker': 'test-worker', 'x-offerpath-workspace': wid})
                assert response.status_code == 200, response.text
                accounts = response.json()['accounts']
                assert [(a['id'], a['label'], a['email']) for a in accounts] == [(1, 'same-label', f'admin{index}@example.test')]
            await asyncio.gather(*(read(wid, index) for index, wid in enumerate(env.contexts, 1)))
            missing = await client.get('/api/accounts', headers={'x-offerpath-worker':'test-worker'})
            assert missing.status_code == 403
    asyncio.run(check())
    for wid, context in env.contexts.items():
        assert schema(context.root/'data'/'mailcheck.db') == env.schemas[wid]
    assert all(path.read_bytes() == content for path, content in env.originals.items())
    assert not env.legacy[1].exists()


@pytest.fixture
def amqp_url(monkeypatch):
    url = os.environ.get('OFFERPATH_TEST_AMQP_URL')
    if not url:
        pytest.skip('set OFFERPATH_TEST_AMQP_URL to an isolated RabbitMQ broker')
    monkeypatch.setenv('AMQP_URL', url)
    return url


def fake_provider(monkeypatch):
    from mailcheck.shared import runtime
    def fetch(account, since, cfg):
        return [message(account, 'existing', 'Preserved manual decision'),
                message(account, 'pending', 'Needs model'),
                message(account, 'rule', 'Rule decision')]
    monkeypatch.setattr(runtime.pipeline, 'fetch_account', fetch)
    monkeypatch.setattr(runtime.prefilter, 'apply', lambda msg, rules:
        Classification('rejection', summary='rule result', source='prefilter') if msg.message_id == 'rule' else None)


def assert_business_state(env):
    for wid, context in env.contexts.items():
        path = context.root/'data'/'mailcheck.db'
        with sqlite3.connect(path) as conn:
            rows = conn.execute('SELECT message_id,body_text FROM messages ORDER BY message_id').fetchall()
            email = conn.execute('SELECT email FROM accounts WHERE id=1').fetchone()[0]
            assert [row[0] for row in rows] == ['existing', 'pending', 'rule']
            assert all(email in body for _, body in rows)
            pending = conn.execute("SELECT c.model,c.category,c.retryable FROM classifications c JOIN messages m ON m.id=c.message_pk WHERE m.message_id='pending'").fetchall()
            assert pending == [('realtime-pending', 'unclassified', 1)]
            assert conn.execute("SELECT COUNT(*) FROM classifications c JOIN messages m ON m.id=c.message_pk WHERE m.message_id='rule'").fetchone()[0] == 1
            old = conn.execute("SELECT m.handled_at,c.category,c.summary,c.model FROM messages m JOIN classifications c ON c.message_pk=m.id WHERE m.message_id='existing'").fetchone()
            assert old == tuple(env.existing[wid])
        assert schema(path) == env.schemas[wid]
    assert all(path.read_bytes() == content for path, content in env.originals.items())
    assert not env.legacy[1].exists()


def test_real_consumer_collects_two_admins_idempotently_without_schema_changes(installation, amqp_url, monkeypatch):
    from mailcheck.shared.broker import RabbitBroker
    env = installation
    fake_provider(monkeypatch)
    broker = RabbitBroker(amqp_url)
    consumer = Consumer(env.reader, env.legacy, amqp_url, 'collection')
    thread = threading.Thread(target=consumer.run, daemon=True)
    identifiers = {}
    try:
        for wid in env.contexts:
            identifiers[wid] = broker.enqueue('mail', 1, workspace_id=wid)
        thread.start()
        deadline = time.monotonic()+15
        while time.monotonic() < deadline:
            ready = all((env.store.root/'shared-runtime'/wid/'pending'/'classify-1.json').exists() for wid in env.contexts)
            if ready and not consumer.inflight:
                break
            time.sleep(.05)
        else:
            pytest.fail('collection did not finish for both temporary workspaces')
        consumer.stop.set()
        thread.join(5)
        assert not thread.is_alive()
        assert_business_state(env)
        # Simulate delivery after the DB commit but before AMQP acknowledgement.
        for wid in env.contexts:
            execute_job(env.reader, env.legacy, {'workspace_id':wid, 'kind':'mail', 'account_id':1})
        assert_business_state(env)
    finally:
        consumer.stop.set()
        if thread.ident:
            thread.join(5)
        # Only this test's model jobs are acknowledged; no model consumer runs.
        for _ in env.contexts:
            delivery = broker.claim('classify')
            if delivery:
                tag, fields = delivery
                if fields['workspace_id'] in env.contexts:
                    broker.ack(tag)
                else:
                    broker._channel.basic_nack(delivery_tag=tag, requeue=True)
                    break
        broker.close()


def test_confirmed_outbox_reaches_gateway_subscriber_as_bodyless_hint(installation, amqp_url):
    from mailcheck.shared.broker import RabbitBroker
    from mailcheck.shared.events import GatewaySubscriber, event_frames
    env = installation
    async def check():
        subscriber = GatewaySubscriber(amqp_url)
        queues = {wid: subscriber.subscribe(wid) for wid in env.contexts}
        subscriber.start()
        try:
            # Initial resync is posted only after the exclusive queue is bound.
            for queue in queues.values():
                assert await asyncio.wait_for(queue.get(), 10) == 'resync'
            def publish(wid):
                broker = RabbitBroker(amqp_url)
                try:
                    with bind_workspace(env.contexts[wid]), db.session() as conn:
                        assert storage.pending_outbox(conn)
                        publish_outbox(conn, broker, wid)
                        assert not storage.pending_outbox(conn)
                finally:
                    broker.close()
            first, second = env.contexts
            await asyncio.to_thread(publish, first)
            async def authorized():
                return True
            frames = event_frames(queues[first], authorized)
            assert 'event: resync' in await anext(frames)
            frame = await asyncio.wait_for(anext(frames), 10)
            assert frame == 'event: changed\ndata: {}\n\n'
            assert queues[second].empty()
            assert 'private body' not in frame and 'example.test' not in frame
            await frames.aclose()
            await asyncio.to_thread(publish, second)
            assert await asyncio.wait_for(queues[second].get(), 10) == 'changed'
        finally:
            for wid, queue in queues.items():
                subscriber.unsubscribe(wid, queue)
            await subscriber.stop()
            assert not subscriber._thread.is_alive()
    asyncio.run(check())


def test_outdated_business_database_is_refused_without_migration(installation):
    env = installation
    context = next(iter(env.contexts.values()))
    path = context.root/'data'/'mailcheck.db'
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA user_version=49')
    original_bytes = path.read_bytes()
    original_schema = schema(path)
    with bind_workspace(context), pytest.raises(RuntimeError, match='no automatic migration'):
        db.connect()
    assert path.read_bytes() == original_bytes
    assert schema(path) == original_schema
    assert all(path.read_bytes() == content for path, content in env.originals.items())


def test_real_channel_close_after_commit_redelivers_without_duplicate_business_rows(installation, amqp_url, monkeypatch):
    from mailcheck.shared.broker import RabbitBroker
    env = installation
    fake_provider(monkeypatch)
    producer = RabbitBroker(amqp_url)
    consumer = None

    def claim_own(broker, kind, expected_id=None):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            delivery = broker.claim(kind)
            if delivery:
                tag, fields = delivery
                matches = fields['id'] == expected_id if expected_id else fields['workspace_id'] in env.contexts
                if matches:
                    return tag, fields
                # A parallel isolated-broker test may own this job. Release it
                # immediately; never acknowledge someone else's envelope.
                broker._channel.basic_nack(delivery_tag=tag, requeue=True)
            broker.process_events(.05)
        pytest.fail(f'own {kind} delivery was not available')

    try:
        for wid in env.contexts:
            identifier = producer.enqueue('mail', 1, workspace_id=wid)
            consumer = RabbitBroker(amqp_url)
            tag, fields = claim_own(consumer, 'mail', identifier)
            execute_job(env.reader, env.legacy, fields)
            # The real database commit succeeded. Closing the transport without
            # ACK models the same broker-visible failure as losing a worker.
            consumer.close()
            consumer = RabbitBroker(amqp_url)
            repeated_tag, repeated = claim_own(consumer, 'mail', identifier)
            assert repeated == fields
            execute_job(env.reader, env.legacy, repeated)
            consumer.ack(repeated_tag)
            consumer.close()
            consumer = None
        assert_business_state(env)
    finally:
        if consumer is not None:
            consumer.close()
        # Each collect schedules one coalesced classify job. No model runs.
        for _ in env.contexts:
            tag, fields = claim_own(producer, 'classify')
            producer.ack(tag)
        producer.close()


def test_one_bad_checkpoint_recovers_without_changing_other_workspace_state(installation,monkeypatch):
    import json
    from datetime import timedelta
    from mailcheck import mail_checkpoints
    from mailcheck.shared.runtime import WorkspaceOperations, AccountBroker
    from mailcheck.shared.state import runtime_root
    env=installation
    fake_provider(monkeypatch)
    monkeypatch.setattr(AccountBroker,'enqueue',lambda *args,**kwargs:'test-classification-hint')
    first,second=env.contexts
    first_path=runtime_root(env.contexts[first])/'mail-1.json'
    first_path.parent.mkdir(parents=True,exist_ok=True)
    first_path.write_text('{')
    second_path=runtime_root(env.contexts[second])/'mail-1.json'
    second_path.parent.mkdir(parents=True,exist_ok=True)
    with bind_workspace(env.contexts[second]), db.session() as conn:
        account=db.list_accounts(conn)[0]
    old=datetime.now(timezone.utc)-timedelta(days=20)
    second_path.write_text(json.dumps(dict(mailbox=mail_checkpoints.mailbox_key(account),pending=old.isoformat())))
    original=second_path.read_bytes()
    with bind_workspace(env.contexts[first]):
        WorkspaceOperations(env.contexts[first],'amqp://unused').collect_mail(1)
    assert second_path.read_bytes()==original
    with bind_workspace(env.contexts[second]):
        WorkspaceOperations(env.contexts[second],'amqp://unused').collect_mail(1)
    assert_business_state(env)
