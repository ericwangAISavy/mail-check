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
    failed=Worker('alice',1234,'failed',failed_process,Mock(),startup_at=workspace_workers.time.monotonic()-121)
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


def test_worker_readiness_has_a_wall_clock_deadline(monkeypatch,tmp_path):
    import time
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    process=Mock();process.poll.return_value=None
    worker=Worker('alice',1234,'token',process,Mock(),startup_at=0);pool.workers['alice']=worker
    clock=[0.];calls=[];status=[503]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,*args,**kwargs):calls.append(True);clock[0]+=1;return SimpleNamespace(status_code=status[0])
    monkeypatch.setattr(workspace_workers.httpx,'Client',Client)
    monkeypatch.setattr(workspace_workers,'time',SimpleNamespace(time=time.time,monotonic=lambda:clock[0],sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)))
    with pytest.raises(RuntimeError,match='still starting|could not start'):pool.ensure({'id':'alice'})
    assert clock[0]<=21,'Readiness waited long past the page request deadline'
    process.terminate.assert_not_called()
    status[0]=200
    assert pool.ensure({'id':'alice'}) is worker
    process.terminate.assert_not_called()


def test_legacy_backup_does_not_block_other_worker_heartbeats(monkeypatch,tmp_path):
    pool=WorkerPool(SimpleNamespace(root=tmp_path,max_workspaces=4),'',(tmp_path/'config',tmp_path/'db',tmp_path/'auth'))
    process=Mock();process.poll.return_value=None
    pool.workers['bob']=Worker('bob',1234,'healthy',process,Mock(),ready=True)
    entered=Event();release=Event()
    def backup():entered.set();assert release.wait(3)
    monkeypatch.setattr(pool,'_backup',backup)
    monkeypatch.setattr(workspace_workers.subprocess,'Popen',Mock(return_value=process))
    client=MagicMock();client.__enter__.return_value=client;client.get.return_value=SimpleNamespace(status_code=200)
    monkeypatch.setattr(workspace_workers.httpx,'Client',Mock(return_value=client))
    with ThreadPoolExecutor(max_workers=2) as executor:
        starting=executor.submit(pool.ensure,{'id':'legacy','root':None})
        assert entered.wait(2)
        heartbeat=executor.submit(pool.authenticate_worker,'healthy')
        try:assert heartbeat.result(timeout=.2)=='bob'
        finally:release.set();starting.result(timeout=3)


def test_worker_that_exceeds_hard_startup_limit_is_retired(monkeypatch,tmp_path):
    import time
    pool=WorkerPool(SimpleNamespace(root=tmp_path),'',())
    process=Mock();process.poll.return_value=None
    worker=Worker('alice',1234,'token',process,Mock(),startup_at=time.monotonic()-121)
    pool.workers['alice']=worker
    client=MagicMock();client.__enter__.return_value=client
    monkeypatch.setattr(workspace_workers.httpx,'Client',Mock(return_value=client))
    with pytest.raises(RuntimeError,match='could not start'):pool.ensure({'id':'alice'})
    process.terminate.assert_called_once()
    assert 'alice' not in pool.workers


def test_recovery_does_not_start_replacement_until_old_worker_exits(monkeypatch, tmp_path):
    pool = WorkerPool(SimpleNamespace(root=tmp_path), '', ())
    old_process = Mock()
    old_process.poll.return_value = None
    old_worker = Worker('alice', 1234, 'old', old_process, Mock(), ready=True)
    pool.workers['alice'] = old_worker
    waiting, exited = Event(), Event()

    def wait(timeout):
        waiting.set()
        assert exited.wait(3)

    old_process.wait.side_effect = wait
    new_process = Mock()
    new_process.poll.return_value = None
    replacement = Worker('alice', 1235, 'new', new_process, Mock(), ready=True)
    def spawn_replacement(workspace):
        pool.workers['alice'] = replacement
        return replacement

    spawn = Mock(side_effect=spawn_replacement)
    monkeypatch.setattr(pool, '_spawn', spawn)

    with ThreadPoolExecutor(max_workers=1) as executor:
        stopping = executor.submit(pool.stop, 'alice', suspended=False)
        assert waiting.wait(2)
        try:
            with pytest.raises(workspace_workers.WorkerStartupPending, match='restarting'):
                pool.ensure({'id': 'alice'})
            spawn.assert_not_called()
        finally:
            exited.set()
            stopping.result(timeout=3)

    assert pool.ensure({'id': 'alice'}) is replacement
