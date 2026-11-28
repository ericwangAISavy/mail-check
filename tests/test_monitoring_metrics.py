import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from mailcheck.shared import telemetry
from tests.test_workspace_gateway import system  # noqa: F401  (pytest fixture)
from mailcheck.web import monitoring_metrics as mm
from mailcheck.web.traffic_metrics import (CLIENT, LATENCY, REQUESTS, SERVER, THROTTLED, TrafficMetrics,
                                           TrafficMiddleware, latency_bin, percentile)


def traffic_app(metrics):
    app = FastAPI()

    @app.get('/api/ok')
    def ok():
        return {'ok': True}

    @app.get('/api/missing')
    def missing():
        raise HTTPException(404)

    @app.get('/api/busy')
    def busy():
        raise HTTPException(503)

    @app.get('/api/boom')
    def boom():
        raise RuntimeError('boom')

    @app.get('/assets/app.js')
    def asset():
        return 'x'

    @app.get('/api/realtime/events')
    def stream():
        return StreamingResponse(iter(['data: 1\n\n']), media_type='text/event-stream')

    app.add_middleware(TrafficMiddleware, metrics=metrics)
    return app


def test_traffic_counts_status_classes_and_skips_static_files():
    metrics = TrafficMetrics()
    client = TestClient(traffic_app(metrics), raise_server_exceptions=False)
    for path in ('/api/ok', '/api/ok', '/api/missing', '/api/busy', '/api/boom', '/assets/app.js', '/api/realtime/events'):
        client.get(path)
    (row,) = metrics.rows(0).values()
    assert row[REQUESTS] == 6            # asset request not counted
    assert row[CLIENT] == 1 and row[SERVER] == 2 and row[THROTTLED] == 1
    assert sum(row[LATENCY:]) == 5       # the event stream has no latency sample


def test_traffic_rows_are_bounded_to_a_day():
    now = [0.0]
    metrics = TrafficMetrics(clock=lambda: now[0])
    for minute in range(24 * 60 + 30):
        now[0] = minute * 60
        metrics.record(200, 0.01)
    rows = metrics.rows(0)
    assert len(rows) <= 24 * 60 + 1 and min(rows) >= 29


def test_latency_percentile_interpolates_inside_bins():
    histogram = [0] * 11
    histogram[latency_bin(40)] = 90       # 25-50 ms
    histogram[latency_bin(900)] = 10      # 500-1000 ms
    assert 25 <= percentile(histogram, .5) <= 50
    assert 500 <= percentile(histogram, .95) <= 1000
    assert percentile([0] * 11, .95) is None


def test_build_series_buckets_traffic_jobs_and_queue_gaps():
    now = 1_800_000_000.0
    minute = int(now // 60)
    traffic = {minute: [10, 2, 1, 1] + [0] * 11, minute - 30: [4, 0, 0, 0] + [4] + [0] * 10}
    jobs = {minute: {'mail': dict.fromkeys(mm.JOB_ACTIONS, 0) | {'completed': 8, 'retry_or_failed': 2, 'duration': [0, 8] + [0] * 8}},
            minute - 1: {'other': dict.fromkeys(mm.JOB_ACTIONS, 0) | {'queued': 3, 'duration': [0] * 10}}}
    queues = {minute: {'mail': [5, 1, 0], 'classify': [2, 0, 1]}}
    result = mm.build_series('1h', traffic, jobs, queues, now=now)
    assert len(result['buckets']) == 60 and result['step'] == 60
    assert result['traffic']['requests'][-1] == 10 and sum(result['traffic']['requests']) == 14
    assert result['summary']['error_rate'] == round(1 / 14, 4)
    assert result['jobs']['completed'][-1] == 8 and result['jobs']['failed'][-1] == 2
    mail = next(stage for stage in result['stages'] if stage['stage'] == 'mail')
    assert mail['failure_rate'] == 0.2 and 1 <= mail['duration_p95'] <= 2
    assert result['queues']['ready'][-1] == 7 and result['queues']['dead'][-1] == 1
    assert result['queues']['ready'][0] is None       # unsampled bucket stays a gap
    assert any(stage['stage'] == 'other' for stage in result['stages'])
    wide = mm.build_series('24h', traffic, jobs, queues, now=now)
    assert len(wide['buckets']) == 96 and sum(wide['traffic']['requests']) == 14


def test_job_minutes_reader_rejects_untrusted_shapes(tmp_path):
    path = tmp_path / 'metrics.json'
    path.write_text(json.dumps({'minutes': {
        '100': {'mail': {'completed': 3, 'retry_or_failed': 'x', 'secret': 9, 'duration': [1] * 10},
                'manual-check': {'completed': 1}, 'events': {'completed': 5}, 7: {}},
        'bad': {'mail': {'completed': 1}}, '5': {'mail': {'completed': 1}}}}))
    rows = mm.read_job_minutes(path, since_minute=50)
    assert set(rows) == {100}
    assert rows[100]['mail']['completed'] == 3 and rows[100]['mail']['retry_or_failed'] == 0
    assert rows[100]['other']['completed'] == 1 and 'events' not in rows[100]
    assert 'secret' not in repr(rows)
    path.write_text('not json')
    assert mm.read_job_minutes(path, 0) == {}


def test_telemetry_batches_events_and_minute_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, '_started', {})
    root = Path(tmp_path)
    at = time.time()
    events = [dict(id=f'id-{i}', at=at + i, workspace='legacy', component='mail', action=action, job_id='7', status='healthy')
              for i, action in enumerate(['queued', 'started', 'completed'])]
    telemetry._write([(root, event) for event in events])
    stored = json.loads((root / 'legacy' / 'events.json').read_text())
    assert [event['action'] for event in stored] == ['queued', 'started', 'completed']
    minutes = json.loads((root / 'metrics.json').read_text())['minutes']
    row = next(iter(minutes.values()))['mail']
    assert row['queued'] == 1 and row['completed'] == 1 and sum(row['duration']) == 1
    # A second batch merges into the same file instead of replacing it.
    telemetry._write([(root, dict(events[0], id='id-9'))])
    assert sum(r['mail']['queued'] for r in json.loads((root / 'metrics.json').read_text())['minutes'].values()) == 2


def test_telemetry_event_log_stays_capped(tmp_path):
    root = Path(tmp_path)
    batch = [(root, dict(id=str(i), at=time.time(), workspace='legacy', component='mail', action='queued', job_id=str(i), status='healthy'))
             for i in range(telemetry.EVENT_LIMIT + 50)]
    telemetry._write(batch)
    stored = json.loads((root / 'legacy' / 'events.json').read_text())
    assert len(stored) == telemetry.EVENT_LIMIT and stored[-1]['id'] == str(telemetry.EVENT_LIMIT + 49)


def test_gateway_metrics_endpoint(system, monkeypatch):
    from tests.test_workspace_gateway import login
    app, store, pool = system
    monkeypatch.delenv('OFFERPATH_REDIS_URL', raising=False)
    store.create_admin(store.owner_token, 'alice', 'Alice workspace', 'temporary-pass-123')
    with TestClient(app) as client:
        assert client.get('/api/admin/system-monitoring/metrics').status_code == 401
        login(client)
        for _ in range(3):
            client.get('/api/admin/system-monitoring')       # its own polling is not traffic
            client.get('/api/auth/session')
        response = client.get('/api/admin/system-monitoring/metrics?range=6h')
        assert response.status_code == 200
        data = response.json()
        assert data['range'] == '6h' and len(data['buckets']) == 72
        assert data['jobs_tracked'] is False      # no shared workers in this gateway
        assert 3 <= data['summary']['requests'] < 9 and data['summary']['p95'] is not None
        assert client.get('/api/admin/system-monitoring/metrics?range=7d').status_code == 422
        login(client, 'alice', 'temporary-pass-123')
        client.post('/api/auth/password', json={'password': 'alice-final-pass-123'})
        assert client.get('/api/admin/system-monitoring/metrics').status_code == 403


def test_monitoring_requests_are_not_counted_as_traffic():
    metrics = TrafficMetrics()
    app = traffic_app(metrics)

    @app.get('/api/admin/system-monitoring')
    def monitoring():
        return {}

    client = TestClient(app)
    client.get('/api/admin/system-monitoring')
    client.get('/api/ok')
    assert sum(row[REQUESTS] for row in metrics.rows(0).values()) == 1


def test_atomic_json_retries_while_a_reader_holds_the_file(tmp_path):
    import threading
    from mailcheck.shared.state import atomic_json
    path = tmp_path / 'metrics.json'
    atomic_json(path, {'v': 1})
    reader = path.open('rb')
    threading.Timer(0.1, reader.close).start()   # e.g. a monitoring read
    atomic_json(path, {'v': 2})
    assert json.loads(path.read_text()) == {'v': 2}


def test_telemetry_buffers_metric_writes_and_repairs_malformed_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, '_started', {})
    monkeypatch.setattr(telemetry, '_pending', {})
    root = Path(tmp_path)
    minute = str(int(time.time() // 60))
    (root / 'metrics.json').write_text(json.dumps({'minutes': {minute: 'corrupt', '7': {'mail': {'completed': 1}}}}))
    event = dict(id='a', at=time.time(), workspace='legacy', component='mail', action='completed', job_id='1', status='healthy')
    monkeypatch.setattr(telemetry, '_last_flush', time.monotonic())
    telemetry._write([(root, event)], flush=False)            # buffered: file unchanged
    assert json.loads((root / 'metrics.json').read_text())['minutes'][minute] == 'corrupt'
    assert telemetry._pending
    telemetry._flush_metrics()
    minutes = json.loads((root / 'metrics.json').read_text())['minutes']
    assert minutes[minute] == {'mail': {'completed': 1}} and '7' not in minutes   # repaired; old minute pruned
    assert not telemetry._pending
