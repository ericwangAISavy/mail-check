import asyncio
import time

import httpx
from fastapi import FastAPI

from types import SimpleNamespace
from unittest.mock import Mock

from mailcheck.shared.pool import SharedPool


def test_shared_pool_preserves_original_backup_gate(tmp_path,monkeypatch):
    pool=SharedPool(SimpleNamespace(root=tmp_path),'http://gateway',
        (tmp_path/'config',tmp_path/'db',tmp_path/'auth'))
    backup=Mock(side_effect=RuntimeError('Original backup is invalid'))
    monkeypatch.setattr(pool,'_backup',backup)
    process=Mock()
    process.poll.return_value=None
    def spawn(record):
        worker=SimpleNamespace(workspace_id=record['id'],process=process,ready=True,startup_at=time.monotonic())
        pool.workers[record['id']]=worker
        return worker
    spawn=Mock(side_effect=spawn)
    monkeypatch.setattr(pool,'_spawn',spawn)
    import pytest
    with pytest.raises(RuntimeError,match='backup'):
        pool.ensure({'id':'legacy','root':None})
    spawn.assert_not_called()


def test_slots_are_fixed_and_workspace_suspension_does_not_kill(tmp_path, monkeypatch):
    pool = SharedPool(SimpleNamespace(root=tmp_path), 'http://gateway', (tmp_path/'c', tmp_path/'d',tmp_path/'auth'), size=2)
    spawned = []
    def spawn(record):
        worker = SimpleNamespace(workspace_id=record['id'], process=Mock(), ready=True, startup_at=time.monotonic())
        worker.process.poll.return_value = None
        pool.workers[record['id']] = worker
        spawned.append(worker)
        return worker
    monkeypatch.setattr(pool, '_spawn', spawn)
    for n in range(100):
        pool.ensure({'id': f'{n:032x}'})
    assert len(spawned) <= 2
    wid = '0'*32
    assert pool.slot(wid) == SharedPool(SimpleNamespace(root=tmp_path), '', (), size=2).slot(wid)
    pool.stop(wid)
    for worker in spawned:
        worker.process.terminate.assert_not_called()


def test_draining_job_keeps_model_token_until_process_exits(tmp_path,monkeypatch):
    from mailcheck.shared import pool as module
    monkeypatch.setenv('AMQP_URL','amqp://test')
    process=Mock()
    process.poll.return_value=None
    monkeypatch.setattr(module.subprocess,'Popen',lambda *args,**kwargs:process)
    pool=SharedPool(SimpleNamespace(root=tmp_path),'http://gateway',(tmp_path/'c',tmp_path/'d'))
    worker=pool._spawn({'id':'shared-job-model-0'})
    worker.ready=True
    def drain():
        assert pool.authenticate_worker(worker.token)=='shared-job-model-0'
    process.wait.side_effect=drain
    pool.stop('shared-job-model-0')
    assert pool.authenticate_worker(worker.token) is None
    process.kill.assert_not_called()


def test_dispatcher_authenticates_and_scopes_concurrent_requests(tmp_path):
    from mailcheck.shared.api import create_dispatcher
    from mailcheck.workspaces import current_workspace, provision
    paths = (tmp_path/'config', tmp_path/'database')
    records = {'legacy': {'id': 'legacy', 'root': None}}
    for wid in ('a'*32, 'b'*32):
        records[wid] = {'id': wid, 'root': str(provision(tmp_path/'workspaces', wid))}
    def workspace(wid):
        if wid not in records:
            raise ValueError('unknown')
        return records[wid]
    reader = SimpleNamespace(root=tmp_path, workspace=workspace)
    app = FastAPI()
    @app.get('/context')
    async def context():
        first = current_workspace()
        await asyncio.sleep(.01)
        assert current_workspace() is first
        return {'id': first.workspace_id}
    @app.get('/sync-context')
    def sync_context():
        return {'id': current_workspace().workspace_id}
    dispatcher = create_dispatcher(reader, 'secret', paths, app=app)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dispatcher), base_url='http://test') as client:
            assert (await client.get('/_internal/ready')).status_code == 403
            assert (await client.get('/_internal/ready', headers={'x-offerpath-worker':'secret'})).status_code == 200
            assert (await client.get('/context', headers={'x-offerpath-worker':'secret'})).status_code == 403
            assert (await client.get('/context', headers={'x-offerpath-worker':'secret', 'x-offerpath-workspace':'missing'})).status_code == 403
            async def request(wid):
                headers = {'x-offerpath-worker':'secret', 'x-offerpath-workspace':wid}
                assert (await client.get('/context', headers=headers)).json() == {'id':wid}
                assert (await client.get('/sync-context', headers=headers)).json() == {'id':wid}
            await asyncio.gather(*(request(wid) for wid in records))
            assert current_workspace() is None
    asyncio.run(check())


def test_spawn_environment_is_shared_and_close_owns_only_slots(tmp_path, monkeypatch):
    from mailcheck.shared import pool as module
    processes = []
    def popen(command, **kwargs):
        process = Mock()
        process.poll.return_value = None
        processes.append((command, kwargs, process))
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    monkeypatch.setenv('OFFERPATH_WORKSPACE_ID', 'inherited')
    monkeypatch.setenv('OFFERPATH_WORKSPACE_ROOT', '/inherited')
    pool = SharedPool(SimpleNamespace(root=tmp_path), 'http://gateway', (tmp_path/'c', tmp_path/'d'))
    slot = pool.slot('legacy')
    worker = pool._spawn({'id':slot})
    command, kwargs, process = processes[0]
    assert 'mailcheck.shared.api' in command
    assert 'OFFERPATH_WORKSPACE_ID' not in kwargs['env']
    assert 'OFFERPATH_WORKSPACE_ROOT' not in kwargs['env']
    assert kwargs['env']['OFFERPATH_CONTROL_ROOT'] == str(tmp_path)
    assert pool.authenticate_worker(worker.token) == slot
    pool.stop('legacy')
    process.terminate.assert_not_called()
    assert pool.authenticate_worker(worker.token) == slot
    pool.close()
    process.terminate.assert_called_once()
    assert worker.log.closed


def test_explicit_broker_mode_has_fixed_job_processes(tmp_path, monkeypatch):
    from mailcheck.shared import pool as module
    monkeypatch.setenv('AMQP_URL', 'amqp://unused-test-value')
    spawned = []
    def popen(command, **kwargs):
        process = Mock()
        process.poll.return_value = None
        spawned.append((command, kwargs, process))
        return process
    monkeypatch.setattr(module.subprocess, 'Popen', popen)
    pool = SharedPool(SimpleNamespace(root=tmp_path), '', (tmp_path/'c', tmp_path/'d'), size=2, job_size=3)
    assert len(pool.job_slots) == 4
    for slot in pool.job_slots:
        worker = pool._spawn({'id':slot})
        assert pool.authenticate_worker(worker.token) == slot
    assert len(spawned) == 4
    assert all('mailcheck.shared.runtime' in command for command, _, _ in spawned)
    assert [kwargs['env']['OFFERPATH_JOB_LANE'] for _, kwargs, _ in spawned].count('collection') == 3
    pool.stop('legacy')
    for _, _, process in spawned:
        process.terminate.assert_not_called()
    pool.close()
    for _, _, process in spawned:
        process.terminate.assert_called_once()


def test_parent_supervisor_requests_graceful_shutdown(monkeypatch):
    from mailcheck.shared.lifecycle import supervise
    import os
    import threading
    signals = Mock()
    monkeypatch.setattr(os, 'kill', signals)
    monkeypatch.setattr(os, '_exit', signals)
    stopped = threading.Event()
    server = SimpleNamespace(should_exit=False)
    failures = []
    def probe():
        failures.append(1)
        raise ConnectionError('parent unavailable')
    def stop():
        assert server.should_exit is False
        stopped.set()
    cleanup = supervise(server, stop, probe=probe, interval=.001)
    assert stopped.wait(1)
    cleanup()
    assert len(failures) == 3
    assert server.should_exit is True
    signals.assert_not_called()


def test_parent_supervisor_accepts_overload_and_rejects_revoked_token():
    from mailcheck.shared.lifecycle import supervise
    import threading
    server = SimpleNamespace(should_exit=False)
    stopped = threading.Event()
    statuses = iter([503, 200, 401])
    cleanup = supervise(server, stopped.set, probe=lambda: next(statuses), interval=.001)
    assert stopped.wait(1)
    cleanup()
    assert server.should_exit is True


def test_shared_api_holds_process_slot_lock(tmp_path, monkeypatch):
    import sys
    import uvicorn
    from mailcheck.shared import api, control, lifecycle
    from mailcheck.workspace_workers import InstanceLock, InstanceAlreadyRunningError
    import pytest
    slot = 'shared-api-0'
    monkeypatch.setenv('OFFERPATH_WORKER_ID', slot)
    monkeypatch.setenv('OFFERPATH_CONTROL_ROOT', str(tmp_path))
    monkeypatch.setenv('OFFERPATH_LEGACY_CONFIG_PATH', str(tmp_path/'config.toml'))
    monkeypatch.setenv('OFFERPATH_LEGACY_DB_PATH', str(tmp_path/'db'))
    monkeypatch.setenv('OFFERPATH_WORKER_TOKEN', 'secret')
    monkeypatch.setattr(sys, 'argv', ['shared.api', '--port', '54321'])
    monkeypatch.setattr(control, 'ControlReader', Mock())
    monkeypatch.setattr(api, 'create_dispatcher', Mock(return_value=object()))
    cleanup = Mock()
    monkeypatch.setattr(lifecycle, 'supervise', Mock(return_value=cleanup))
    held = []
    class Server:
        def __init__(self, config):
            pass
        def run(self):
            with pytest.raises(InstanceAlreadyRunningError):
                with InstanceLock(tmp_path/'shared-runtime'/'processes'/f'{slot}.lock'):
                    pass
            held.append(True)
    monkeypatch.setattr(uvicorn, 'Server', Server)
    monkeypatch.setattr(uvicorn, 'Config', Mock())
    api.main()
    assert held == [True]
    cleanup.assert_called_once()
    with InstanceLock(tmp_path/'shared-runtime'/'processes'/f'{slot}.lock'):
        pass


def test_dispatcher_commit_guard_rejects_changed_workspace(tmp_path):
    from mailcheck.shared.api import create_dispatcher
    from mailcheck.workspaces import current_commit_guard
    enabled = [True]
    def lookup(wid):
        if not enabled[0]:
            raise ValueError('disabled')
        return {'id': 'legacy', 'root': None}
    app = FastAPI()
    @app.get('/check')
    def check():
        enabled[0] = False
        guard = current_commit_guard()
        assert guard is not None
        try:
            guard()
        except ValueError:
            return {'blocked': True}
        return {'blocked': False}
    dispatcher = create_dispatcher(SimpleNamespace(root=tmp_path, workspace=lookup),
                                   'secret', (tmp_path/'c', tmp_path/'d'), app=app)
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=dispatcher), base_url='http://test') as client:
            result = await client.get('/check', headers={'x-offerpath-worker':'secret', 'x-offerpath-workspace':'legacy'})
            assert result.json() == {'blocked': True}
    asyncio.run(request())

def test_expensive_sqlite_read_releases_session_at_deadline(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import pytest

    from mailcheck import db

    path = tmp_path / 'deadline.db'
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(db, 'time', SimpleNamespace(monotonic=lambda: clock.now))

    def advance_clock(value):
        clock.now = 2.0
        return value

    with pytest.raises(db.ReadDeadlineExpired):
        with db.session(path, read_deadline=1.0) as conn:
            conn.create_function('advance_clock', 1, advance_clock)
            conn.execute('''
                WITH RECURSIVE steps(n) AS (
                    SELECT 1 UNION ALL SELECT n + 1 FROM steps WHERE n < 100000
                )
                SELECT sum(advance_clock(n)) FROM steps
            ''').fetchone()

    with db.session(path) as conn:
        assert conn.execute('SELECT 1').fetchone()[0] == 1
