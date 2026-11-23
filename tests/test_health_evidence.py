import json
import sqlite3
import time
from unittest.mock import patch

from mailcheck.web.local_monitor import Observer


def test_worker_health_requires_transport_and_recent_progress_without_killing_slow_jobs():
    from mailcheck.shared.health_evidence import WorkerProgress
    clock = [100.0]
    progress = WorkerProgress(clock=lambda: clock[0], slow_seconds=60)
    assert progress.snapshot()['status'] == 'unknown'
    progress.poll()
    assert progress.snapshot()['status'] == 'healthy'
    progress.start(dict(id='job-123', workspace_id='legacy', kind='classify', attempt=2))
    clock[0] += 61
    progress.poll()
    slow = progress.snapshot()
    assert slow['status'] == 'degraded'
    assert slow['reason'] == 'operation_slow'
    assert slow['job_id'] == 'job-123'
    assert slow['attempt'] == 3
    progress.finish()
    clock[0] += 31
    assert progress.snapshot()['reason'] == 'consumer_stalled'
    progress.failed(ConnectionRefusedError('amqp://secret:password@host'))
    result = progress.snapshot()
    assert result['reason'] == 'connection_refused'
    assert 'secret' not in json.dumps(result)
    progress.poll()
    assert progress.snapshot()['status'] == 'healthy'


def test_incidents_preserve_degraded_unknown_and_full_recovery_evidence(tmp_path):
    observer = Observer(tmp_path, 1)
    def sample(status):
        observer.record_service_changes(dict(events=[], components=[dict(id='shared-job-model-0',
            status=status, detail='Safe diagnostic', reason='connection_refused', pid=456,
            checked_at=time.time(), job_id='job-123')]))
    for status in ['healthy', 'degraded', 'degraded', 'unknown', 'healthy']:
        sample(status)
    replacement = Observer(tmp_path, 1)
    assert [row['action'] for row in replacement.incidents] == ['service_degraded','service_unknown','service_recovered']
    assert replacement.incidents[0]['reason'] == 'connection_refused'
    assert replacement.incidents[0]['pid'] == 456
    assert replacement.incidents[0]['job_id'] == 'job-123'


def test_database_probe_exposes_read_scope_and_sqlite_failure_category(tmp_path):
    from mailcheck.web.system_monitoring import database_snapshot
    path = tmp_path/'db.sqlite'
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE example(value TEXT)')
    result = database_snapshot(path)
    assert result['scope'] == 'sqlite_read'
    assert result['write_status'] == 'unknown'
    with sqlite3.connect(path) as conn:
        conn.execute('BEGIN EXCLUSIVE')
        result = database_snapshot(path)
    assert result['status'] == 'unavailable'
    assert result['reason'] == 'sqlite_busy'
    assert result['error_type'] == 'OperationalError'
    assert result['duration_ms'] >= 0
    with patch.object(type(path),'is_file',side_effect=PermissionError('private path')):
        result=database_snapshot(path)
    assert result['status']=='unavailable'
    assert result['reason']=='permission_denied'


def test_independent_registry_failures_remain_visible(tmp_path):
    from mailcheck.web.local_monitor import independent_snapshot
    (tmp_path/'control.db').write_bytes(b'not a database')
    result = independent_snapshot(tmp_path, 'ready')
    registry = next(item for item in result['components'] if item['id'] == 'workspace-registry')
    assert registry['status'] == 'unavailable'
    assert registry['error_type'] == 'DatabaseError'


def test_independent_charts_survive_gateway_outage_without_inventing_traffic(tmp_path):
    observer = Observer(tmp_path, 1)
    observer.latest = dict(global_queues=[dict(kind='mail',pending=3,retry=1,dead=0)],checked_at=time.time())
    with patch('mailcheck.web.local_monitor.fetch_snapshot', side_effect=OSError('gateway unavailable')):
        observer.sample_metrics()
    metrics = observer.metrics['1h']
    assert metrics['traffic_available'] is False
    assert metrics['queues']['ready'][-1] == 3
    assert metrics['source'] == 'independent'


def test_public_probe_checks_shell_and_asset_bytes_and_exposes_access_denial(tmp_path):
    from mailcheck.web.public_health import public_snapshot
    (tmp_path/'assets').mkdir()
    (tmp_path/'assets'/'index-test.js').write_bytes(b'export const ok=true;')
    requests = []
    def fetch(url):
        requests.append(url)
        if '/assets/' in url:
            return 200, 'text/javascript', b'<html>Broken cache</html>'
        return 200, 'text/html', b'<div id="root"></div><script type="module" src="/assets/index-test.js"></script>'
    result = public_snapshot('https://example.test', tmp_path, fetch=fetch)
    assert result['status'] == 'unavailable'
    assert result['reason'] == 'asset_content_mismatch'
    assert len(requests) == 2
    denied = public_snapshot('https://example.test', tmp_path, fetch=lambda url:(403,'text/html',b'Access denied'))
    assert denied['reason'] == 'http_403'
    assert denied['status'] == 'unknown'


def test_worker_report_keeps_source_timestamps_and_safe_evidence(tmp_path):
    from mailcheck.shared.service_health import read_services
    directory = tmp_path/'shared-runtime'/'service-health'
    directory.mkdir(parents=True)
    checked = time.time()
    (directory/'shared-job-model-0.json').write_text(json.dumps(dict(id='shared-job-model-0',pid=123,
        updated_at=checked,status='degraded',detail='Slow operation',evidence=dict(reason='operation_slow',
        job_id='job-123',scope='consumer_progress',operation_age_seconds=1000))))
    with patch('mailcheck.shared.monitoring.process_running', return_value=True):
        result = read_services(tmp_path)['shared-job-model-0']
    assert result['status'] == 'degraded'
    assert result['checked_at'] == checked
    assert result['pid'] == 123
    assert result['reason'] == 'operation_slow'
    assert result['operation_age_seconds'] == 1000


def test_request_diagnostics_correlate_failures_without_logging_queries_or_error_text(caplog):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mailcheck.web.request_diagnostics import RequestDiagnostics
    app = FastAPI()
    app.add_middleware(RequestDiagnostics)
    @app.get('/api/example')
    def endpoint():
        return __import__('starlette.responses',fromlist=['Response']).Response(status_code=503)
    identity = '12345678-1234-1234-1234-123456789abc'
    with TestClient(app) as client:
        response = client.get('/api/example?token=private-secret',headers={'X-Request-ID':identity})
    assert response.headers['X-Request-ID'] == identity
    assert identity in caplog.text
    assert 'http_status=503' in caplog.text
    assert 'private-secret' not in caplog.text


def test_live_consumer_cannot_stay_healthy_when_broker_claim_fails(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from mailcheck.shared import runtime
    consumer = runtime.Consumer(SimpleNamespace(root=tmp_path),(), 'amqp://test','collection')
    class Broker:
        def claim(self,kind):
            consumer.stop.set()
            raise ConnectionRefusedError('private connection details')
        def close(self):
            pass
    monkeypatch.setattr(runtime,'RabbitBroker',lambda url:Broker())
    consumer.run()
    assert consumer.health.snapshot()['status'] == 'degraded'
    assert consumer.health.snapshot()['reason'] == 'connection_refused'


def test_independent_queue_history_is_restored_after_monitor_restart(tmp_path):
    observer = Observer(tmp_path, 1)
    observer.latest = dict(checked_at=time.time(),global_queues=[dict(kind='mail',pending=7,retry=2,dead=1)])
    with patch('mailcheck.web.local_monitor.fetch_snapshot', side_effect=OSError()):
        observer.sample_metrics()
        restarted = Observer(tmp_path,1)
        restarted.sample_metrics()
    assert restarted.metrics['1h']['queues']['ready'][-1] == 7
    assert restarted.metrics['1h']['traffic_available'] is False


def test_stopped_telemetry_writer_is_not_fresh_coverage(monkeypatch):
    from types import SimpleNamespace
    from mailcheck.shared import telemetry
    monkeypatch.setattr(telemetry,'_thread',SimpleNamespace(is_alive=lambda:True))
    monkeypatch.setattr(telemetry,'_last_writer_activity',time.time()-90,raising=False)
    evidence = telemetry.health_snapshot()
    assert evidence['telemetry_status'] == 'unavailable'
    assert evidence['telemetry_reason'] == 'writer_stalled'


def test_stale_job_file_does_not_invent_current_observation_coverage(tmp_path):
    folder=tmp_path/'shared-runtime'
    folder.mkdir()
    minute=int(time.time()//60)-2
    (folder/'metrics.json').write_text(json.dumps({'minutes':{str(minute):{'mail':{'completed':4}}}}))
    observer=Observer(tmp_path,1)
    with patch('mailcheck.web.local_monitor.fetch_snapshot',side_effect=OSError()):
        observer.sample_metrics()
    result=observer.metrics['1h']
    assert result['jobs_current_available'] is False
    assert result['summary']['completed'] == 4
    assert result['jobs']['completed'][-1] is None
    assert all(value is None for value in result['jobs']['completed'])


def test_telemetry_persistence_failure_cannot_report_healthy(monkeypatch):
    from types import SimpleNamespace
    from mailcheck.shared import telemetry
    monkeypatch.setattr(telemetry,'_thread',SimpleNamespace(is_alive=lambda:True))
    monkeypatch.setattr(telemetry,'_last_writer_activity',time.time())
    monkeypatch.setattr(telemetry,'_publication_errors',{'metrics':time.time()},raising=False)
    assert telemetry.health_snapshot()['telemetry_status']=='degraded'
    assert telemetry.health_snapshot()['telemetry_reason']=='writer_persistence_failed'


def test_missing_job_coverage_stays_a_gap_after_minute_rollover_and_restart(tmp_path):
    from mailcheck.web import local_monitor
    observer=Observer(tmp_path,1)
    now=int(time.time()//60)*60
    with patch.object(local_monitor,'fetch_snapshot',side_effect=OSError()), patch.object(local_monitor.time,'time',return_value=now):
        observer.sample_metrics()
    with patch.object(local_monitor,'fetch_snapshot',side_effect=OSError()), patch.object(local_monitor.time,'time',return_value=now+60):
        replacement=Observer(tmp_path,1)
        replacement.sample_metrics()
    result=replacement.metrics['1h']
    previous=result['buckets'].index(now)
    assert result['jobs']['completed'][previous] is None


def test_incident_persistence_retries_even_without_a_new_status_change(tmp_path):
    observer=Observer(tmp_path,1)
    def sample():
        return dict(events=[],components=[dict(id='gateway',status='unavailable',detail='Listener failed')])
    with patch('mailcheck.shared.state.atomic_json',side_effect=PermissionError()):
        observer.record_service_changes(sample())
    observer.record_service_changes(sample())
    assert json.loads((tmp_path/'monitor-incidents.json').read_text())[0]['component']=='gateway'
