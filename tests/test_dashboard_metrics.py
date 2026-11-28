"""Dashboard metric definitions (docs/METRICS.md) on real SQLite records."""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from mailcheck import dashboard_metrics as m, db

NOW = datetime(2026, 12, 9, 18, tzinfo=timezone.utc)  # Wednesday, 12:00 Chicago
TODAY = date(2026, 12, 9)
WEEK = date(2026, 12, 7)


def at(day, hour=16):
    return datetime(day.year, day.month, day.day, hour, tzinfo=timezone.utc)


@pytest.fixture
def conn(tmp_path):
    conn = db.connect(tmp_path / "metrics.db")
    yield conn
    conn.close()


def account(conn, name="Profile"):
    return db.add_account(conn, label=name, email=f"{name.lower()}@example.test")


def receipt(conn, aid, key, kind, stamp, company="Acme", role="Engineer", refs=()):
    conn.execute("""INSERT INTO application_receipts(account_id,message_id,received_at,category,company,role,job_refs)
        VALUES(?,?,?,?,?,?,?)""", (aid, key, stamp.isoformat(), kind, company, role, json.dumps(list(refs))))


def interview(conn, aid, start, status="Scheduled", event_id=None):
    """A calendar interview for one profile; pass event_id to share an interview between profiles."""
    if event_id is None:
        event_id = conn.execute("""INSERT INTO interview_events(company,status,start_at,end_at,needs_review,created_at,updated_at)
            VALUES('Acme',?,?,?,0,'2026-01-01','2026-01-01')""", (status, start.isoformat(), (start + timedelta(hours=1)).isoformat())).lastrowid
    conn.execute("INSERT INTO interview_sources(event_id,account_id,external_message_id) VALUES(?,?,?)", (event_id, aid, f"msg-{event_id}-{aid}"))
    return event_id


def bidder(conn, name, aid, start="2026-11-01", end=None):
    conn.execute("INSERT OR IGNORE INTO bidders(name,created_at) VALUES(?,'2026-01-01')", (name,))
    who = conn.execute("SELECT id FROM bidders WHERE name=?", (name,)).fetchone()[0]
    conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date,end_date) VALUES(?,?,?,?,?)",
                 (who, aid, "p", start, end))
    return who


def sheet(conn, who, aid):
    conn.execute("INSERT OR IGNORE INTO native_books(bidder_id,title) VALUES(?,'Applications')", (who,))
    book = conn.execute("SELECT id FROM native_books WHERE bidder_id=?", (who,)).fetchone()[0]
    tab = conn.execute("INSERT INTO native_tabs(book_id,account_id,account_label,title,updated_at) VALUES(?,?,'p','p',0)", (book, aid)).lastrowid
    conn.execute("INSERT INTO native_columns(id,tab_id,position,title,kind) VALUES(?,?,0,'Link','link'),(?,?,1,'Done','check')",
                 (f"l{tab}", tab, f"c{tab}", tab))
    return tab


def link(conn, tab, key, created, *, done_at=None, confirmed=True):
    conn.execute("INSERT INTO native_rows(id,tab_id,position,work_date,created_at) VALUES(?,?,0,?,?)",
                 (key, tab, created.astimezone(m.ZONE).date().isoformat(), created.timestamp()))
    conn.execute("INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)", (key, f"l{tab}", f"https://jobs.example/{key}"))
    if done_at:
        conn.execute("INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,'true')", (key, f"c{tab}"))
        conn.execute("""INSERT INTO sourcing_check_activity(row_id,bidder_id,account_id,work_date,detected_at,source,confirmed_at)
            VALUES(?,1,NULL,NULL,?,'test',?)""", (key, done_at.isoformat(), done_at.isoformat() if confirmed else None))


# ------------------------------------------------------------------ formulas and ranges

def test_change_gives_absolute_and_percentage_and_never_divides_by_zero():
    assert m.change(15, 10) == {"absolute": 5, "percent": 50.0}
    assert m.change(4, 0) == {"absolute": 4, "percent": None}
    assert m.change(None, 3) is None and m.change(3, None) is None
    assert m.rate(0, 0) is None and m.rate(1, 4) == 0.25


def test_graph_ranges_cover_whole_reporting_weeks():
    assert m.graph_range(TODAY) == (date(2026, 10, 19), date(2026, 12, 13))
    assert m.graph_range(TODAY, 4) == (date(2026, 11, 16), date(2026, 12, 13))
    assert m.graph_range(TODAY, start=date(2026, 11, 18), end=date(2026, 11, 25)) == (date(2026, 11, 16), date(2026, 11, 29))
    for bad in (dict(weeks=5), dict(start=date(2026, 12, 2)), dict(start=date(2026, 12, 5), end=date(2026, 12, 1)),
                dict(start=date(2027, 1, 1), end=date(2027, 1, 2))):
        with pytest.raises(ValueError):
            m.graph_range(TODAY, **bad)


def test_week_before_keeps_the_local_clock_across_daylight_saving():
    instant = datetime(2026, 11, 3, 18, tzinfo=timezone.utc)  # 12:00 CST, after the change
    assert m.week_before(instant) == datetime(2026, 10, 27, 17, tzinfo=timezone.utc)  # 12:00 CDT


# ------------------------------------------------------------------ weekly summaries

def test_applications_compare_the_same_elapsed_part_of_last_week(conn):
    aid = account(conn)
    receipt(conn, aid, "old", "application_ack", at(date(2026, 11, 2)), company="Old")
    receipt(conn, aid, "a", "application_ack", at(date(2026, 12, 7)), company="A")
    receipt(conn, aid, "a-again", "application_ack", at(date(2026, 12, 7), 17), company="A")  # duplicate
    receipt(conn, aid, "b", "application_ack", at(date(2026, 12, 8)), company="B")
    receipt(conn, aid, "p1", "application_ack", at(date(2026, 12, 1)), company="P1")
    receipt(conn, aid, "p2", "application_ack", at(date(2026, 12, 5)), company="P2")  # later than this point last week
    conn.commit()
    apps = m.report(conn, now=NOW)["summaries"]["applications"]
    assert (apps["current"], apps["previous_comparable"], apps["previous_full"]) == (2, 1, 2)
    assert apps["change"] == {"absolute": 1, "percent": 100.0}
    assert apps["average_weeks"] == 4 and apps["average"] == 0.5  # zero weeks count once history exists


def test_missing_history_is_not_reported_as_zero(conn):
    aid = account(conn)
    receipt(conn, aid, "a", "application_ack", at(date(2026, 12, 8)))
    conn.commit()
    data = m.report(conn, now=NOW)
    apps = data["summaries"]["applications"]
    assert apps["previous_full"] is None and apps["change"] is None and apps["average"] is None
    assert apps["trend"][-2]["value"] is None and apps["trend"][-1] == {"week": "2026-12-07", "value": 1, "partial": True}
    points = data["profiles"]["series"][0]["points"]
    assert points["applications"][:-1] == [None] * 7 and points["applications"][-1] == 1


def test_interviews_are_calendar_events_including_upcoming_ones(conn):
    a, b, paused = account(conn, "A"), account(conn, "B"), account(conn, "Paused")
    db.set_account_enabled(conn, "Paused", False)
    receipt(conn, a, "first", "application_ack", at(date(2026, 11, 2)))
    interview(conn, a, at(date(2026, 12, 1)))
    shared = interview(conn, a, at(date(2026, 12, 8)))
    interview(conn, b, at(date(2026, 12, 8)), event_id=shared)
    interview(conn, b, at(date(2026, 12, 11)))                      # upcoming this week
    interview(conn, a, at(date(2026, 12, 9)), status="Cancelled")
    interview(conn, paused, at(date(2026, 12, 8)))                  # hidden from the calendar
    for i in range(5):                                               # invitation emails are not interviews
        receipt(conn, a, f"mail{i}", "interview_invite", at(date(2026, 12, 8)), company=f"Co{i}")
    conn.commit()
    data = m.report(conn, now=NOW)
    meetings = data["summaries"]["interviews"]
    assert (meetings["scheduled"], meetings["so_far"], meetings["previous_full"]) == (2, 1, 1)
    assert meetings["change"] == {"absolute": 1, "percent": 100.0}
    series = {p["label"]: p["points"]["interviews"][-1] for p in data["profiles"]["series"]}
    assert (series["A"], series["B"]) == (1, 2)


# ------------------------------------------------------------------ outcome rates and rejections

def test_rates_use_the_same_cohort_when_matching_is_reliable(conn):
    aid = account(conn)
    day = date(2026, 11, 16)
    # Mail has been kept since before these applications, so their replies would have been recorded.
    conn.execute("INSERT INTO messages(account_id,message_id,date_utc,fetched_at) VALUES(?,'kept','2026-11-10T00:00:00','2026-11-10T00:00:00')", (aid,))
    for company in ("Acme", "Globex", "Initech", "Umbrella"):
        receipt(conn, aid, company, "application_ack", at(day), company=company)
    for i in range(3):  # several invitation emails for one application count once
        receipt(conn, aid, f"i{i}", "interview_invite", at(day + timedelta(days=3)), company="Acme")
    receipt(conn, aid, "r1", "rejection", at(day + timedelta(days=5)), company="Acme")   # interview then rejection
    receipt(conn, aid, "r2", "rejection", at(day + timedelta(days=6)), company="Globex")
    receipt(conn, aid, "r2-again", "rejection", at(day + timedelta(days=7)), company="Globex")
    conn.commit()
    profiles = m.report(conn, now=NOW)["profiles"]
    week = [w["start"] for w in profiles["weeks"]].index("2026-11-16")
    points = profiles["series"][0]["points"]
    assert profiles["rates"]["interview_rate"]["available"] and profiles["rates"]["rejection_rate"]["available"]
    assert points["interview_rate"][week] == {"value": 0.25, "hits": 1, "base": 4}
    assert points["rejection_rate"][week] == {"value": 0.5, "hits": 2, "base": 4}
    assert points["rejections"][week] == 2


def test_rates_are_unavailable_when_most_outcome_emails_cannot_be_matched(conn):
    aid = account(conn)
    receipt(conn, aid, "a", "application_ack", at(date(2026, 11, 16)))
    for i in range(4):
        receipt(conn, aid, f"i{i}", "interview_invite", at(date(2026, 11, 18)), company=f"Stranger{i}")
    conn.commit()
    profiles = m.report(conn, now=NOW)["profiles"]
    info = profiles["rates"]["interview_rate"]
    assert not info["available"] and info["matched"] == 0 and "0 of 4" in info["reason"]
    assert set(profiles["series"][0]["points"]["interview_rate"]) == {None}


def test_applications_before_reply_history_are_outside_the_cohort(conn):
    aid = account(conn)
    receipt(conn, aid, "early", "application_ack", at(date(2026, 10, 26)), company="Early")
    receipt(conn, aid, "late", "application_ack", at(date(2026, 11, 17)), company="Late")
    receipt(conn, aid, "i", "interview_invite", at(date(2026, 11, 17), 20), company="Late")
    conn.commit()
    profiles = m.report(conn, now=NOW)["profiles"]
    starts = [w["start"] for w in profiles["weeks"]]
    points = profiles["series"][0]["points"]
    assert profiles["replies_since"] == "2026-11-17"
    assert points["interview_rate"][starts.index("2026-10-26")] is None
    assert points["rejections"][starts.index("2026-10-26")] is None  # no records, not zero
    assert points["interview_rate"][starts.index("2026-11-16")] == {"value": 1.0, "hits": 1, "base": 1}


# ------------------------------------------------------------------ workload

def test_workload_counts_each_link_once_and_completion_cannot_exceed_availability():
    lower, upper = at(date(2026, 12, 7), 6), at(date(2026, 12, 9), 6)
    life = timedelta(days=7)
    def row(created, done=None, assigned_until=None):
        expires = created + life
        closes = done + timedelta(microseconds=1) if done else expires
        if assigned_until:
            closes = min(closes, assigned_until)
        return {"created": created, "expires": expires, "done_at": done, "spans": [(created, closes)] if created < closes else []}
    rows = [
        row(lower - timedelta(days=2)),                                       # carryover, still open
        row(lower - timedelta(days=1), lower + timedelta(hours=1)),           # carryover, completed
        row(lower - timedelta(days=7, hours=-1)),                             # carryover, expires in window
        row(lower - timedelta(days=9)),                                       # expired earlier: excluded
        row(lower - timedelta(days=1), lower - timedelta(hours=1)),           # completed earlier: excluded
        row(lower + timedelta(hours=2), lower + timedelta(hours=3)),          # new, completed
        row(lower + timedelta(hours=4)),                                      # new, open
        row(lower - timedelta(days=1), assigned_until=lower + timedelta(hours=2)),  # reassigned: available, not open at end
    ]
    window = m.productivity_window(rows, lower, upper)
    assert window == {"carryover": 4, "new": 2, "available": 6, "completed": 2, "expired": 1, "remaining": 2, "completion_rate": 2 / 6}
    assert m.productivity_window([], lower, upper)["completion_rate"] is None


def test_bidder_series_workload_and_attention_come_from_sheets(conn):
    aid = account(conn)
    who = bidder(conn, "Alex", aid)
    tab = sheet(conn, who, aid)
    link(conn, tab, "old-open", NOW - timedelta(days=6))
    link(conn, tab, "new-done", NOW - timedelta(hours=3), done_at=NOW - timedelta(hours=1))
    link(conn, tab, "unconfirmed", NOW - timedelta(days=3), done_at=NOW - timedelta(days=2), confirmed=False)
    conn.commit()
    data = m.report(conn, weeks=4, now=NOW)
    daily = data["bidders"]["daily"]
    today = daily["series"][0]["points"][-1]
    assert (today["carryover"], today["new"], today["completed"], today["checked"]) == (1, 1, 1, 1)
    assert today["completion_rate"] == 0.5
    assert daily["workload"][-1] == {"new": 1, "backlog": 1, "expired": 0, "checked": 1}
    assert daily["series"][0]["points"][0] is None  # before sourcing history
    assert daily["buckets"][-1]["partial"]
    ids = {item["id"]: item["count"] for item in data["attention"]}
    assert ids["expiring_links"] == 1 and ids["backlog"] == 1 and ids["missing_confirmations"] == 1


def test_account_and_bidder_filters_scope_every_section(conn):
    mine, other = account(conn, "Mine"), account(conn, "Other")
    who = bidder(conn, "Alex", mine)
    bidder(conn, "Blair", other)
    receipt(conn, mine, "a", "application_ack", at(date(2026, 12, 8)))
    receipt(conn, other, "b", "application_ack", at(date(2026, 12, 8)), company="Other Co")
    conn.commit()
    data = m.report(conn, bidder=who, admin=False, now=NOW)
    assert [p["label"] for p in data["profiles"]["series"]] == ["Mine"]
    assert data["summaries"]["applications"]["current"] == 1
    assert [b["name"] for b in data["bidders"]["weekly"]["series"]] == ["Alex"]
    assert all(i["id"] not in {"account_connectivity", "unclassified"} for i in data["attention"])
    one = m.report(conn, account="Other", now=NOW)
    assert [p["label"] for p in one["profiles"]["series"]] == ["Other"] and one["summaries"]["applications"]["current"] == 1


def test_metrics_endpoint_returns_sections_and_validates_ranges(tmp_path):
    from unittest.mock import patch
    from mailcheck import config
    from mailcheck.web.app import create_app
    from tests.web_client import TestClient
    path = tmp_path / "mail.db"
    db.connect(path).close()
    patches = [patch.object(config, "db_path", return_value=path), patch.object(config, "config_dir", return_value=tmp_path),
               patch.object(config, "config_path", return_value=tmp_path / "config.toml")]
    for item in patches:
        item.start()
    try:
        client = TestClient(create_app())
        try:
            ok = client.get("/api/dashboard/metrics?weeks=4")
            assert ok.status_code == 200 and {"summaries", "profiles", "bidders", "attention", "payments"} <= set(ok.json())
            assert client.get("/api/dashboard/metrics?weeks=5").status_code == 400
            assert client.get("/api/dashboard/metrics?start=2026-12-05&end=2026-12-01").status_code == 400
            assert client.get("/api/dashboard/metrics?start=bad&end=2026-12-01").status_code == 400
        finally:
            client.close()
    finally:
        for item in reversed(patches):
            item.stop()
