from unittest.mock import patch
import pytest
from mailcheck.web import app as web


def test_completion_callback_failure_cannot_permanently_lock_checks(monkeypatch):
    class ImmediateThread:
        def __init__(self,*,target,**kwargs):self.target=target
        def start(self):self.target()
    monkeypatch.setattr(web.threading,'Thread',ImmediateThread)
    def failed_finish():raise ValueError('invalid settings')
    assert web._job_lock.acquire(blocking=False)
    try:
        with patch.dict(web._job):
            web._start_job(lambda:None,failed='Job failed',verify_sourcing=False,on_finish=failed_finish)
            assert not web._job_lock.locked()
            assert web._job['running'] is False
            assert web._job['ok'] is False
    finally:
        if web._job_lock.locked():web._job_lock.release()


def test_thread_start_failure_releases_job_lock(monkeypatch):
    class FailedThread:
        def __init__(self,**kwargs):pass
        def start(self):raise RuntimeError('cannot start thread')
    monkeypatch.setattr(web.threading,'Thread',FailedThread)
    assert web._job_lock.acquire(blocking=False)
    try:
        with patch.dict(web._job):
            with pytest.raises(RuntimeError):web._start_job(lambda:None,failed='Job failed')
            assert not web._job_lock.locked()
            assert web._job['running'] is False
    finally:
        if web._job_lock.locked():web._job_lock.release()
