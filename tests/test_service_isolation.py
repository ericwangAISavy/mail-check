import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from mailcheck.shared.pool import SharedPool
from mailcheck.workspace_workers import Worker, WorkerPool
from mailcheck.web.local_monitor import Observer


def test_requests_use_healthy_api_without_restarting_other_workers(tmp_path, monkeypatch):
    pool = SharedPool(SimpleNamespace(root=tmp_path), '', (), size=2)
    monkeypatch.setattr(pool, '_backup', lambda: None)
    slot = pool.slot('legacy')
    other = next(value for value in pool._slots if value != slot and value.startswith('shared-api-'))
    failed, live = Mock(), Mock()
    failed.poll.return_value = 1
    live.poll.return_value = None
    pool.workers[slot] = Worker(slot,1,'failed',failed,Mock(),ready=True)
    survivor = Worker(other,2,'survivor',live,Mock(),ready=True)
    pool.workers[other] = survivor
    assert pool.ensure({'id':'legacy'}) is survivor
    assert pool.assignments['legacy'] == other
    live.terminate.assert_not_called()
    failed.terminate.assert_not_called()


def test_one_blocked_job_recovery_does_not_block_other_job_health_checks(tmp_path, monkeypatch):
    pool = SharedPool(SimpleNamespace(root=tmp_path), '', (), amqp_url='amqp://test', job_size=1)
    monkeypatch.setattr(pool, '_backup', lambda: None)
    release, entered, other_checked = threading.Event(), threading.Event(), threading.Event()
    def check(self, slot):
        if slot == 'shared-job-model-0':
            entered.set()
            release.wait(3)
        else:
            other_checked.set()
    monkeypatch.setattr(WorkerPool, 'check_health', check)
    monkeypatch.setattr(WorkerPool, 'ensure', lambda *args: None)
    async def scenario():
        task = asyncio.create_task(pool._monitor_jobs())
        try:
            assert await asyncio.to_thread(entered.wait,1)
            assert await asyncio.to_thread(other_checked.wait,1)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task,return_exceptions=True)
    asyncio.run(scenario())


def test_incidents_capture_failure_and_recovery_across_monitor_restart(tmp_path):
    observer = Observer(tmp_path, 52400)
    def sample(status):
        return dict(components=[dict(id='shared-api-0',status=status,detail='Runtime evidence')],events=[])
    observer.record_service_changes(sample('healthy'))
    observer.record_service_changes(sample('unavailable'))
    observer.record_service_changes(sample('unavailable'))
    assert len(observer.incidents) == 1
    replacement = Observer(tmp_path, 52400)
    replacement.record_service_changes(sample('unknown'))
    replacement.record_service_changes(sample('healthy'))
    records = json.loads((tmp_path/'monitor-incidents.json').read_text())
    assert [row['action'] for row in records] == ['service_failed','service_unknown','service_recovered']


def test_hung_api_shutdown_is_bounded_to_that_process(tmp_path):
    import subprocess
    pool = SharedPool(SimpleNamespace(root=tmp_path), '', (), size=2)
    process, survivor = Mock(), Mock()
    process.poll.return_value = None
    process.wait.side_effect = [subprocess.TimeoutExpired('worker', 10), 0]
    survivor.poll.return_value = None
    pool.workers['shared-api-0'] = Worker('shared-api-0',1,'a',process,Mock(),ready=True)
    pool.workers['shared-api-1'] = Worker('shared-api-1',2,'b',survivor,Mock(),ready=True)
    pool.stop('shared-api-0')
    process.kill.assert_called_once()
    survivor.terminate.assert_not_called()
    assert 'shared-api-1' in pool.workers


def test_failed_runtime_readiness_recovers_only_affected_shared_api(tmp_path, monkeypatch):
    from mailcheck import workspace_workers
    pool = SharedPool(SimpleNamespace(root=tmp_path), '', (), size=2)
    slot = pool.slot('legacy')
    process = Mock()
    process.poll.return_value = None
    worker = Worker(slot,1,'a',process,Mock(),ready=True)
    pool.workers[slot] = worker
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.get.return_value.status_code = 503
    monkeypatch.setattr(workspace_workers.httpx,'Client',Mock(return_value=client))
    stop = Mock()
    monkeypatch.setattr(pool,'stop',stop)
    for _ in range(3):
        pool.check_health('legacy')
    stop.assert_called_once_with(slot,suspended=False,expected=worker)
    assert client.get.call_args.args[0].endswith('/_internal/availability')
