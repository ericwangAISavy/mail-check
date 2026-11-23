import json
import time
from unittest.mock import patch

from mailcheck.shared.service_health import read_services
from mailcheck.web.local_monitor import Observer


def report(root, slot, *, pid=123, age=0, status='healthy'):
    folder = root / 'shared-runtime' / 'service-health'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (slot + '.json')).write_text(json.dumps(dict(id=slot, pid=pid,
        updated_at=time.time()-age, status=status, detail='Direct runtime check.')), encoding='utf-8')


def test_service_checks_work_when_gateway_is_down(tmp_path):
    report(tmp_path, 'shared-api-0')
    report(tmp_path, 'shared-job-model-0', pid=456)
    observer = Observer(tmp_path, 52400)
    with patch('mailcheck.web.local_monitor.origin_state', return_value='unavailable'), patch(
        'mailcheck.web.local_monitor.fetch_snapshot', side_effect=OSError('gateway stopped')
    ), patch('mailcheck.shared.monitoring.process_running', side_effect=lambda pid: pid == 123):
        observer.sample()
    snapshot = observer.status()['snapshot']
    states = {item['id']:item['status'] for item in snapshot['components']}
    assert states['gateway'] == 'unavailable'
    assert states['shared-api-0'] == 'healthy'
    assert states['shared-job-model-0'] == 'unavailable'
    assert 'shared-job-model-0' in observer.status()['failed_services']
    assert not observer.status()['snapshot_stale']


def test_stale_and_failed_runtime_reports_identify_individual_service(tmp_path):
    report(tmp_path, 'shared-api-0', age=60)
    report(tmp_path, 'shared-job-collection-1', status='unavailable')
    with patch('mailcheck.shared.monitoring.process_running', return_value=True):
        rows = read_services(tmp_path)
    assert rows['shared-api-0']['status'] == 'unavailable'
    assert rows['shared-job-collection-1']['status'] == 'unavailable'


def test_database_and_broker_checks_do_not_depend_on_gateway(tmp_path, monkeypatch):
    import sqlite3
    from mailcheck.web.local_monitor import independent_snapshot
    with sqlite3.connect(tmp_path/'control.db') as conn:
        conn.execute('CREATE TABLE workspaces(id TEXT,name TEXT,root TEXT,enabled INTEGER)')
    monkeypatch.setenv('AMQP_URL', 'amqp://example.test')
    with patch('mailcheck.shared.monitoring.read_rabbit', return_value=[dict(kind='mail',pending=4,retry=0,dead=0)]) as broker:
        snapshot = independent_snapshot(tmp_path, 'unavailable')
    components = {item['id']:item for item in snapshot['components']}
    assert components['gateway']['status'] == 'unavailable'
    assert components['control-db']['status'] == 'healthy'
    assert components['rabbitmq']['status'] == 'healthy'
    assert snapshot['global_queues'][0]['pending'] == 4
    broker.assert_called_once()


def test_reporter_checks_local_runtime_and_finishes_with_stopped_state(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from mailcheck.shared.service_health import report_service
    monkeypatch.setenv('OFFERPATH_CONTROL_ROOT', str(tmp_path))
    monkeypatch.setenv('OFFERPATH_WORKER_ID', 'shared-api-0')
    monkeypatch.setenv('OFFERPATH_WORKER_TOKEN', 'private-token')
    server = SimpleNamespace(started=True, should_exit=False, config=SimpleNamespace(port=12345))
    response = Mock()
    response.__enter__ = Mock(return_value=SimpleNamespace(status=200,read=lambda limit:b'{"ready":true}'))
    response.__exit__ = Mock(return_value=False)
    with patch('mailcheck.shared.service_health.build_opener') as opener:
        opener.return_value.open.return_value = response
        cleanup = report_service(server)
        path = tmp_path/'shared-runtime'/'service-health'/'shared-api-0.json'
        deadline = time.monotonic()+2
        while not path.exists() and time.monotonic()<deadline:
            time.sleep(.01)
        try:
            value = json.loads(path.read_text())
            assert value['status'] == 'healthy'
            assert 'private-token' not in path.read_text()
        finally:
            cleanup()
    assert json.loads(path.read_text())['status'] == 'unavailable'
