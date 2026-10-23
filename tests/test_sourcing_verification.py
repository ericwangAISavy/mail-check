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

    def receipt(self, key, company, stamp, *, account=None, category="application_ack", role="Engineer"):
        pk = db.upsert_message(self.conn, NormalizedMessage(account_id=account or self.account_id,
            account_label="personal", message_id=key, uid=key, folder="INBOX",
            from_addr="hr@example.test", from_name="Recruiter", subject="Application received",
            date_utc=datetime.fromisoformat(stamp), body="Received"))
        db.save_classification(self.conn, pk, Classification(category=category, company=company, role=role), "test", "1")
        return pk

    def jobs(self, day="2026-10-20"):
        base = self.snapshot()
        return self.native.append(self.conn, self.tab(), "jobs", base["revision"],
            [["Acme", "Engineer", "https://jobs.test/1"], ["Beta", "Engineer", "https://jobs.test/2"],
             ["Other", "Engineer", "https://jobs.test/3"]], work_date=day)

    def test_matching_checks_same_account_company_and_seven_chicago_days(self):
        from mailcheck import sourcing_verification as verification
        other = db.add_account(self.conn, label="other", email="other@example.test")
        self.conn.commit()
        base = self.jobs()
        self.receipt("start", "A.C.M.E.", "2026-10-20T05:00:00+00:00")
        self.receipt("end", "Acme", "2026-10-27T04:59:59+00:00")
        self.receipt("too-late", "Beta", "2026-10-27T05:00:00+00:00")
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

    def test_rechecking_preserves_checks_after_reclassification_and_reports_payment_ratio(self):
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
        self.assertEqual(result["rows"][1][3]["value"], "true")
        self.assertEqual(result["verification"]["checked"], 1)
        verification.verify_all(self.conn)
        self.assertEqual(self.snapshot()["rows"][1][3]["value"], "true")

    def test_editing_a_verified_company_or_moving_day_keeps_its_check(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        self.receipt("match", "Acme", "2026-10-20T12:00:00+00:00")
        self.conn.commit()
        first = verification.verify(self.conn, self.tab(), "first", base["revision"], "2026-10-20")
        changed = self.native.save(self.conn, self.tab(), "edit-company", [{
            "row_id": first["row_ids"][1], "column_id": first["columns"][0]["id"],
            "expected_version": first["rows"][1][0]["version"], "value": "Different company"}], work_date="2026-10-20")
        self.assertEqual(changed["rows"][1][3]["value"], "true")
        checked = self.native.save(self.conn, self.tab(), "manual-check", [{
            "row_id": changed["row_ids"][1], "column_id": changed["columns"][3]["id"],
            "expected_version": changed["rows"][1][3]["version"], "value": "true"}])
        moved = self.native.structure(self.conn, self.tab(), "move", checked["revision"], {
            "action": "move_date", "ids": [checked["row_ids"][1]], "work_date": "2026-10-21"})
        self.assertEqual(moved["rows"][1][3]["value"], "true")

    def test_checked_cells_cannot_be_cleared_by_manual_edits(self):
        base = self.jobs()
        checked = self.native.save(self.conn, self.tab(), "mark", [{
            "row_id": base["row_ids"][1], "column_id": base["columns"][3]["id"],
            "expected_version": base["rows"][1][3]["version"], "value": "true"}])
        for value in ("false", ""):
            with self.assertRaisesRegex(ValueError, "cannot be unchecked"):
                self.native.save(self.conn, self.tab(), "clear-" + value, [{
                    "row_id": checked["row_ids"][1], "column_id": checked["columns"][3]["id"],
                    "expected_version": checked["rows"][1][3]["version"], "value": value}])
        self.assertEqual(self.snapshot()["rows"][1][3]["value"], "true")

    def test_role_mismatch_is_rejected_but_missing_receipt_role_matches_company(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        self.receipt("same-company-wrong-role", "Acme", "2026-10-20T12:00:00+00:00", role="Designer")
        self.receipt("same-role-wrong-company", "Different company", "2026-10-20T12:00:00+00:00")
        self.receipt("missing-role", "Beta", "2026-10-20T12:00:00+00:00", role=None)
        self.receipt("correct", "Other", "2026-10-20T12:00:00+00:00", role="  ENGINEER  ")
        self.conn.commit()
        manual = verification.verify(self.conn, self.tab(), "roles", base["revision"], "2026-10-20")
        self.assertEqual([r[3]["value"] for r in manual["rows"][1:4]], ["false", "true", "true"])
        verification.verify_all(self.conn)
        self.assertEqual([r[3]["value"] for r in self.snapshot()["rows"][1:4]], ["false", "true", "true"])

    def test_automatic_company_only_fallback_still_requires_account_and_window(self):
        from mailcheck import sourcing_verification as verification
        self.jobs()
        other = db.add_account(self.conn, label="other", email="other@example.test")
        self.receipt("no-role", "Acme", "2026-10-21T12:00:00+00:00", role="  ")
        self.receipt("wrong-account", "Beta", "2026-10-21T12:00:00+00:00", account=other, role=None)
        self.receipt("outside-window", "Other", "2026-10-27T05:00:00+00:00", role=None)
        self.conn.commit()
        verification.verify_all(self.conn)
        self.assertEqual([r[3]["value"] for r in self.snapshot()["rows"][1:4]], ["true", "false", "false"])

    def test_missing_sheet_role_does_not_match_and_role_normalization_is_conservative(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        self.native.save(self.conn, self.tab(), "blank-role", [{
            "row_id": base["row_ids"][1], "column_id": base["columns"][1]["id"],
            "expected_version": base["rows"][1][1]["version"], "value": ""}])
        self.receipt("match", "Acme", "2026-10-20T12:00:00+00:00")
        self.conn.commit()
        verification.verify_all(self.conn)
        self.assertEqual(self.snapshot()["rows"][1][3]["value"], "false")
        self.assertEqual(verification.role_key("Senior—Software Engineer"), "senior")
        self.assertEqual(verification.role_key("C++ Engineer"), verification.role_key("C# Engineer"))
        self.assertNotEqual(verification.role_key("Senior Engineer"), verification.role_key("Engineer"))

    def test_requested_company_and_role_cleanup(self):
        from mailcheck import sourcing_verification as verification
        for company, expected in (("4A Consulting, LLC", "4a"), ("4AConsulting.LLC", "4aconsulting"), (" 4A Consulting ", "4a"), ("Cube Software", "cube"), ("Cube", "cube"), ("Cube.Software", "cube"), ("CUBE-Software", "cube")):
            with self.subTest(company=company):
                self.assertEqual(verification.company_key(company), expected)
        for suffix in (", Remote", ". II", "| Backend", "/ Platform", "\\ Contract", "- AI", "— AI", "2"):
            with self.subTest(suffix=suffix):
                self.assertEqual(verification.role_key(" Software Engineer " + suffix), "softwareengineer")
        self.assertEqual(verification.company_key("Foo & Bar, Inc."), "foo")
        self.assertEqual(verification.company_key("., Inc."), "")

    def test_cleaned_company_and_role_are_used_by_manual_and_automatic_checks(self):
        from mailcheck import sourcing_verification as verification
        self.receipt("cleaned", "Cube Software", "2026-10-20T12:00:00+00:00", role="Staff Backend Engineer")
        self.conn.commit()
        for mode, book in (("manual", self.book), ("auto", self.native.create_book(self.conn, 2))):
            tab_id = self.tab_id if mode == "manual" else self.native.create_tab(self.conn, book, self.account_id, "Applications")
            tab = self.native.owned(self.conn, tab_id, self.principal)
            base = self.native.snapshot(self.conn, tab)
            appended = self.native.append(self.conn, tab, "append-" + mode, base["revision"],
                [["Cube", "Staff Backend Engineer | Remote, US & Canada", "https://jobs.test/cleanup"]], work_date="2026-10-20")
            if mode == "manual":
                verification.verify(self.conn, tab, "cleaned-manual", appended["revision"], "2026-10-20")
            else:
                verification.verify_all(self.conn)
            result = self.native.snapshot(self.conn, tab)
            self.assertEqual(result["rows"][1][3]["value"], "true", mode)

    def test_receipt_company_survives_message_cleanup(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        pk = self.receipt("durable", "Acme", "2026-10-20T12:00:00+00:00")
        self.conn.execute("DELETE FROM messages WHERE id=?", (pk,))
        self.conn.commit()
        result = verification.verify(self.conn, self.tab(), "after-cleanup", base["revision"], "2026-10-20")
        self.assertEqual(result["rows"][1][3]["value"], "true")

    def test_seven_day_window_handles_fall_back_offset_change(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs("2026-11-01")
        self.receipt("last-minute", "Acme", "2026-11-08T05:59:59+00:00")
        self.receipt("next-midnight", "Beta", "2026-11-08T06:00:00+00:00")
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
        self.assertEqual(summary["checked"], 4)
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

    def test_automatic_window_includes_day_seven_but_excludes_day_eight(self):
        from mailcheck import sourcing_verification as verification
        self.jobs()
        self.receipt("last-minute", "Acme", "2026-10-27T04:59:59+00:00")
        self.receipt("too-late", "Beta", "2026-10-27T05:00:00+00:00")
        self.receipt("too-early", "Other", "2026-10-20T04:59:59+00:00")
        self.conn.commit()
        verification.verify_all(self.conn)
        self.assertEqual([r[3]["value"] for r in self.snapshot()["rows"][1:4]], ["true", "false", "false"])

    def test_late_confirmation_credits_receipt_day_even_across_payment_weeks(self):
        from mailcheck import sourcing_verification as verification
        self.jobs("2026-10-20")
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')", (self.account_id,))
        self.receipt("next-week", "Acme", "2026-10-26T12:00:00+00:00")
        self.conn.commit()
        verification.verify_all(self.conn)
        row = payments.report(self.conn, date(2026,10,19), admin=True)["bidders"][0]
        self.conn.commit()
        self.assertEqual(row["checked_daily"], [0] * 7)
        self.assertEqual(row["application_total"], 0)
        self.assertEqual(row["daily"], [0] * 7)
        verification.verify_all(self.conn)
        completed = payments.report(self.conn,date(2026,10,26),admin=True)["bidders"][0]
        self.conn.commit()
        self.assertEqual(completed["checked_daily"],[1,0,0,0,0,0,0])
        self.assertEqual(completed["daily"],[1,0,0,0,0,0,0])
        self.assertEqual(completed["application_total"],1)

    def test_confirmation_timestamp_is_received_time_and_refresh_repairs_it(self):
        from unittest.mock import patch
        from mailcheck import sourcing_verification as verification, sourcing_activity as activity
        from tests.web_client import sign_in_bidder
        self.jobs("2026-10-20")
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')", (self.account_id,))
        self.receipt("later", "Acme", "2026-10-21T16:00:00+00:00")
        self.receipt("earliest", "Acme", "2026-10-21T14:23:00+00:00")
        self.conn.commit()
        with patch.object(activity,'now',return_value=datetime.fromisoformat("2026-10-22T20:00:00+00:00")):
            verification.verify_all(self.conn)
        first = self.snapshot()
        self.assertEqual(first['rows'][1][3]['checked_at'], "2026-10-21T14:23:00+00:00")
        metrics = activity.report(self.conn,date(2026,10,19))
        self.assertEqual(metrics['bidders'][0]['hourly'][9],1)
        self.assertEqual(metrics['bidders'][0]['daily'],[0,0,1,0,0,0,0])
        self.conn.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-10-22T20:00:00+00:00' WHERE row_id=?",(first['row_ids'][1],))
        self.conn.commit()
        with patch.object(payments,'today',return_value=date(2026,10,22)):
            response = self.client.post('/api/payments/refresh',json={})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['from'],'2026-10-16')
        refreshed = self.snapshot()
        self.assertEqual(refreshed['rows'][1][3]['value'],'true')
        self.assertEqual(refreshed['rows'][1][3]['checked_at'],"2026-10-21T14:23:00+00:00")
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.post('/api/payments/refresh',json={}).status_code,403)

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
