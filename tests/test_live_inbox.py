from datetime import date
from unittest.mock import patch
from mailcheck.live_inbox import LiveInbox
from mailcheck.config import Config
from mailcheck.web import app as web
from tests.test_daily_deductions import workspace


def test_active_demand_is_shared_throttled_and_expires():
    tracker=LiveInbox()
    with patch('mailcheck.live_inbox.time.monotonic',return_value=100):
        tracker.heartbeat(1);tracker.heartbeat(2)
        assert tracker.due()
        assert tracker.reserve()
        assert not tracker.reserve()
        tracker.finish(success=True)
        assert not tracker.due()
    with patch('mailcheck.live_inbox.time.monotonic',return_value=131):
        assert tracker.active()==set()
        assert not tracker.due()
        tracker.heartbeat(2)
        assert tracker.due()
        assert tracker.snapshot(True)['last_checked_at']


def test_fast_job_revalidates_assignments_and_respects_auto_check(workspace,monkeypatch):
    conn,account=workspace
    cfg=Config();cfg.watch.auto_check=True;cfg.llm.base_url='http://model.test'
    tracker=LiveInbox();tracker.heartbeat(1)
    monkeypatch.setattr(web,'_live_inbox',tracker)
    jobs=[]
    def start(work,**kwargs):
        assert kwargs['verify_sourcing'] is False
        jobs.append((work,kwargs['on_finish']))
    monkeypatch.setattr(web,'_start_job',start)
    cfg.watch.auto_check=False
    assert not web._resume_live_inbox(cfg)
    cfg.watch.auto_check=True
    with patch.object(web.payments,'today',return_value=date(2026,11,4)):
        assert web._resume_live_inbox(cfg)
        try:
            conn.execute("UPDATE bidder_assignments SET end_date='2026-11-03'");conn.commit()
            with patch.object(web,'check_once') as check,patch.object(web.cfgmod,'load',return_value=cfg):
                jobs[0][0]()
                check.assert_not_called()
        finally:
            jobs[0][1]();web._job_lock.release()
    assert not tracker.snapshot(True)['running']


def test_live_api_heartbeat_is_explicit_and_preserves_inbox_visibility(workspace,monkeypatch):
    from tests.web_client import TestClient,sign_in_bidder
    from mailcheck.web.app import create_app
    conn,account=workspace
    cfg=Config();cfg.watch.auto_check=True;cfg.llm.base_url='http://model.test'
    tracker=LiveInbox()
    monkeypatch.setattr(web,'_live_inbox',tracker)
    monkeypatch.setattr(web,'_resume_live_inbox',lambda cfg:False)
    with TestClient(create_app()) as client,patch.object(web.cfgmod,'load',return_value=cfg),patch.object(web.payments,'today',return_value=date(2026,11,4)):
        sign_in_bidder(client)
        assert client.get('/api/triage').status_code==200
        assert tracker.active()==set()
        response=client.get('/api/triage?live=1&category=interview_invite')
        assert response.status_code==200,response.text
        assert response.json()['selected_category']=='info_request'
        assert response.json()['check_schedule']['live']['enabled'] is True
        assert tracker.active()=={1}
        assert web._live_assigned_accounts(conn)=={account}
        cfg.watch.auto_check=False
        assert client.get('/api/triage?live=1').json()['check_schedule']['live']['enabled'] is False


def test_fast_job_only_fetches_current_assigned_accounts(workspace,monkeypatch):
    from mailcheck.models import RunResult
    from datetime import datetime,timezone
    conn,account=workspace
    cfg=Config();cfg.watch.auto_check=True;cfg.llm.base_url='http://model.test'
    tracker=LiveInbox();tracker.heartbeat(1)
    monkeypatch.setattr(web,'_live_inbox',tracker)
    jobs=[]
    monkeypatch.setattr(web,'_start_job',lambda work,**kwargs:jobs.append((work,kwargs['on_finish'])))
    with patch.object(web.cfgmod,'load',return_value=cfg),patch.object(web.payments,'today',return_value=date(2026,11,4)),patch.object(web,'check_once',return_value=RunResult(started_at=datetime.now(timezone.utc))) as check:
        assert web._resume_live_inbox(cfg)
        try:
            jobs[0][0]()
            assert check.call_args.kwargs['account_ids']=={account}
            assert check.call_args.kwargs['recent_since'].tzinfo is not None
        finally:jobs[0][1]();web._job_lock.release()


def test_live_status_reports_failed_attempt_then_success():
    tracker=LiveInbox();tracker.heartbeat(1)
    assert tracker.snapshot(True)['last_check_ok'] is None
    assert tracker.reserve()
    assert tracker.snapshot(True)['last_attempt_at']
    tracker.finish(False)
    assert tracker.snapshot(True)['last_check_ok'] is False
    with patch('mailcheck.live_inbox.time.monotonic',return_value=10**12):
        tracker.heartbeat(1)
        assert tracker.reserve()
        tracker.finish(True)
        assert tracker.snapshot(True)['last_check_ok'] is True


def test_disabled_live_status_explains_missing_assignments(workspace,monkeypatch):
    from tests.web_client import TestClient,sign_in_bidder
    conn,account=workspace
    cfg=Config();cfg.watch.auto_check=True;cfg.llm.base_url='http://model.test'
    monkeypatch.setattr(web,'_live_inbox',LiveInbox())
    monkeypatch.setattr(web,'_resume_live_inbox',lambda cfg:False)
    with TestClient(web.create_app()) as client,patch.object(web.cfgmod,'load',return_value=cfg):
        sign_in_bidder(client)
        conn.execute('DELETE FROM bidder_assignments');conn.commit()
        live=client.get('/api/triage?live=1').json()['check_schedule']['live']
        assert live['enabled'] is False
        assert live['disabled_reason']=='No active assigned mailboxes.'
