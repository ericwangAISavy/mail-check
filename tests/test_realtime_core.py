"""Durability and isolation contracts exercised against SQLite and real Redis."""
import hashlib
import os
import time
import uuid

import pytest

from mailcheck import db


@pytest.fixture
def database(tmp_path):
    conn = db.connect(tmp_path / 'mail.db')
    account_id = db.add_account(conn, label='primary', email='person@example.com')
    yield conn, account_id
    conn.close()


@pytest.fixture
def broker():
    from mailcheck.realtime.queue import Broker
    url = os.environ.get('OFFERPATH_TEST_REDIS_URL')
    if not url:
        pytest.skip('set OFFERPATH_TEST_REDIS_URL to exercise real Redis')
    broker = Broker(url, 'test-' + uuid.uuid4().hex, reclaim_idle_ms=30,
                    max_attempts=2, retry_base_ms=30)
    broker.redis.ping()
    yield broker
    keys = list(broker.redis.scan_iter(broker.prefix + '*'))
    if keys:
        broker.redis.delete(*keys)
    broker.close()


def test_opt_in_is_persisted_and_disabled_accounts_are_excluded(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    assert storage.enabled_accounts(conn) == []
    storage.set_account(conn, account_id, True)
    assert storage.enabled_accounts(conn) == [account_id]
    storage.set_status(conn, account_id, error='Redis unavailable', last_sync=123.0)
    record = storage.status(conn)[0]
    assert record['enabled'] and record['last_sync'] == 123.0
    assert record['last_error'] == 'Redis unavailable'
    conn.execute('UPDATE accounts SET enabled=0 WHERE id=?', (account_id,))
    assert storage.enabled_accounts(conn) == []
    with pytest.raises(ValueError):
        storage.set_account(conn, 99999, True)


def test_outbox_rolls_back_and_replays_until_acknowledged(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    storage.set_publishing(conn, True)
    conn.execute("INSERT INTO messages(account_id,message_id,body_text,fetched_at) VALUES(?,?,?,?)",
                 (account_id, 'message', 'private body', '2026-11-13'))
    assert storage.pending_outbox(conn)
    conn.rollback()
    assert storage.pending_outbox(conn) == []
    conn.execute("INSERT INTO messages(account_id,message_id,body_text,fetched_at) VALUES(?,?,?,?)",
                 (account_id, 'message', 'private body', '2026-11-13'))
    conn.commit()
    first = storage.pending_outbox(conn)
    assert first and dict(first[0]).keys() == {'id', 'topic'}
    assert first[0]['topic'] == 'messages'
    assert [dict(r) for r in storage.pending_outbox(conn)] == [dict(r) for r in first]
    storage.acknowledge_outbox(conn, [r['id'] for r in first])
    conn.commit()
    assert storage.pending_outbox(conn) == []


def test_manual_classification_calendar_and_done_updates_emit_topics(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    storage.set_publishing(conn, True)
    message_id = conn.execute("INSERT INTO messages(account_id,message_id,fetched_at) VALUES(?,?,?)",
                              (account_id, 'message', '2026-11-13')).lastrowid
    conn.execute("INSERT INTO classifications(message_pk,category,model,prompt_version,created_at) VALUES(?,?,?,?,?)",
                 (message_id, 'other', 'model', 'version', '2026-11-13'))
    event_id = conn.execute("INSERT INTO interview_events(created_at,updated_at) VALUES(?,?)",
                            ('2026-11-13', '2026-11-13')).lastrowid
    source_id = conn.execute("INSERT INTO interview_sources(event_id,account_id,external_message_id) VALUES(?,?,?)",
                             (event_id, account_id, 'calendar')).lastrowid
    conn.execute('INSERT INTO interview_source_details(source_id,description) VALUES(?,?)', (source_id, 'private'))
    conn.commit()
    assert {'messages', 'classifications', 'interviews'} <= {r['topic'] for r in storage.pending_outbox(conn)}
    storage.acknowledge_outbox(conn, [r['id'] for r in storage.pending_outbox(conn)])
    conn.execute("UPDATE messages SET handled_at='now' WHERE id=?", (message_id,))
    conn.execute("UPDATE interview_source_details SET description='changed' WHERE source_id=?", (source_id,))
    conn.commit()
    assert {'messages', 'interviews'} == {r['topic'] for r in storage.pending_outbox(conn)}


def test_registry_hashes_callback_secret_and_checks_expiry_and_workspace(tmp_path):
    from mailcheck.realtime.storage import Registry
    path = tmp_path / 'registry.db'
    registry = Registry(path)
    registry.save('subscription', 'workspace-A', 5, 'mail', 'secret', time.time()+60)
    restored = Registry(path)
    record = restored.validate('subscription', 'secret')
    assert record['workspace_id'] == 'workspace-A' and record['account_id'] == 5
    assert record['client_state_hash'] == hashlib.sha256(b'secret').hexdigest()
    assert restored.validate('subscription', 'wrong') is None
    assert restored.list_workspace('workspace-B') == []
    assert len(restored.list_workspace('workspace-A')) == 1
    assert b'secret' not in path.read_bytes()
    registry.save('expired', 'workspace-A', 5, 'mail', 'other', time.time()-1)
    assert registry.validate('expired', 'other') is None
    registry.delete('subscription')
    assert registry.validate('subscription', 'secret') is None


def test_settings_require_redis_and_a_public_https_root(monkeypatch):
    from mailcheck.realtime.settings import Settings
    monkeypatch.delenv('OFFERPATH_REDIS_URL', raising=False)
    monkeypatch.delenv('OFFERPATH_PUBLIC_URL', raising=False)
    assert not Settings.from_env().enabled
    monkeypatch.setenv('OFFERPATH_REDIS_URL', 'redis://localhost:6379/0')
    assert Settings.from_env().enabled
    monkeypatch.setenv('OFFERPATH_PUBLIC_URL', 'http://insecure.example')
    with pytest.raises(ValueError):
        Settings.from_env()
    monkeypatch.setenv('OFFERPATH_PUBLIC_URL', 'https://app.example/')
    assert Settings.from_env().public_url == 'https://app.example'


def test_streams_keep_workspaces_and_consumers_independent(broker):
    from mailcheck.realtime.queue import Broker
    other = Broker(broker.redis_url, 'other-' + uuid.uuid4().hex)
    job_id = broker.enqueue('mail', 7, reason='notification')
    assert other.claim('mail', 'other') == []
    assert broker.claim('classify', 'classifier') == []
    jobs = broker.claim('mail', 'collector')
    assert len(jobs) == 1 and jobs[0][0] == job_id
    fields = jobs[0][1]
    assert fields['account_id'] == '7' and fields['kind'] == 'mail'
    assert set(fields) <= {'account_id', 'kind', 'reason', 'attempt'}
    assert broker.claim('mail', 'second') == []
    broker.ack('mail', job_id)
    assert broker.redis.xpending(broker.stream_name('mail'), broker.group)['pending'] == 0
    other.close()


def test_abandoned_job_is_reclaimed_and_failed_job_retries_then_deadletters(broker):
    original_id = broker.enqueue('mail', 7)
    assert broker.claim('mail', 'crashed')[0][0] == original_id
    time.sleep(.05)
    reclaimed = broker.claim('mail', 'replacement')
    assert reclaimed[0][0] == original_id
    broker.fail('mail', *reclaimed[0])
    assert broker.claim('mail', 'replacement') == []
    time.sleep(.05)
    retry = broker.claim('mail', 'replacement')
    assert len(retry) == 1 and retry[0][1]['attempt'] == '2'
    broker.fail('mail', *retry[0])
    assert broker.claim('mail', 'replacement') == []
    dead = broker.redis.xrange(broker.deadletter_stream('mail'))
    assert len(dead) == 1 and dead[0][1]['account_id'] == '7'
    assert broker.redis.xpending(broker.stream_name('mail'), broker.group)['pending'] == 0
    # Repeating a failure after a lost response cannot schedule duplicate work.
    broker.fail('mail', *retry[0])
    assert broker.redis.xlen(broker.deadletter_stream('mail')) == 1


def test_change_events_replay_for_each_reader_and_outbox_publish_is_idempotent(broker):
    first = broker.publish(['messages', 'interviews'], 10)
    assert broker.publish(['messages', 'interviews'], 10) == first
    second = broker.publish(['classifications'], 11)
    reader_a = broker.read_changes('0-0')
    reader_b = broker.read_changes('0-0')
    assert reader_a == reader_b and [r[0] for r in reader_a] == [first, second]
    assert broker.read_changes(first) == [reader_a[1]]


def test_renewable_account_lease_prevents_overlap_and_releases(broker):
    with broker.lease(7, ttl_ms=90) as lease:
        assert lease
        time.sleep(.15)
        with broker.lease(7, ttl_ms=90) as competitor:
            assert not competitor
        with broker.lease(8, ttl_ms=90) as independent:
            assert independent
    with broker.lease(7, ttl_ms=90) as acquired:
        assert acquired


def test_retry_survives_worker_restart_and_keeps_only_safe_original_hints(broker):
    from mailcheck.realtime.queue import Broker
    broker.enqueue('classify', 3)
    message_id, fields = broker.claim('classify', 'first')[0]
    fields['body_text'] = 'never persist this'
    fields['account_id'] = '900'
    broker.fail('classify', message_id, fields)
    replacement = Broker(broker.redis_url, broker.workspace_id, retry_base_ms=30)
    try:
        time.sleep(.05)
        retry_id, retry_fields = replacement.claim('classify', 'replacement')[0]
        assert retry_fields['account_id'] == '3'
        assert 'body_text' not in retry_fields
        replacement.ack('classify', retry_id)
    finally:
        replacement.close()


def test_repeated_consumer_crashes_deadletter_instead_of_looping_forever(broker):
    message_id = broker.enqueue('mail', 3)
    assert broker.claim('mail', 'crashed1')[0][0] == message_id
    time.sleep(.05)
    assert broker.claim('mail', 'crashed2')[0][0] == message_id
    time.sleep(.05)
    assert broker.claim('mail', 'replacement') == []
    assert broker.redis.xlen(broker.deadletter_stream('mail')) == 1


def test_pending_jobs_survive_large_queue_and_acked_jobs_are_removed(broker):
    first = broker.enqueue('mail', 3)
    assert broker.claim('mail', 'consumer')[0][0] == first
    for _ in range(1100):
        broker.enqueue('mail', 3)
    assert broker.redis.xrange(broker.stream_name('mail'), first, first)
    broker.ack('mail', first)
    assert broker.redis.xrange(broker.stream_name('mail'), first, first) == []


def test_lease_loss_does_not_delete_successors_lease(broker):
    with broker.lease(3, ttl_ms=90) as first:
        assert first
        broker.redis.set(first.key, 'successor', px=5000)
        with pytest.raises(RuntimeError, match='lease lost'):
            first.ensure_owned()
    assert broker.redis.get(first.key) == 'successor'


def test_latest_change_cursor_does_not_replay_older_events(broker):
    assert broker.latest_change_id() == '0-0'
    broker.publish(['messages'], 1)
    cursor = broker.latest_change_id()
    assert broker.read_changes(cursor) == []
    second = broker.publish(['interviews'], 2)
    assert broker.read_changes(cursor)[0][0] == second


def test_renewals_can_update_expiration_without_persisting_raw_secrets(tmp_path):
    from mailcheck.realtime.storage import Registry
    registry = Registry(tmp_path / 'registry.db')
    registry.save('subscription', 'workspace', 1, 'mail', 'secret', time.time()+60)
    # A restarted worker only has the stored hash, not the raw callback secret.
    registry.update_expiry('subscription', '2027-01-01T00:00:00Z')
    assert registry.validate('subscription', 'secret')['expires'] == 1798761600.0


def test_calendar_collection_has_an_independent_stream(broker):
    job = broker.enqueue('calendar', 4)
    assert broker.claim('mail', 'mail-worker') == []
    assert broker.claim('calendar', 'calendar-worker')[0][0] == job


def test_disabled_realtime_does_not_accumulate_outbox_but_preserves_enabled_backlog(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    conn.execute("INSERT INTO messages(account_id,message_id,fetched_at) VALUES(?,?,?)", (account_id, 'disabled', '2026-11-13'))
    conn.commit()
    assert storage.pending_outbox(conn) == []
    storage.set_publishing(conn, True)
    conn.execute("UPDATE messages SET handled_at='done' WHERE account_id=?", (account_id,))
    conn.commit()
    backlog = [dict(row) for row in storage.pending_outbox(conn)]
    assert backlog
    storage.set_publishing(conn, False)
    conn.execute("UPDATE messages SET handled_at=NULL WHERE account_id=?", (account_id,))
    conn.commit()
    assert [dict(row) for row in storage.pending_outbox(conn)] == backlog


def test_classification_lease_does_not_block_collection(broker):
    with broker.lease(5, lane='classification') as classification:
        assert classification
        with broker.lease(5, lane='collection') as collection:
            assert collection
        with broker.lease(5, lane='classification') as competing_classifier:
            assert not competing_classifier
    with pytest.raises(ValueError):
        with broker.lease(5, lane='unsafe'):
            pass


def test_processing_heartbeat_keeps_active_job_from_being_reclaimed(broker):
    broker.reclaim_idle_ms = 120
    message_id = broker.enqueue('mail', 3)
    assert broker.claim('mail', 'active')[0][0] == message_id
    with broker.processing('mail', message_id, 'active') as processing:
        assert processing
        time.sleep(.35)
        processing.ensure_owned()
        assert broker.claim('mail', 'replacement') == []
        assert broker.ack('mail', message_id, consumer='active')


def test_reclaimed_job_cannot_be_acknowledged_or_failed_by_stale_consumer(broker):
    message_id = broker.enqueue('mail', 3)
    fields = broker.claim('mail', 'stale')[0][1]
    time.sleep(.05)
    assert broker.claim('mail', 'successor')[0][0] == message_id
    assert not broker.ack('mail', message_id, consumer='stale')
    assert not broker.fail('mail', message_id, fields, consumer='stale')
    assert broker.redis.xpending_range(broker.stream_name('mail'), broker.group, message_id, message_id, 1)[0]['consumer'] == 'successor'
    with broker.processing('mail', message_id, 'stale') as stale:
        assert not stale
        with pytest.raises(RuntimeError, match='ownership lost'):
            stale.ensure_owned()
    assert broker.ack('mail', message_id, consumer='successor')


def test_claim_does_not_leave_a_batch_idle_while_first_job_runs(broker):
    broker.enqueue('mail', 3)
    broker.enqueue('mail', 4)
    assert len(broker.claim('mail', 'first')) == 1
    assert len(broker.claim('mail', 'second')) == 1


def test_manual_account_and_realtime_status_changes_emit_accounts_topic(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    storage.set_publishing(conn, True)
    conn.execute('UPDATE accounts SET enabled=0 WHERE id=?', (account_id,))
    conn.commit()
    assert [r['topic'] for r in storage.pending_outbox(conn)] == ['accounts']
    storage.acknowledge_outbox(conn, [r['id'] for r in storage.pending_outbox(conn)])
    storage.set_status(conn, account_id, error='Provider unavailable')
    assert [r['topic'] for r in storage.pending_outbox(conn)] == ['accounts']


def test_reclaim_scan_advances_past_healthy_pending_jobs(broker):
    broker.reclaim_idle_ms = 1000
    ids = [broker.enqueue('mail', 3) for _ in range(15)]
    for _ in ids:
        broker.claim('mail', 'healthy')
    for message_id in ids[10:]:
        broker.redis.xclaim(broker.stream_name('mail'), broker.group, 'crashed', 0,
                            [message_id], idle=5000, justid=True)
    reclaimed = []
    for _ in range(3):
        reclaimed.extend(broker.claim('mail', 'replacement'))
    assert reclaimed and reclaimed[0][0] in ids[10:]


def test_outbox_coalesces_bursts_and_rollbacks_restore_previous_hint(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    storage.set_publishing(conn, True)
    for i in range(500):
        conn.execute('UPDATE accounts SET label=? WHERE id=?', (f'changed-{i}', account_id))
    conn.commit()
    first = [dict(row) for row in storage.pending_outbox(conn)]
    assert len(first) == 1
    conn.execute('UPDATE accounts SET label=? WHERE id=?', ('rolled-back', account_id))
    assert storage.pending_outbox(conn)[0]['id'] > first[0]['id']
    conn.rollback()
    assert [dict(row) for row in storage.pending_outbox(conn)] == first
    conn.execute('UPDATE accounts SET label=? WHERE id=?', ('later-change', account_id))
    conn.commit()
    storage.acknowledge_outbox(conn, [first[0]['id']])
    conn.commit()
    later = storage.pending_outbox(conn)
    assert len(later) == 1 and later[0]['id'] > first[0]['id']


def test_outbox_upgrade_preserves_latest_unpublished_hint(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    # Reproduce the pre-coalescing schema and trigger used by release 2.28.0.
    conn.execute('DROP TABLE realtime_outbox')
    conn.execute('CREATE TABLE realtime_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,topic TEXT NOT NULL)')
    conn.executemany('INSERT INTO realtime_outbox(topic) VALUES(?)', [('accounts',), ('messages',), ('accounts',)])
    conn.execute('DROP TRIGGER realtime_accounts_update')
    conn.execute("CREATE TRIGGER realtime_accounts_update AFTER UPDATE ON accounts BEGIN INSERT INTO realtime_outbox(topic) VALUES('accounts'); END")
    conn.commit()
    storage.initialize(conn)
    conn.commit()
    assert [(row['id'], row['topic']) for row in storage.pending_outbox(conn)] == [(2, 'messages'), (3, 'accounts')]
    storage.set_publishing(conn, True)
    conn.execute('UPDATE accounts SET label=? WHERE id=?', ('new', account_id))
    conn.commit()
    rows = storage.pending_outbox(conn)
    assert len(rows) == 2 and rows[-1]['topic'] == 'accounts' and rows[-1]['id'] > 3


@pytest.mark.parametrize(('sql', 'topic'), [
    ("INSERT INTO sourcing_blocked_companies VALUES('company','Company')", 'sourcing'),
    ("INSERT INTO sourcing_blocked_roles VALUES(1,'role','Role')", 'sourcing'),
    ("INSERT INTO bidders(name,created_at) VALUES('Bidder','now')", 'accounts'),
    ("INSERT INTO payment_deduction_rule VALUES(1,1,100)", 'payments'),
    ("INSERT INTO pipeline_settings VALUES('activated','true')", 'interviews'),
    ("INSERT INTO interview_manual_processes VALUES('company','Company','now')", 'interviews'),
    ("INSERT INTO agent_followup_state VALUES('followup','dismissed',NULL,'{}','now')", 'messages'),
])
def test_business_changes_emit_transactional_invalidation(database, sql, topic):
    from mailcheck.realtime import storage
    conn, _ = database
    storage.set_publishing(conn, True)
    conn.execute(sql)
    assert topic in {row['topic'] for row in storage.pending_outbox(conn)}
    conn.rollback()
    assert not storage.pending_outbox(conn)


def test_native_sourcing_cells_emit_one_hint_for_large_import(database):
    from mailcheck.realtime import storage
    conn, account_id = database
    bidder = conn.execute("INSERT INTO bidders(name,created_at) VALUES('Bidder','now')").lastrowid
    book = conn.execute("INSERT INTO native_books(bidder_id,title) VALUES(?,'Book')", (bidder,)).lastrowid
    tab = conn.execute("INSERT INTO native_tabs(book_id,account_id,account_label,title,updated_at) VALUES(?,?,'primary','Tab',1)", (book, account_id)).lastrowid
    conn.execute("INSERT INTO native_columns(id,tab_id,position,title) VALUES('column',?,0,'Column')", (tab,))
    conn.execute("INSERT INTO native_rows(id,tab_id,position) VALUES('row',?,0)", (tab,))
    conn.commit()
    storage.set_publishing(conn, True)
    for i in range(500):
        conn.execute("INSERT INTO native_cells(row_id,column_id,value) VALUES('row','column',?) ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value", (str(i),))
    conn.commit()
    rows = storage.pending_outbox(conn)
    assert len(rows) == 1 and rows[0]['topic'] == 'sourcing'


def test_schema_49_database_reopen_installs_coalescing_business_triggers(tmp_path):
    from mailcheck.realtime import storage
    path = tmp_path / 'previous-release.db'
    conn = db.connect(path)
    conn.execute('DROP TABLE realtime_outbox')
    conn.execute('CREATE TABLE realtime_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,topic TEXT NOT NULL)')
    conn.executemany('INSERT INTO realtime_outbox(topic) VALUES(?)', [('sourcing',), ('sourcing',)])
    conn.execute('DROP TRIGGER realtime_sourcing_blocked_companies_insert')
    conn.execute('PRAGMA user_version=49')
    conn.commit()
    conn.close()
    conn = db.connect(path)
    try:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        assert [(row['id'], row['topic']) for row in storage.pending_outbox(conn)] == [(2, 'sourcing')]
        storage.set_publishing(conn, True)
        conn.execute("INSERT INTO sourcing_blocked_companies VALUES('new','New')")
        conn.commit()
        rows = storage.pending_outbox(conn)
        assert len(rows) == 1 and rows[0]['topic'] == 'sourcing' and rows[0]['id'] > 2
    finally:
        conn.close()
