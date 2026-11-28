from types import SimpleNamespace
import threading


def test_shared_snapshot_counts_processes_once_and_keeps_queues_global(tmp_path, monkeypatch):
    from mailcheck.shared import monitoring
    admins = [{'workspace_id': 'legacy', 'workspace_name': 'Original', 'enabled': True},
              {'workspace_id': 'a'*32, 'workspace_name': 'Other', 'enabled': False}]
    store = SimpleNamespace(root=tmp_path, path=tmp_path/'missing.db', list_admins=lambda: admins,
                            workspace=lambda wid: {'root': str(tmp_path/wid)})
    process = SimpleNamespace(poll=lambda: None)
    pool = SimpleNamespace(amqp_url='amqp://hidden-secret', _lock=threading.Lock(),
        workers={'shared-api-0': SimpleNamespace(process=process, ready=True),
                 'shared-job-model-0': SimpleNamespace(process=process, ready=False)},
        _slots={'shared-api-0', 'shared-job-model-0'}, legacy_paths=(None,tmp_path/'legacy.db'))
    monkeypatch.setattr(monitoring, 'read_rabbit', lambda url: [{'kind':'mail','pending':2,'retry':0,'dead':0}])
    snapshot = monitoring.shared_snapshot(store, pool)
    assert snapshot['architecture'] == 'shared'
    assert snapshot['process_counts'] == {'api': 1, 'collection': 0, 'model': 1}
    assert len([c for c in snapshot['components'] if c['id'].startswith('shared-')]) == 2
    assert snapshot['global_queues'][0]['pending'] == 2
    assert all(w['queues'] == [] for w in snapshot['workspaces'])
    assert snapshot['events'] == [] and snapshot['event_retention'] == 1000
    assert 'hidden-secret' not in repr(snapshot)
    assert all(not c.get('workspace') for c in snapshot['components'] if c['id'].startswith('shared-'))


def test_missing_broker_reports_unavailable_not_zero(tmp_path, monkeypatch):
    from mailcheck.shared import monitoring
    store = SimpleNamespace(root=tmp_path, path=tmp_path/'missing.db', list_admins=lambda: [])
    pool = SimpleNamespace(amqp_url='amqp://secret', workers={}, _lock=threading.Lock(), _slots=set())
    def unavailable(url):
        raise OSError('raw credentials')
    monkeypatch.setattr(monitoring, 'read_rabbit', unavailable)
    result = monitoring.shared_snapshot(store,pool)
    assert result['global_queues'] == []
    assert next(c for c in result['components'] if c['id']=='rabbitmq')['status'] == 'unavailable'
    assert 'raw credentials' not in repr(result)


def test_telemetry_is_workspace_scoped_and_sanitized(tmp_path,monkeypatch):
    import json
    from mailcheck.shared import monitoring
    directory=tmp_path/'shared-runtime'/'legacy'
    directory.mkdir(parents=True)
    safe=dict(id='12345678-1234-4234-8234-123456789abc',at=100,workspace='legacy',component='mail',action='completed',job_id='12345678-1234-4234-8234-123456789abc',status='healthy')
    (directory/'events.json').write_text(json.dumps([safe,{**safe,'workspace':'other'},{**safe,'action':'secret message'},{**safe,'job_id':'credentials'},{**safe,'component':[]},{**safe,'action':{}}]))
    store=SimpleNamespace(root=tmp_path,path=tmp_path/'none',list_admins=lambda:[dict(workspace_id='legacy',workspace_name='Original',enabled=False)])
    pool=SimpleNamespace(amqp_url='fake',workers={},_lock=threading.Lock(),_slots=set())
    monkeypatch.setattr(monitoring,'read_rabbit',lambda url:[])
    result=monitoring.shared_snapshot(store,pool)
    assert len(result['events'])==2
    assert result['event_retention']==1000
    assert 'credentials' not in repr(result) and 'secret message' not in repr(result)
    assert all(event['workspace']=='legacy' for event in result['events'])


def test_broker_metrics_only_passively_read_queue_counts(monkeypatch):
    import sys
    from mailcheck.shared import monitoring
    calls=[]
    class Channel:
        def queue_declare(self,**kwargs):
            assert kwargs['passive'] is True
            assert set(kwargs)=={'queue','passive'}
            calls.append(kwargs['queue'])
            return SimpleNamespace(method=SimpleNamespace(message_count=2))
    class Connection:
        def __init__(self,params):
            assert params.socket_timeout==2
        def channel(self):
            return Channel()
        def close(self):
            calls.append('closed')
    monkeypatch.setitem(sys.modules,'pika',SimpleNamespace(URLParameters=lambda url:SimpleNamespace(),BlockingConnection=Connection))
    rows=monitoring.read_rabbit('amqp://unused')
    assert len(rows)==len(monitoring.KINDS)
    assert all(row['pending']==2 and row['retry']==8 and row['dead']==2 for row in rows)
    assert calls[-1]=='closed'


def test_shared_model_state_uses_file_coordinator_not_legacy_callback(tmp_path,monkeypatch):
    import json
    from mailcheck.shared import monitoring
    store=SimpleNamespace(root=tmp_path,path=tmp_path/'none',list_admins=lambda:[])
    pool=SimpleNamespace(amqp_url='fake',workers={},_lock=threading.Lock(),_slots=set())
    monkeypatch.setattr(monitoring,'read_rabbit',lambda url:[])
    def old_activity():
        raise AssertionError('shared monitoring read legacy model leases')
    def scheduler():
        return next(c for c in monitoring.shared_snapshot(store,pool,old_activity)['components'] if c['id']=='model-scheduler')
    missing=scheduler()
    assert missing['status']=='healthy' and '0 active' in missing['detail']
    state=tmp_path/'shared-runtime'/'model-state.json'
    state.parent.mkdir()
    state.write_text(json.dumps(dict(pid=123,workspace='legacy',started_at=100)))
    calls=[]
    monkeypatch.setattr(monitoring, 'sys', SimpleNamespace(platform='linux'))
    monkeypatch.setattr(monitoring.os,'kill',lambda pid,signal:calls.append((pid,signal)))
    live=scheduler()
    assert live['status']=='healthy' and '1 active' in live['detail']
    assert calls==[(123,0)]
    def gone(pid,signal):
        raise ProcessLookupError()
    monkeypatch.setattr(monitoring.os,'kill',gone)
    assert scheduler()['status']=='unknown'
    state.write_text(json.dumps(dict(pid=True,workspace='legacy')))
    assert scheduler()['status']=='unknown'


def test_windows_model_probe_reads_process_without_sending_console_signals(tmp_path, monkeypatch):
    import ctypes
    import json
    from unittest.mock import Mock
    from mailcheck.shared import monitoring
    state = tmp_path/'shared-runtime'/'model-state.json'
    state.parent.mkdir()
    state.write_text(json.dumps(dict(pid=123, workspace='legacy')))
    monkeypatch.setattr(monitoring, 'sys', SimpleNamespace(platform='win32'), raising=False)
    def unsafe_signal(*args):
        raise AssertionError('Monitoring sent a Windows console control event')
    monkeypatch.setattr(monitoring.os, 'kill', unsafe_signal)
    kernel = Mock()
    kernel.OpenProcess.return_value = 456
    def read_status(handle, output):
        output._obj.value = 259  # STILL_ACTIVE
        return True
    kernel.GetExitCodeProcess.side_effect = read_status
    monkeypatch.setattr(ctypes, 'WinDLL', lambda *args, **kwargs: kernel, raising=False)
    assert monitoring.model_activity_snapshot(tmp_path) == 1
    kernel.OpenProcess.assert_called_once_with(0x1000, False, 123)
    kernel.CloseHandle.assert_called_once_with(456)
    def exited(handle, output):
        output._obj.value = 0
        return True
    kernel.GetExitCodeProcess.side_effect = exited
    assert monitoring.model_activity_snapshot(tmp_path) is None
    assert kernel.CloseHandle.call_count == 2
    # Access denied and failed status reads are unknown, never an active count.
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: 5, raising=False)
    monkeypatch.setattr(ctypes, 'WinError', lambda code: OSError(code, 'Access denied'), raising=False)
    kernel.OpenProcess.return_value = 0
    assert monitoring.model_activity_snapshot(tmp_path) is None
    assert kernel.CloseHandle.call_count == 2
    kernel.OpenProcess.return_value = 789
    kernel.GetExitCodeProcess.side_effect = None
    kernel.GetExitCodeProcess.return_value = False
    assert monitoring.model_activity_snapshot(tmp_path) is None
    kernel.CloseHandle.assert_called_with(789)


def test_model_monitoring_keeps_a_live_process_running(tmp_path):
    import json
    import subprocess
    import sys
    from mailcheck.shared import monitoring
    state = tmp_path/'shared-runtime'/'model-state.json'
    state.parent.mkdir()
    # Isolate the test child from our console on Windows; never signal a real job.
    flags = subprocess.CREATE_NEW_CONSOLE if sys.platform == 'win32' else 0
    with subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                          creationflags=flags, stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as process:
        try:
            state.write_text(json.dumps(dict(pid=process.pid, workspace='legacy')))
            for _ in range(20):
                assert monitoring.model_activity_snapshot(tmp_path) == 1
                assert process.poll() is None
        finally:
            process.terminate()
            process.wait(timeout=10)
        assert monitoring.model_activity_snapshot(tmp_path) is None
