from fastapi.testclient import TestClient
from tests.test_workspace_gateway import system, login


def test_monitoring_requires_owner_and_covers_all_workspaces(system, monkeypatch):
    app, store, pool = system
    monkeypatch.delenv('OFFERPATH_REDIS_URL', raising=False)
    store.create_admin(store.owner_token, 'alice', 'Alice workspace', 'temporary-pass-123')
    with TestClient(app) as client:
        assert client.get('/api/admin/system-monitoring').status_code == 401
        login(client)
        response = client.get('/api/admin/system-monitoring')
        assert response.status_code == 200
        data = response.json()
        assert {w['name'] for w in data['workspaces']} == {'Original workspace', 'Alice workspace'}
        assert next(c for c in data['components'] if c['id'] == 'redis')['status'] == 'disabled'
        assert data['checked_at'] > 0
        assert data['events'] == []
        login(client, 'alice', 'temporary-pass-123')
        client.post('/api/auth/password', json={'password': 'alice-final-pass-123'})
        assert client.get('/api/admin/system-monitoring').status_code == 403
        assert client.get('/system-monitoring').status_code == 403


def test_monitoring_invalid_configuration_never_leaks_credentials(system, monkeypatch):
    app, store, pool = system
    monkeypatch.setenv('OFFERPATH_REDIS_URL', 'https://private:secret@internal.invalid')
    with TestClient(app) as client:
        login(client)
        response = client.get('/api/admin/system-monitoring')
        assert response.status_code == 200
        assert 'secret' not in response.text and 'internal.invalid' not in response.text
        assert next(c for c in response.json()['components'] if c['id'] == 'redis')['status'] == 'unavailable'


def test_database_monitor_is_read_only_and_redacts_errors(tmp_path):
    import sqlite3
    from mailcheck.web.system_monitoring import database_snapshot
    missing = tmp_path/'missing.db'
    assert database_snapshot(missing)['status'] == 'unknown'
    assert not missing.exists()
    path = tmp_path/'workspace.db'
    with sqlite3.connect(path) as conn:
        conn.executescript("CREATE TABLE accounts(id INTEGER); CREATE TABLE realtime_accounts(account_id INTEGER, enabled INTEGER,last_sync REAL,last_error TEXT); CREATE TABLE realtime_outbox(id INTEGER);")
        conn.execute('INSERT INTO realtime_accounts VALUES (1,1,100,?)', ('token=secret mail body',))
        conn.execute('INSERT INTO realtime_outbox VALUES (1)')
    before = path.read_bytes()
    data = database_snapshot(path)
    assert data['outbox'] == 1
    assert data['accounts'][0]['status'] == 'degraded'
    assert 'secret' not in str(data)
    assert path.read_bytes() == before


def test_broker_records_only_safe_operational_fields(monkeypatch):
    from mailcheck.realtime.queue import Broker
    recorded=[]
    monkeypatch.setattr('mailcheck.realtime.telemetry.record',lambda *args:recorded.append(args))
    class Redis:
        def xadd(self, name, fields, **kwargs):return '1000-0'
    broker = Broker('redis://unused', 'legacy')
    broker._redis = Redis()
    broker.enqueue('mail', 1, reason='manual')
    assert recorded == [('redis://unused',broker.prefix,'mail','queued','1000-0')]


def test_telemetry_failure_does_not_fail_successful_enqueue(monkeypatch):
    def fail(*args): raise RuntimeError("telemetry unavailable")
    monkeypatch.setattr("mailcheck.realtime.telemetry.record",fail)
    from mailcheck.realtime.queue import Broker
    class Redis:
        def xadd(self, name, fields, **kwargs):
            if name.endswith('monitor'): raise RuntimeError('private failure')
            return '1000-0'
    broker = Broker('redis://unused', 'legacy')
    broker._redis = Redis()
    assert broker.enqueue('calendar', 1) == '1000-0'


def test_monitor_reports_per_stage_health_without_claiming_provider_reachability(system, monkeypatch):
    from mailcheck.web.system_monitoring import Monitor
    app, store, pool = system
    monkeypatch.setenv('OFFERPATH_REDIS_URL','redis://unused')
    monkeypatch.setattr('mailcheck.web.system_monitoring.read_redis',lambda *args:{'legacy':{'queues':[{'kind':'mail','pending':2,'retry':1,'dead':0}], 'events':[]}})
    monkeypatch.setattr(pool,'status',lambda:{'legacy':'running'})
    data = Monitor(store,pool).snapshot()
    assert {c['name'] for c in data['components']} >= {'Mail collection','Calendar collection','Classification','Shared model scheduler'}
    assert next(c for c in data['components'] if c['id']=='legacy:mail')['status']=='degraded'


def test_redis_failure_keeps_gateway_and_database_monitoring_available(system, monkeypatch):
    from mailcheck.web.system_monitoring import Monitor
    app, store, pool = system
    monkeypatch.setenv('OFFERPATH_REDIS_URL','redis://unused')
    def fail(*args):raise RuntimeError('password=supersecret')
    monkeypatch.setattr('mailcheck.web.system_monitoring.read_redis',fail)
    data = Monitor(store,pool).snapshot()
    assert next(c for c in data['components'] if c['id']=='gateway')['status']=='healthy'
    assert next(c for c in data['components'] if c['id']=='redis')['status']=='unavailable'
    assert 'supersecret' not in str(data)


def test_real_redis_monitoring_traces_jobs_without_consuming_or_leaking_data(monkeypatch):
    import os
    import uuid
    import time
    import pytest
    from mailcheck.realtime.queue import Broker
    from mailcheck.realtime.settings import Settings
    from mailcheck.web.system_monitoring import read_redis
    url = os.environ.get('OFFERPATH_TEST_REDIS_URL')
    if not url: pytest.skip('set OFFERPATH_TEST_REDIS_URL for real Redis monitoring')
    wid = 'monitor-'+uuid.uuid4().hex
    broker = Broker(url,wid)
    try:
        jid = broker.enqueue('mail',1)
        assert broker.claim('mail','test')[0][0] == jid
        deadline=time.monotonic()+2
        while broker.redis.xlen(broker.prefix+'monitor')<2 and time.monotonic()<deadline: time.sleep(0.01)
        snapshot = read_redis(Settings(url),[wid])[wid]
        assert next(q for q in snapshot['queues'] if q['kind']=='mail')['pending'] == 1
        assert {e['action'] for e in snapshot['events']} == {'queued','started'}
        assert all(e['job_id']==jid for e in snapshot['events'])
        assert broker.ack('mail',jid,'test')
        broker.publish(['messages'],1)
        deadline=time.monotonic()+2
        while broker.redis.xlen(broker.prefix+'monitor')<4 and time.monotonic()<deadline: time.sleep(0.01)
        broker.redis.xadd(broker.prefix+'monitor',{'kind':'mail','action':'password=secret','private':'body'})
        broker.redis.xadd(broker.prefix+'monitor',{'kind':'mail','action':'queued','job_id':'secret','private':'body'})
        before = broker.redis.xlen(broker.prefix+'monitor')
        snapshot = read_redis(Settings(url),[wid])[wid]
        assert {e['action'] for e in snapshot['events']} >= {'completed','published'}
        assert 'secret' not in str(snapshot) and 'body' not in str(snapshot)
        assert broker.redis.xlen(broker.prefix+'monitor') == before
        assert next(q for q in snapshot['queues'] if q['kind']=='mail')['pending'] == 0
    finally:
        keys=list(broker.redis.scan_iter(broker.prefix+'*'))
        if keys:broker.redis.delete(*keys)
        broker.close()


def test_unavailable_worker_propagates_to_processing_health(system, monkeypatch):
    from mailcheck.web.system_monitoring import Monitor
    app, store, pool = system
    monkeypatch.setenv('OFFERPATH_REDIS_URL','redis://unused')
    monkeypatch.setattr('mailcheck.web.system_monitoring.read_redis',lambda *args:{'legacy':{'queues':[{'kind':'mail','pending':2,'retry':1,'dead':1}], 'events':[]}})
    data=Monitor(store,pool).snapshot()
    for key in ['legacy:mail','legacy:calendar','legacy:classify','legacy:delivery']:
        assert next(c for c in data['components'] if c['id']==key)['status']=='unavailable'


def test_slow_telemetry_never_blocks_jobs_and_buffer_is_bounded(monkeypatch):
    import threading
    import time
    from mailcheck.realtime.telemetry import Recorder
    recorder=Recorder(capacity=2)
    entered, release = threading.Event(),threading.Event()
    def slow(*args):
        entered.set()
        release.wait(2)
    monkeypatch.setattr(recorder,'_send',slow)
    try:
        recorder.record('redis://unused','prefix:','mail','queued','1-0')
        assert entered.wait(1)
        started=time.monotonic()
        for _ in range(1000):recorder.record('redis://unused','prefix:','mail','queued','1-0')
        assert time.monotonic()-started<0.5
        assert recorder._queue.qsize()<=2
    finally:
        release.set()
        recorder.close()
