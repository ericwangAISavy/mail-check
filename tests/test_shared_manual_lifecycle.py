import json
import time
from unittest.mock import Mock

import pytest

from mailcheck.shared.dispatch import submit_manual
from mailcheck.shared.runtime import execute_job
from mailcheck.shared.state import JobState
from tests.test_shared_runtime import manual_fixture


def test_completed_manual_delivery_is_not_executed_again(tmp_path):
    reader,legacy,fields,_=manual_fixture(tmp_path)
    operation=Mock(return_value='done')
    execute_job(reader,legacy,fields,handler=operation)
    execute_job(reader,legacy,fields,handler=operation)
    assert operation.call_count==1
    record=json.loads((reader.root/'shared-runtime'/'dispatch'/f"{fields['dispatch_id']}.json").read_text())
    assert record['state']=='succeeded'
    assert 'token' not in record


def test_transient_failure_remains_pending_and_cannot_be_replaced(tmp_path,monkeypatch):
    from mailcheck.web import app as web
    reader,legacy,fields,_=manual_fixture(tmp_path)
    state=JobState(reader.root/'shared-runtime'/'legacy'/'job.json')
    state.update(job_id=fields['id'],running=True,queued_at=time.time()-500)
    def fail(body,**kwargs):
        web._start_job(lambda:(_ for _ in ()).throw(ConnectionError('transient')),failed='failed',verify_sourcing=False)
    monkeypatch.setattr(web,'_run_check',fail)
    with pytest.raises(ConnectionError):
        execute_job(reader,legacy,fields)
    assert state['running']
    assert state['completion_id']==0
    with pytest.raises(BlockingIOError):
        submit_manual(reader,legacy,'legacy','test-session','manual-check',b'{}','amqp://unused')


def test_older_uncompleted_delivery_cannot_overwrite_newer_status(tmp_path):
    reader,legacy,fields,_=manual_fixture(tmp_path)
    state=JobState(reader.root/'shared-runtime'/'legacy'/'job.json')
    state.update(job_id='00000000-0000-0000-0000-000000000001',running=True,message='newer')
    operation=Mock()
    with pytest.raises(PermissionError):
        execute_job(reader,legacy,fields,handler=operation)
    operation.assert_not_called()
    assert state['message']=='newer'


def test_success_receipt_repairs_status_after_crash_without_repeating_work(tmp_path):
    reader,legacy,fields,_=manual_fixture(tmp_path)
    operation=Mock()
    execute_job(reader,legacy,fields,handler=operation)
    state=JobState(reader.root/'shared-runtime'/'legacy'/'job.json')
    state.update(running=True,completion_id=0)
    execute_job(reader,legacy,fields,handler=operation)
    assert operation.call_count==1
    assert not state['running'] and state['completion_id']==1
    execute_job(reader,legacy,fields,handler=operation)
    assert state['completion_id']==1


def test_unavailable_broker_does_not_reserve_manual_job(tmp_path, monkeypatch):
    from mailcheck.shared import dispatch

    reader, legacy, _, _ = manual_fixture(tmp_path)
    root = reader.root / 'shared-runtime'
    dispatches = set((root / 'dispatch').glob('*.json'))
    state = JobState(root / 'legacy' / 'job.json')
    original = state.snapshot()

    class OfflineBroker(dispatch.RabbitBroker):
        def _connect(self):
            raise ConnectionError('broker unavailable before sending')

    monkeypatch.setattr(dispatch, 'RabbitBroker', OfflineBroker)
    with pytest.raises(ConnectionError):
        submit_manual(reader, legacy, 'legacy', 'test-session', 'manual-check', b'{}', 'amqp://test')
    assert state.snapshot() == original
    assert set((root / 'dispatch').glob('*.json')) == dispatches


def test_job_started_during_broker_connect_keeps_its_status(tmp_path, monkeypatch):
    from mailcheck.shared import dispatch
    from mailcheck.shared.state import OperationLock

    reader, legacy, _, _ = manual_fixture(tmp_path)
    root = reader.root / 'shared-runtime' / 'legacy'
    job = OperationLock(root / 'job.lock')
    state = JobState(root / 'job.json')
    broker = Mock()

    def start_calendar():
        assert job.acquire(False)
        state.update(running=True, message='Collecting calendar')

    broker.process_events.side_effect = start_calendar
    monkeypatch.setattr(dispatch, 'RabbitBroker', lambda *_: broker)
    try:
        with pytest.raises(BlockingIOError):
            submit_manual(reader, legacy, 'legacy', 'test-session', 'manual-check', b'{}', 'amqp://test')
        assert state['message'] == 'Collecting calendar'
        broker.enqueue.assert_not_called()
    finally:
        if job.locked():
            job.release()


def test_lost_confirm_leaves_executing_job_success_state_intact(tmp_path, monkeypatch):
    from mailcheck.shared import dispatch

    reader, legacy, _, _ = manual_fixture(tmp_path)
    state = JobState(reader.root / 'shared-runtime' / 'legacy' / 'job.json')
    broker = Mock()

    def accepted_publish(*args, **kwargs):
        state.update(message='Check complete', ok=True)
        raise ConnectionError('confirm lost')

    broker.enqueue.side_effect = accepted_publish
    monkeypatch.setattr(dispatch, 'RabbitBroker', lambda *_: broker)
    with pytest.raises(ConnectionError):
        submit_manual(reader, legacy, 'legacy', 'test-session', 'manual-check', b'{}', 'amqp://test')
    assert state['running'] and state['ok']
    assert state['message'] == 'Check complete'


def test_calendar_job_rechecks_manual_reservation_after_acquiring_workspace_lock(tmp_path, monkeypatch):
    from mailcheck.realtime.runtime import WorkDeferred
    from mailcheck.web import app as web

    reader, legacy, fields, _ = manual_fixture(tmp_path)
    state = JobState(reader.root / 'shared-runtime' / 'legacy' / 'job.json')

    def workspace(identity):
        state.update(job_id=fields['id'], running=True, message='Manual check queued')
        return {'id': identity, 'root': None}

    reader.workspace.side_effect = workspace
    analyze = Mock()
    monkeypatch.setattr(web, '_run_calendar_analysis', analyze)
    with pytest.raises(WorkDeferred, match='manual check'):
        execute_job(reader, legacy, {'kind': 'calendar-analysis', 'workspace_id': 'legacy', 'account_id': 0})
    analyze.assert_not_called()
    assert state['message'] == 'Manual check queued'
