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
