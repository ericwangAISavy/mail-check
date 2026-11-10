from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread, main_thread
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from mailcheck import workspace_workers
from mailcheck.workspace_workers import Worker, WorkerPool


@pytest.mark.parametrize("ready_after", [1, 100])
def test_late_readiness_waiter_does_not_stop_worker_ready_for_another_request(monkeypatch, tmp_path, ready_after):
    pool = WorkerPool(SimpleNamespace(root=tmp_path), '', ())
    process = Mock()
    process.poll.return_value = None
    worker = Worker('alice', 1234, 'token', process, Mock())
    pool.workers['alice'] = worker
    waiting = Event()
    ready = Event()
    attempts = 0

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs):
            nonlocal attempts
            if current_thread() is main_thread():
                return SimpleNamespace(status_code=200)
            attempts += 1
            if attempts == ready_after:
                waiting.set()
                assert ready.wait(5)
            return SimpleNamespace(status_code=503)

    monkeypatch.setattr(workspace_workers.httpx, 'Client', Client)
    monkeypatch.setattr(workspace_workers.time, 'sleep', lambda _: None)
    with ThreadPoolExecutor(max_workers=1) as executor:
        delayed = executor.submit(pool.ensure, {'id': 'alice'})
        assert waiting.wait(5)
        try:
            assert pool.ensure({'id': 'alice'}) is worker
        finally:
            ready.set()
        assert delayed.result(timeout=5) is worker
    assert pool.workers['alice'] is worker
    process.terminate.assert_not_called()


def test_spawn_failure_closes_open_worker_log(monkeypatch, tmp_path):
    pool = WorkerPool(SimpleNamespace(root=tmp_path, max_workspaces=2), '',
                      (tmp_path/'config.toml', tmp_path/'db', tmp_path/'auth'))
    log = Mock()
    log.name = str(tmp_path/'worker.log')
    monkeypatch.setattr(workspace_workers.socket, 'socket', MagicMock())
    socket = workspace_workers.socket.socket.return_value.__enter__.return_value
    socket.getsockname.return_value = ('127.0.0.1', 1234)
    monkeypatch.setattr(workspace_workers.Path, 'open', Mock(return_value=log))
    monkeypatch.setattr(workspace_workers.os, 'chmod', Mock())
    monkeypatch.setattr(workspace_workers.subprocess, 'Popen', Mock(side_effect=OSError('out of resources')))
    with pytest.raises(OSError, match='out of resources'):
        pool.ensure({'id': 'alice', 'root': str(tmp_path/'alice')})
    log.close.assert_called_once()
    assert pool.workers == {}


def test_readiness_response_after_suspension_does_not_return_stopped_worker(monkeypatch, tmp_path):
    pool = WorkerPool(SimpleNamespace(root=tmp_path), '', ())
    process = Mock()
    process.poll.return_value = None
    worker = Worker('alice', 1234, 'token', process, Mock())
    pool.workers['alice'] = worker

    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs):
            pool.stop('alice')
            return SimpleNamespace(status_code=200)

    monkeypatch.setattr(workspace_workers.httpx, 'Client', Client)
    with pytest.raises(RuntimeError, match='could not start'):
        pool.ensure({'id': 'alice'})
    assert not worker.ready
    assert 'alice' not in pool.workers
    process.terminate.assert_called_once()


def test_unresponsive_ready_worker_is_removed_after_three_failed_probes(monkeypatch,tmp_path):
    import httpx
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    process=Mock();process.poll.return_value=None
    worker=Worker('alice',1234,'token',process,Mock(),ready=True)
    pool.workers['alice']=worker
    client=MagicMock();client.__enter__.return_value=client
    client.get.side_effect=httpx.ConnectError('listener unavailable')
    monkeypatch.setattr(workspace_workers.httpx,'Client',Mock(return_value=client))
    pool.check_health('alice');pool.check_health('alice')
    process.terminate.assert_not_called()
    pool.check_health('alice')
    assert 'alice' not in pool.workers
    process.terminate.assert_called_once()
    assert 'alice' not in pool.stopped


def test_overloaded_worker_stays_running_and_resets_health_failures(monkeypatch,tmp_path):
    import httpx
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    process=Mock();process.poll.return_value=None
    worker=Worker('alice',1234,'token',process,Mock(),ready=True)
    pool.workers['alice']=worker
    client=MagicMock();client.__enter__.return_value=client
    client.get.side_effect=[httpx.ConnectError('offline'),SimpleNamespace(status_code=503),httpx.ConnectError('offline'),httpx.ConnectError('offline')]
    monkeypatch.setattr(workspace_workers.httpx,'Client',Mock(return_value=client))
    for _ in range(4):pool.check_health('alice')
    process.terminate.assert_not_called()


def test_expected_stop_does_not_kill_a_replacement_worker(tmp_path):
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    old=Worker('alice',1,'old',Mock(),Mock())
    new=Worker('alice',2,'new',Mock(),Mock())
    pool.workers['alice']=new
    pool.stop('alice',suspended=False,expected=old)
    assert pool.workers['alice'] is new
    new.process.terminate.assert_not_called()


def test_failed_worker_shutdown_does_not_skip_other_workers(tmp_path):
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    pool.workers={'alice':Mock(),'bob':Mock()}
    pool.stop=Mock(side_effect=[OSError('first process failed to stop'),None])
    pool.close()
    assert pool.stop.call_count==2


def test_startup_cleanup_wait_does_not_block_other_worker_authentication(monkeypatch,tmp_path):
    from threading import Thread
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    failed_process=Mock();failed_process.poll.return_value=None
    failed=Worker('alice',1234,'failed',failed_process,Mock())
    healthy_process=Mock();healthy_process.poll.return_value=None
    healthy=Worker('bob',1235,'healthy',healthy_process,Mock(),ready=True)
    pool.workers={'alice':failed,'bob':healthy}
    authenticated=Event()
    def wait(timeout):
        def authenticate():
            if pool.authenticate_worker('healthy')=='bob':authenticated.set()
        Thread(target=authenticate,daemon=True).start()
        assert authenticated.wait(.3), 'Stopping one worker held the lock needed by other worker heartbeats'
    failed_process.wait.side_effect=wait
    client=MagicMock();client.__enter__.return_value=client
    client.get.return_value=SimpleNamespace(status_code=503)
    monkeypatch.setattr(workspace_workers.httpx,'Client',Mock(return_value=client))
    monkeypatch.setattr(workspace_workers.time,'sleep',lambda _:None)
    with pytest.raises(RuntimeError,match='could not start'):pool.ensure({'id':'alice'})
    healthy_process.terminate.assert_not_called()
