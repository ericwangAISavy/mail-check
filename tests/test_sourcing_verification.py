"""Receipt matching is isolated by account, company and Chicago work day."""
import unittest
from datetime import date, datetime
from mailcheck import db, payments
from mailcheck.models import Classification, NormalizedMessage
from tests import test_native_sourcing as fixtures


class SourcingVerificationTests(unittest.TestCase):
    setUp = fixtures.NativeSheetTests.setUp
    tab = fixtures.NativeSheetTests.tab
    snapshot = fixtures.NativeSheetTests.snapshot

    def receipt(self, key, company, stamp, *, account=None, category="application_ack"):
        pk = db.upsert_message(self.conn, NormalizedMessage(account_id=account or self.account_id,
            account_label="personal", message_id=key, uid=key, folder="INBOX",
            from_addr="hr@example.test", from_name="Recruiter", subject="Application received",
            date_utc=datetime.fromisoformat(stamp), body="Received"))
        db.save_classification(self.conn, pk, Classification(category=category, company=company), "test", "1")
        return pk

    def jobs(self, day="2026-10-20"):
        base = self.snapshot()
        return self.native.append(self.conn, self.tab(), "jobs", base["revision"],
            [["Acme", "Engineer", "https://jobs.test/1"], ["Beta", "Engineer", "https://jobs.test/2"],
             ["Other", "Engineer", "https://jobs.test/3"]], work_date=day)

    def test_matching_checks_only_same_account_company_and_local_day(self):
        from mailcheck import sourcing_verification as verification
        other = db.add_account(self.conn, label="other", email="other@example.test")
        self.conn.commit()
        base = self.jobs()
        self.receipt("start", "A.C.M.E.", "2026-10-20T05:00:00+00:00")
        self.receipt("end", "Acme", "2026-10-21T04:59:59+00:00")
        self.receipt("too-late", "Beta", "2026-10-21T05:00:00+00:00")
        self.receipt("too-early", "Beta", "2026-10-20T04:59:59+00:00")
        self.receipt("other-account", "Other", "2026-10-20T12:00:00+00:00", account=other)
        self.receipt("wrong-category", "Beta", "2026-10-20T12:00:00+00:00", category="interview_invite")
        self.conn.commit()
        result = verification.verify(self.conn, self.tab(), "verify", base["revision"], "2026-10-20")
        self.assertEqual([r[3]["value"] for r in result["rows"][1:4]], ["true", "false", "false"])
        self.assertEqual(result["verification"]["checked"], 1)
        repeated = verification.verify(self.conn, self.tab(), "verify", base["revision"], "2026-10-20")
        self.assertEqual(repeated["revision"], result["revision"])
        with self.assertRaises(FileExistsError):
            verification.verify(self.conn, self.tab(), "stale", base["revision"], "2026-10-20")
        with self.assertRaises(ValueError):
            verification.verify(self.conn, self.tab(), "undated", result["revision"], "undated")

    def test_rechecking_clears_reclassified_matches_and_reports_payment_ratio(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        pk = self.receipt("match", "Acme", "2026-10-20T12:00:00+00:00")
        self.receipt("unlisted", "Unlisted company", "2026-10-20T13:00:00+00:00")
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')", (self.account_id,))
        self.conn.commit()
        first = verification.verify(self.conn, self.tab(), "first", base["revision"], "2026-10-20")
        report = payments.report(self.conn, date(2026,10,19), admin=True)
        self.assertEqual(report["bidders"][0]["daily"][1], 2)
        self.assertEqual(report["bidders"][0]["checked_daily"][1], 1)
        self.assertEqual(report["checked_daily"][1], 1)
        db.save_classification(self.conn, pk, Classification(category="other", company="Acme"), "test", "1")
        self.conn.commit()
        result = verification.verify(self.conn, self.tab(), "again", first["revision"], "2026-10-20")
        self.assertEqual(result["rows"][1][3]["value"], "false")
        self.assertEqual(result["verification"]["checked"], 0)

    def test_editing_a_verified_company_or_moving_day_clears_its_check(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        self.receipt("match", "Acme", "2026-10-20T12:00:00+00:00")
        self.conn.commit()
        first = verification.verify(self.conn, self.tab(), "first", base["revision"], "2026-10-20")
        changed = self.native.save(self.conn, self.tab(), "edit-company", [{
            "row_id": first["row_ids"][1], "column_id": first["columns"][0]["id"],
            "expected_version": first["rows"][1][0]["version"], "value": "Different company"}], work_date="2026-10-20")
        self.assertEqual(changed["rows"][1][3]["value"], "false")
        checked = self.native.save(self.conn, self.tab(), "manual-check", [{
            "row_id": changed["row_ids"][1], "column_id": changed["columns"][3]["id"],
            "expected_version": changed["rows"][1][3]["version"], "value": "true"}])
        moved = self.native.structure(self.conn, self.tab(), "move", checked["revision"], {
            "action": "move_date", "ids": [checked["row_ids"][1]], "work_date": "2026-10-21"})
        self.assertEqual(moved["rows"][1][3]["value"], "false")

    def test_receipt_company_survives_message_cleanup(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        pk = self.receipt("durable", "Acme", "2026-10-20T12:00:00+00:00")
        self.conn.execute("DELETE FROM messages WHERE id=?", (pk,))
        self.conn.commit()
        result = verification.verify(self.conn, self.tab(), "after-cleanup", base["revision"], "2026-10-20")
        self.assertEqual(result["rows"][1][3]["value"], "true")

    def test_fall_back_day_includes_the_full_25_hour_chicago_day(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs("2026-11-01")
        self.receipt("last-minute", "Acme", "2026-11-02T05:59:59+00:00")
        self.receipt("next-midnight", "Beta", "2026-11-02T06:00:00+00:00")
        self.conn.commit()
        result = verification.verify(self.conn, self.tab(), "dst", base["revision"], "2026-11-01")
        self.assertEqual([row[3]["value"] for row in result["rows"][1:3]], ["true", "false"])

    def test_automatic_verification_covers_all_books_tabs_and_dated_rows(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        self.native.append(self.conn, self.tab(), "next-day", base["revision"], [["Beta", "Engineer", "https://jobs.test/later"]], work_date="2026-10-21")
        other = db.add_account(self.conn, label="other", email="other@example.test")
        self.conn.commit()
        second_tab = self.native.create_tab(self.conn, self.book, other, "Other")
        second_book = self.native.create_book(self.conn, 2)
        third_tab = self.native.create_tab(self.conn, second_book, self.account_id, "Third")
        for tab_id in (second_tab, third_tab):
            tab = self.native.owned(self.conn, tab_id, self.principal)
            current = self.native.snapshot(self.conn, tab)
            self.native.append(self.conn, tab, f"append-{tab_id}", current["revision"], [["Acme", "Engineer", "https://jobs.test/acme"]], work_date="2026-10-20")
        self.receipt("first", "Acme", "2026-10-20T12:00:00+00:00")
        self.receipt("later", "Beta", "2026-10-21T12:00:00+00:00")
        self.conn.commit()
        summary = verification.verify_all(self.conn)
        self.assertEqual(summary["tabs"], 3)
        self.assertEqual(summary["checked"], 3)
        self.assertEqual(self.snapshot()["rows"][1][3]["value"], "true")
        other_tab = self.native.owned(self.conn, second_tab, self.principal)
        self.assertEqual(self.native.snapshot(self.conn, other_tab)["rows"][1][3]["value"], "false")
        revisions = {row["id"]: row["revision"] for row in self.conn.execute("SELECT id,revision FROM native_tabs")}
        summary = verification.verify_all(self.conn)
        self.assertEqual(summary["changed"], 0)
        self.assertEqual(revisions, {row["id"]: row["revision"] for row in self.conn.execute("SELECT id,revision FROM native_tabs")})
        self.conn.execute("UPDATE native_tabs SET archived=1 WHERE id=?", (third_tab,))
        self.conn.commit()
        self.assertEqual(verification.verify_all(self.conn)["tabs"], 2)
        self.conn.execute("UPDATE accounts SET enabled=0 WHERE id=?", (other,))
        self.conn.commit()
        self.assertEqual(verification.verify_all(self.conn)["tabs"], 2)

    def test_check_job_verifies_after_new_receipts_before_reporting_completion(self):
        from unittest.mock import patch
        from mailcheck.web import app as web
        self.jobs()
        def work():
            self.receipt("just-fetched", "Acme", "2026-10-20T12:00:00+00:00")
            self.conn.commit()
            web._job.update(message="Mail check complete", ok=True)
        with patch.object(web.threading, "Thread") as thread, patch.object(web, "_job_lock"), patch.dict(web._job, {"completion_id": 0}):
            web._start_job(work, failed="Check failed")
            runner = thread.call_args.kwargs["target"]
            runner()
            self.assertEqual(self.snapshot()["rows"][1][3]["value"], "true")
            self.assertEqual(web._job["completion_id"], 1)
            self.assertTrue(web._job["ok"], web._job["detail"])
            self.assertIn("sourcing", web._job["message"])
