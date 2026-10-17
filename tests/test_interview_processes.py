"""Organization processes use saved calendar evidence, not extracted company names."""
from datetime import datetime, timezone

import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

from tests import test_calendar_collection as calendar_fixtures
from tests.web_client import TestClient, sign_in_bidder
from mailcheck import config, db
from mailcheck.models import NormalizedMessage, Classification
from mailcheck.web.app import create_app


@pytest.mark.parametrize("participants,organizer,expected", [
    (["me@example.test", "HR@Appian.com", "dev@appian.com"], None, ["appian.com"]),
    (["me@example.test"], "Recruiter <hr@rava.com>", ["rava.com"]),
    (["hr@appian.com", "hr@rava.com"], "host@appian.com", ["appian.com", "rava.com"]),
    (["me@example.test", "bot@google.com", "bot@calendar.google.com", "bot@teams.microsoft.com", "bot@teams.live.com", "bot@teams.com", "bot@zoom.us", "bot@zoom.com"], None, []),
    (["invalid", "x@bad domain", "x@localhost", "x@-bad.com"], None, []),
    (["hr@notgoogle.com"], None, ["notgoogle.com"]),
    (["hr@jobs.appian.com"], None, ["jobs.appian.com"]),
])
def test_domain_assignment(participants, organizer, expected):
    from mailcheck import interview_processes
    result = interview_processes.organization_domains(
        participants, organizer, own_emails={"me@example.test"})
    assert result == expected


class ProcessCollectionTests(unittest.TestCase):
    setUp = calendar_fixtures.NativeCalendarTests.setUp
    source = calendar_fixtures.NativeCalendarTests.source
    collect = calendar_fixtures.NativeCalendarTests.collect

    def test_process_starts_at_first_calendar_event_and_waits_for_one_if_manual(self):
        from mailcheck import interview_processes as processes
        processes.create_process(self.conn, "Appian")
        for identity, hour in (("before", 14), ("same", 15), ("after", 16)):
            db.upsert_message(self.conn, NormalizedMessage(
                account_id=self.a, account_label="work", message_id=identity, uid=identity,
                folder="INBOX", from_addr="hr@appian.com", from_name="Recruiter",
                subject="Appian follow-up", date_utc=datetime(2026, 10, 18, hour, 30, tzinfo=timezone.utc), body="Details"))
        self.assertEqual(processes.list_processes(self.conn)[0]["milestones"], [])
        self.collect(self.source([calendar_fixtures.event("first-calendar", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])]))
        process = processes.list_processes(self.conn)[0]
        self.assertEqual([m["kind"] for m in process["milestones"]], ["event", "message", "message"])
        self.assertEqual(process["message_count"], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 3)

    def test_existing_event_and_message_html_are_cleaned_in_preview_without_changing_storage(self):
        from mailcheck import interview_processes as processes
        self.collect(self.source([calendar_fixtures.event("html-preview", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])]))
        html = '<p>Interview <strong>Details:</strong></p><p>Engineering &amp; Research</p><a href="https://example.test/meeting">Join meeting</a>'
        self.conn.execute("UPDATE interview_events SET notes=?", (html,))
        pk = db.upsert_message(self.conn, NormalizedMessage(
            account_id=self.a, account_label="work", message_id="html-preview", uid="html-preview",
            folder="INBOX", from_addr="hr@appian.com", from_name="Recruiter",
            subject="Interview details", date_utc=datetime(2026, 10, 19, tzinfo=timezone.utc), body="Saved mail"))
        db.save_classification(self.conn, pk, Classification(category="interview_invite", summary=html), "test", "1")
        milestones = processes.list_processes(self.conn)[0]["milestones"]
        self.assertEqual(len(milestones), 2)
        for milestone in milestones:
            self.assertIn("Interview Details:", milestone["summary"])
            self.assertIn("Engineering & Research", milestone["summary"])
            self.assertIn("https://example.test/meeting", milestone["summary"])
            self.assertNotIn("<p>", milestone["summary"])
        self.assertEqual(self.conn.execute("SELECT notes FROM interview_events").fetchone()[0], html)

    def test_manual_process_matches_saved_and_new_content_and_handles_ambiguity(self):
        from mailcheck import interview_processes as processes
        booking = calendar_fixtures.event("manual")
        booking["subject"] = "Interview with ACME"
        self.collect(self.source([booking]))
        pk = db.upsert_message(self.conn, NormalizedMessage(
            account_id=self.a, account_label="work", message_id="manual-mail", uid="manual-mail",
            folder="INBOX", from_addr="recruiter@agency.test", from_name="Recruiter",
            subject="Availability", date_utc=datetime(2026, 10, 19, tzinfo=timezone.utc),
            body="x" * 1500 + " Labs follow-up"))
        processes.create_process(self.conn, "Acme Labs")
        report = processes.list_processes(self.conn)
        manual = next(p for p in report if p["organization"] == "Acme Labs")
        self.assertEqual(manual["event_count"], 1)
        self.assertEqual(manual["message_count"], 1)
        self.assertEqual(manual["milestones"][1]["id"], f"message:{pk}")
        with self.assertRaises(ValueError):
            processes.create_process(self.conn, "  ACME labs  ")
        later = calendar_fixtures.event("manual-new")
        later["subject"] = "Acme next round"
        self.collect(self.source([later]))
        self.assertEqual(next(p for p in processes.list_processes(self.conn) if p["organization"] == "Acme Labs")["event_count"], 2)
        processes.set_pin(self.conn, "Acme Labs", True)
        processes.set_removed(self.conn, "Acme Labs", True)
        self.assertFalse(any(p["organization"] == "Acme Labs" for p in processes.list_processes(self.conn)))
        processes.set_removed(self.conn, "Acme Labs", False)
        processes.create_process(self.conn, "Acme Other")
        report = processes.list_processes(self.conn)
        ambiguous = next(p for p in report if p["organization"] is None)
        self.assertEqual(ambiguous["event_count"], 2)
        self.assertEqual(ambiguous["milestones"][0]["assignment_reason"], "Multiple matching manual processes")
        processes.create_process(self.conn, "Empty Company")
        self.conn.commit()
        with db.session(self.path) as conn:
            empty = next(p for p in processes.list_processes(conn) if p["organization"] == "Empty Company")
            self.assertEqual(empty["milestones"], [])
            self.assertTrue(next(p for p in processes.list_processes(conn) if p["organization"] == "Acme Labs")["pinned"])
        for name in ("", "   ", "!!!", "x" * 254):
            with self.assertRaises(ValueError):
                processes.create_process(self.conn, name)

    def test_removal_persists_through_collection_without_deleting_events_and_can_be_restored(self):
        from mailcheck import interview_processes
        booking = calendar_fixtures.event("remove", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])
        self.collect(self.source([booking]))
        interview_processes.set_removed(self.conn, "Appian.COM", True)
        self.conn.commit()
        second = calendar_fixtures.event("new-after-removal", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])
        self.collect(self.source([booking, second]))
        self.assertEqual(interview_processes.list_processes(self.conn), [])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM interview_events").fetchone()[0], 2)
        self.conn.commit()
        with db.session(self.path) as conn:
            self.assertEqual(interview_processes.list_removed(conn)[0]["organization"], "appian.com")
            interview_processes.set_removed(conn, "appian.com", False)
        self.assertEqual(len(interview_processes.list_processes(self.conn)), 1)
        with self.assertRaises(ValueError):
            interview_processes.set_removed(self.conn, "invalid domain", True)

    def test_version_18_upgrade_preserves_history_and_adds_manual_processes(self):
        from mailcheck import interview_processes as processes
        self.collect(self.source([calendar_fixtures.event("manual-upgrade")]))
        self.conn.execute("DROP TABLE interview_manual_processes")
        self.conn.execute("PRAGMA user_version=18")
        self.conn.commit()
        with db.session(self.path) as conn:
            self.assertEqual(len(processes.list_processes(conn)), 1)
            processes.create_process(conn, "Upgrade Company")
            self.assertEqual(len(processes.list_processes(conn)), 2)

    def test_version_17_upgrade_preserves_pins_and_events_and_adds_removals(self):
        from mailcheck import interview_processes
        self.collect(self.source([calendar_fixtures.event("upgrade-removal", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])]))
        interview_processes.set_pin(self.conn, "appian.com", True)
        self.conn.execute("DROP TABLE interview_process_removals")
        self.conn.execute("PRAGMA user_version=17")
        self.conn.commit()
        with db.session(self.path) as conn:
            self.assertEqual(interview_processes.list_removed(conn), [])
            process = interview_processes.list_processes(conn)[0]
            self.assertTrue(process["pinned"])
            self.assertEqual(process["event_count"], 1)
            interview_processes.set_removed(conn, "appian.com", True)
        self.assertEqual(interview_processes.list_processes(self.conn), [])

    def test_saved_email_summaries_join_the_matching_timeline(self):
        from mailcheck import interview_processes
        self.collect(self.source([calendar_fixtures.event("mail", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])]))
        def message(sender, subject, summary=None):
            pk = db.upsert_message(self.conn, NormalizedMessage(
                account_id=self.a, account_label="work", message_id=subject,
                uid=subject, folder="INBOX", from_addr=sender, from_name="Recruiter",
                subject=subject, date_utc=datetime(2026, 10, 19, 12, tzinfo=timezone.utc),
                body="Saved email preview"))
            if summary:
                db.save_classification(self.conn, pk, Classification(category="interview_invite", summary=summary), "test", "1")
            return pk
        first = message("HR@Appian.com", "Choose a time", "Recruiter asks for availability.")
        message("hr@appian.com", "Follow up")
        message("hr@unrelated.test", "Unrelated")
        report = interview_processes.list_processes(self.conn)
        self.assertEqual(len(report), 1)
        process = report[0]
        self.assertEqual(process["message_count"], 2)
        self.assertEqual([m["kind"] for m in process["milestones"]], ["event", "message", "message"])
        self.assertEqual(process["milestones"][1]["summary"], "Recruiter asks for availability.")
        self.assertIn("Saved email preview", process["milestones"][2]["summary"])
        self.assertEqual(process["milestones"][1]["id"], f"message:{first}")
        self.assertEqual(len({m["id"] for m in process["milestones"]}), 3)

    def test_pins_survive_reopening_and_unpinning(self):
        from mailcheck import interview_processes
        self.collect(self.source([calendar_fixtures.event("pin", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])]))
        interview_processes.set_pin(self.conn, "appian.com", True)
        self.conn.commit()
        with db.session(self.path) as conn:
            self.assertTrue(interview_processes.list_processes(conn)[0]["pinned"])
            interview_processes.set_pin(conn, "appian.com", False)
        self.assertFalse(interview_processes.list_processes(self.conn)[0]["pinned"])
        with self.assertRaises(ValueError):
            interview_processes.set_pin(self.conn, "not a domain", True)

    def test_version_16_upgrade_preserves_events_and_adds_pin_storage(self):
        from mailcheck import interview_processes
        self.collect(self.source([calendar_fixtures.event("upgrade", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])]))
        original = self.conn.execute("SELECT id,calendar_uid FROM interview_events").fetchone()
        self.conn.execute("DROP TABLE interview_process_pins")
        self.conn.execute("PRAGMA user_version=16")
        self.conn.commit()
        with db.session(self.path) as conn:
            preserved = conn.execute("SELECT id,calendar_uid FROM interview_events").fetchone()
            self.assertEqual(tuple(preserved), tuple(original))
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            interview_processes.set_pin(conn, "appian.com", True)
        self.assertTrue(interview_processes.list_processes(self.conn)[0]["pinned"])

    def test_new_organizations_and_calendar_updates_rebuild_the_right_process(self):
        from mailcheck import interview_processes
        first = calendar_fixtures.event("first", attendees=[{"emailAddress": {"address": "hr@appian.com"}}])
        second = calendar_fixtures.event("second", attendees=[{"emailAddress": {"address": "hr@rava.com"}}])
        self.collect(self.source([first, second]))
        self.assertEqual([p["organization"] for p in interview_processes.list_processes(self.conn)], ["appian.com", "rava.com"])
        first.update(attendees=[{"emailAddress": {"address": "hr@rava.com"}}],
                     lastModifiedDateTime="2026-10-16T15:00:00Z", isCancelled=True)
        self.collect(self.source([first]))
        processes = interview_processes.list_processes(self.conn, now=datetime(2026, 10, 16, tzinfo=timezone.utc))
        self.assertEqual(len(processes), 1)
        self.assertEqual(processes[0]["organization"], "rava.com")
        self.assertEqual(processes[0]["event_count"], 2)
        self.assertEqual(processes[0]["events"][0]["status"], "Cancelled")
        self.assertEqual(processes[0]["next_interview"]["id"], processes[0]["events"][1]["id"])

    def test_process_api_is_admin_only_and_page_is_served(self):
        self.collect(self.source([calendar_fixtures.event("api", attendees=[
            {"emailAddress": {"address": "hr@appian.com"}}])]))
        self.conn.commit()
        with patch.object(config, "db_path", return_value=self.path), patch.object(config, "config_dir", return_value=Path(self.tmp.name)):
            with TestClient(create_app()) as client:
                response = client.get("/api/interview-processes")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["processes"][0]["organization"], "appian.com")
                event_id = response.json()["processes"][0]["events"][0]["id"]
                detail = client.get(f"/api/interviews/{event_id}").json()
                self.assertIn("Other", detail["stages"])
                self.assertIn("Cancelled", detail["statuses"])
                self.assertEqual(client.post("/api/interview-processes/pin", json={"organization": "appian.com", "pinned": True}).status_code, 200)
                self.assertTrue(client.get("/api/interview-processes").json()["processes"][0]["pinned"])
                self.assertEqual(client.post("/api/interview-processes/remove", json={"organization": "appian.com", "removed": True}).status_code, 200)
                self.assertEqual(client.get("/api/interview-processes").json()["processes"], [])
                self.assertEqual(client.get("/api/interview-processes").json()["removed"][0]["organization"], "appian.com")
                self.assertEqual(client.post("/api/interview-processes/remove", json={"organization": "appian.com", "removed": False}).status_code, 200)
                self.assertEqual(client.post("/api/interview-processes", json={"name": "Manual Company"}).status_code, 200)
                self.assertTrue(any(p["organization"] == "Manual Company" and p["milestones"] == [] for p in client.get("/api/interview-processes").json()["processes"]))
                self.assertEqual(client.post("/api/interview-processes", json={"name": "manual company"}).status_code, 400)
                page = client.get("/interview-processes")
                self.assertEqual(page.status_code, 200)
                self.assertIn("no-store", page.headers["cache-control"])
                sign_in_bidder(client)
                self.assertEqual(client.post("/api/interview-processes", json={"name": "Forbidden"}).status_code, 403)
                self.assertEqual(client.get("/api/interview-processes").status_code, 403)
                self.assertEqual(client.post("/api/interview-processes/pin", json={"organization": "appian.com", "pinned": False}).status_code, 403)
                self.assertEqual(client.post("/api/interview-processes/remove", json={"organization": "appian.com", "removed": True}).status_code, 403)
                self.assertEqual(client.get("/interview-processes").status_code, 403)
                client.post("/api/auth/logout")
                self.assertEqual(client.get("/api/interview-processes").status_code, 401)

    def test_processes_reconcile_collection_and_explain_unassigned(self):
        from mailcheck import interview_processes
        def booking(identity, addresses, organizer="host@google.com", **overrides):
            value = calendar_fixtures.event(identity)
            value.update(attendees=[{"emailAddress": {"address": a}} for a in addresses],
                         organizer={"emailAddress": {"address": organizer}}, **overrides)
            return value

        first = booking("one", ["WORK@example.test", "HR@Appian.com"])
        second = booking("two", ["staff@appian.com", "work@example.test"])
        ambiguous = booking("three", ["hr@appian.com", "hr@rava.com"])
        unknown = booking("four", ["work@example.test", "bot@zoom.us"])
        self.collect(self.source([first]))
        report = interview_processes.list_processes(self.conn)
        self.assertEqual([p["organization"] for p in report], ["appian.com"])
        original_id = report[0]["events"][0]["id"]
        self.collect(self.source([first, second, ambiguous, unknown]))
        self.collect(self.source([first, second, ambiguous, unknown]))
        report = interview_processes.list_processes(self.conn, now=datetime(2026, 10, 16, tzinfo=timezone.utc))
        self.assertEqual(len(report), 2)
        assigned, unassigned = report
        self.assertEqual(assigned["organization"], "appian.com")
        self.assertEqual(assigned["event_count"], 2)
        self.assertEqual(assigned["events"][0]["id"], original_id)
        self.assertIsNotNone(assigned["next_interview"])
        self.assertIsNone(unassigned["organization"])
        self.assertEqual(unassigned["event_count"], 2)
        self.assertEqual(unassigned["events"][0]["organization_domains"], ["appian.com", "rava.com"])
        self.assertEqual(unassigned["events"][0]["assignment_reason"], "Multiple organization domains")
        self.assertEqual(unassigned["events"][1]["assignment_reason"], "No eligible organization domain")
        self.conn.execute("UPDATE accounts SET enabled=0")
        self.assertEqual(interview_processes.list_processes(self.conn), [])

@pytest.mark.parametrize("description,expected", [
    ('<p>Interview <strong>Details:</strong></p><ul><li>Position: Sr. ML Engineer</li><li>Date: Thu, Oct 1</li></ul><p><a href="https://example.test/reschedule">Reschedule</a></p><script>hidden_script()</script>', ['Interview Details:', 'Position: Sr. ML Engineer', 'Date: Thu, Oct 1', 'https://example.test/reschedule']),
    ('<strong>Engineering &amp; Research</strong><br>Room &lt;3', ['Engineering & Research', 'Room <3']),
    ('Plain notes: use x < 3.\nRecruiter <hr@example.test>', ['Plain notes: use x < 3.', 'Recruiter <hr@example.test>']),
])
def test_milestone_preview_summary_is_readable_text(description, expected):
    from mailcheck.interview_processes import _preview_summary
    result = _preview_summary(description)
    for text in expected:
        assert text in result
    for markup in ('<p>', '<strong>', '<li>', '<a ', '<script>', 'hidden_script()'):
        assert markup not in result
    assert len(result) <= 1000
