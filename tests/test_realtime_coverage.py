"""Scheduled and live Inbox checks leave fresh real-time accounts to real-time collection."""
import time
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mailcheck import db, mail_checkpoints, realtime_coverage as coverage
from mailcheck.config import Config
from mailcheck.live_inbox import LiveInbox
from mailcheck.realtime import settings as realtime_settings, storage as realtime_storage
from mailcheck.web import app as web
from tests.test_daily_deductions import workspace  # noqa: F401 - fixture


@pytest.fixture
def background_service(monkeypatch):
    configured = realtime_settings.Settings(amqp_url="amqp://broker.test/")
    monkeypatch.setattr(realtime_settings.Settings, "from_env", classmethod(lambda cls: configured))


def live(conn, account_id, seconds_ago):
    realtime_storage.set_account(conn, account_id, True)
    realtime_storage.set_status(conn, account_id, last_sync=time.time() - seconds_ago)


def test_only_recently_synced_opted_in_accounts_are_covered(workspace, background_service):
    conn, inbox = workspace
    fresh = db.add_account(conn, label="fresh", email="fresh@example.test")
    stale = db.add_account(conn, label="stale", email="stale@example.test")
    paused = db.add_account(conn, label="paused", email="paused@example.test")
    never = db.add_account(conn, label="never", email="never@example.test")
    live(conn, fresh, 60)
    live(conn, stale, coverage.FRESH_SECONDS + 60)  # background service stopped
    live(conn, paused, 60)
    conn.execute("UPDATE accounts SET enabled=0 WHERE id=?", (paused,))
    realtime_storage.set_account(conn, never, True)  # opted in, never synced
    conn.commit()
    assert coverage.covered_accounts(conn) == {fresh}


def test_nothing_is_covered_without_the_background_service(workspace):
    conn, inbox = workspace
    live(conn, inbox, 30)
    assert coverage.covered_accounts(conn) == set()


def test_full_checks_slow_to_housekeeping_only_when_every_account_is_covered(workspace, background_service):
    conn, inbox = workspace
    cfg = Config()
    cfg.watch.interval_minutes = 2
    other = db.add_account(conn, label="other", email="other@example.test")
    live(conn, inbox, 30)
    assert coverage.interval_minutes(conn, cfg) == 2  # "other" still needs scheduled checks
    live(conn, other, 30)
    assert coverage.interval_minutes(conn, cfg) == coverage.HOUSEKEEPING_MINUTES
    cfg.watch.interval_minutes = 60
    assert coverage.interval_minutes(conn, cfg) == 60  # never shortens a longer choice


def test_a_housekeeping_wait_shortens_when_coverage_lapses_but_never_lengthens():
    now = 1000.0
    assert coverage.tightened(now + 30 * 60, 2, now=now) == now + 120
    assert coverage.tightened(now + 60, 2, now=now) == now + 60
    assert coverage.tightened(None, 2, now=now) is None


def test_scheduled_check_skips_covered_accounts_but_check_now_does_not(workspace, background_service, monkeypatch):
    conn, inbox = workspace
    other = db.add_account(conn, label="other", email="other@example.test")
    live(conn, inbox, 30)
    conn.commit()
    calls = []
    monkeypatch.setattr(web, "check_once", lambda conn, cfg, **kwargs: calls.append(("mail", kwargs["account_ids"]))
                        or SimpleNamespace(fetched=0, classified=0, from_cache=0, prefiltered=0, pruned=0,
                                           retryable=0, errors=[], interview_changes=[]))
    monkeypatch.setattr(web.interviews, "collect_calendar_events",
                        lambda conn, cfg, **kwargs: calls.append(("calendar", kwargs["account_ids"])) or {"changes": [], "errors": []})
    monkeypatch.setattr(web, "_start_job", lambda work, **kwargs: work())
    web._run_check(web.CheckBody(), include_calendar=True, scheduled=True)
    assert calls == [("calendar", {other}), ("mail", {other})]
    assert "1 kept current by real-time collection" in web._job["message"]
    calls.clear()
    web._run_check(web.CheckBody())
    assert calls == [("mail", None)]


def test_live_inbox_polls_only_accounts_real_time_is_not_covering(workspace, background_service, monkeypatch):
    conn, inbox = workspace
    cfg = Config(); cfg.watch.auto_check = True; cfg.llm.base_url = "http://model.test"
    tracker = LiveInbox(); tracker.heartbeat(1)
    monkeypatch.setattr(web, "_live_inbox", tracker)
    started = []
    monkeypatch.setattr(web, "_start_job", lambda work, **kwargs: started.append(work))
    with patch.object(web.payments, "today", return_value=date(2026, 11, 4)):
        assert web._live_assigned_accounts(conn) == {inbox}
        live(conn, inbox, 30)
        conn.commit()
        assert web._live_assigned_accounts(conn) == set()
        # Nothing to poll: handled as a healthy check, without starting a job.
        assert web._resume_live_inbox(cfg)
    assert started == []
    snapshot = tracker.snapshot(True)
    assert snapshot["last_check_ok"] is True and not snapshot["running"]
    assert not web._job_lock.locked()


def test_inbox_freshness_is_its_least_recently_collected_account(workspace, background_service):
    conn, inbox = workspace
    other = db.add_account(conn, label="other", email="other@example.test")
    now = datetime.now(timezone.utc)
    mail_checkpoints.record(conn, db.get_account(conn, "inbox"), now - timedelta(minutes=30))
    live(conn, inbox, 60)  # real-time: inbox is 1 minute fresh
    mail_checkpoints.record(conn, db.get_account(conn, "other"), now - timedelta(minutes=10))
    conn.commit()
    accounts = [db.get_account(conn, "inbox"), db.get_account(conn, "other")]
    # "other" is not covered: a live poll 20 seconds ago refreshed it.
    polled = (now - timedelta(seconds=20)).isoformat()
    stamp = datetime.fromisoformat(web._inbox_updated_at(accounts, polled))
    assert now - timedelta(seconds=70) < stamp < now - timedelta(seconds=50)  # inbox's real-time sync
    # Without the live poll, "other" was last collected 10 minutes ago.
    stamp = datetime.fromisoformat(web._inbox_updated_at(accounts, None))
    assert abs((now - timedelta(minutes=10) - stamp).total_seconds()) < 2
    # An assigned mailbox that nothing has collected yet means no freshness yet;
    # a live poll counts, because it collects that mailbox's new mail.
    db.add_account(conn, label="never", email="never@example.test")
    conn.commit()
    everything = [*accounts, db.get_account(conn, "never")]
    assert web._inbox_updated_at(everything, None) is None
    assert web._inbox_updated_at(everything, polled) is not None


def test_status_reports_the_latest_mail_collection(workspace, background_service):
    from tests.web_client import TestClient
    conn, inbox = workspace
    with TestClient(web.create_app()) as client:
        assert client.get("/api/status").json()["updated_at"] is None
        mail_checkpoints.record(conn, db.get_account(conn, "inbox"), datetime.now(timezone.utc) - timedelta(minutes=5))
        live(conn, inbox, 30)
        conn.commit()
        stamp = datetime.fromisoformat(client.get("/api/status").json()["updated_at"])
        assert datetime.now(timezone.utc) - stamp < timedelta(seconds=40)


def test_scheduler_still_starts_a_due_check_on_a_coverage_refresh_tick(monkeypatch):
    cfg = Config(); cfg.watch.auto_check = True
    ran = []
    monkeypatch.setattr(web.cfgmod, "load", lambda: cfg)
    ticks = iter([None])
    monkeypatch.setattr(web.time, "sleep", lambda seconds: next(ticks))  # StopIteration ends the loop
    monkeypatch.setattr(web, "_check_interval_minutes", lambda cfg: 2)
    monkeypatch.setattr(web, "_state", lambda: {"has_accounts": True})
    monkeypatch.setattr(web, "_reschedule", lambda cfg=None: None)
    monkeypatch.setattr(web, "_run_check", lambda body, **kwargs: ran.append(kwargs))
    monkeypatch.setattr(web, "_job_lock", SimpleNamespace(acquire=lambda blocking=False: True))
    monkeypatch.setitem(web._job, "running", False)
    monkeypatch.setitem(web._sched, "next_due", 0)
    with pytest.raises(StopIteration):
        web._scheduler()
    assert ran == [{"include_calendar": True, "scheduled": True}]


def test_an_account_becoming_covered_mid_check_is_not_a_failed_live_check(workspace, background_service, monkeypatch):
    conn, inbox = workspace
    cfg = Config(); cfg.watch.auto_check = True; cfg.llm.base_url = "http://model.test"
    tracker = LiveInbox(); tracker.heartbeat(1)
    monkeypatch.setattr(web, "_live_inbox", tracker)
    jobs = []
    monkeypatch.setattr(web, "_start_job", lambda work, **kwargs: jobs.append((work, kwargs["on_finish"])))
    with patch.object(web.payments, "today", return_value=date(2026, 11, 4)), patch.object(web.cfgmod, "load", return_value=cfg), \
         patch.object(web, "check_once") as check:
        assert web._resume_live_inbox(cfg)
        live(conn, inbox, 30)  # real-time catches up before the job runs
        conn.commit()
        try:
            jobs[0][0]()
        finally:
            jobs[0][1](); web._job_lock.release()
        check.assert_not_called()
    assert tracker.snapshot(True)["last_check_ok"] is True
    assert web._job["message"] == "Bidder Inbox accounts are already current."


def test_calendar_success_never_marks_mail_as_freshly_collected(tmp_path):
    from mailcheck import db
    from mailcheck.realtime import storage
    from mailcheck.realtime.runtime import Runtime
    import inspect
    source = inspect.getsource(Runtime.collect_calendar)
    # Coverage treats last_sync as "mail collected"; calendar must leave it alone.
    code = [line.split("#", 1)[0] for line in source.split("collect_calendar_events", 1)[1].splitlines()]
    assert not any("last_sync" in line for line in code)
    path = tmp_path / "status.db"
    with db.session(path) as conn:
        account = db.add_account(conn, label="a", email="a@example.test")
        storage.set_account(conn, account, True)
        storage.set_status(conn, account, error="Mail collection unavailable; retrying.", last_sync=100.0)
        storage.set_status(conn, account)  # what a calendar success now records
        row = conn.execute("SELECT last_sync,last_error FROM realtime_accounts WHERE account_id=?", (account,)).fetchone()
    assert row[0] == 100.0 and row[1] == ""
