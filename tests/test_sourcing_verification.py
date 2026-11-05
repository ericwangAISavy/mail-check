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

    def test_verified_row_rejects_value_and_format_edits_but_can_move_day(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        self.receipt("match", "Acme", "2026-10-20T12:00:00+00:00")
        self.conn.commit()
        first = verification.verify(self.conn, self.tab(), "first", base["revision"], "2026-10-20")
        for index, column in enumerate(first["columns"]):
            for field in ({"value": "Different company"} if column["kind"] != "check" else {"value": "true"}, {"style": {"bold": True}}):
                # Resaving the existing check value is harmless; all changed cells are locked.
                if field == {"value": "true"}:
                    continue
                with self.subTest(column=column["kind"], field=field):
                    with self.assertRaisesRegex(ValueError, "Checked rows cannot be edited"):
                        self.native.save(self.conn, self.tab(), "edit-" + str(index) + str(field), [{
                            "row_id": first["row_ids"][1], "column_id": column["id"],
                            "expected_version": first["rows"][1][index]["version"], **field}])
        after = self.snapshot()
        self.assertEqual(after["rows"], first["rows"])
        self.assertEqual(after["revision"], first["revision"])
        moved = self.native.structure(self.conn, self.tab(), "move", first["revision"], {
            "action": "move_date", "ids": [first["row_ids"][1]], "work_date": "2026-10-21"})
        self.assertEqual(moved["rows"][1][3]["value"], "true")

    def test_initial_save_can_check_row_before_its_job_details(self):
        base = self.snapshot()
        row_id = base["row_ids"][1]
        changes = [{"row_id": row_id, "column_id": base["columns"][index]["id"],
                    "expected_version": 0, "value": value}
                   for index, value in [(3, "true"), (0, "Acme"), (1, "Engineer"),
                                        (2, "https://jobs.test/initial")]]
        saved = self.native.save(self.conn, self.tab(), "initial-checked-paste", changes)
        self.assertEqual([cell["value"] for cell in saved["rows"][1]],
                         ["Acme", "Engineer", "https://jobs.test/initial", "true"])
        with self.assertRaisesRegex(ValueError, "Checked rows cannot be edited"):
            self.native.save(self.conn, self.tab(), "mixed-checked-edit", [
                {"row_id": saved["row_ids"][2], "column_id": saved["columns"][0]["id"],
                 "expected_version": 0, "value": "Must roll back"},
                {"row_id": row_id, "column_id": saved["columns"][0]["id"],
                 "expected_version": saved["rows"][1][0]["version"], "value": "Changed"}])
        self.assertEqual(self.snapshot()["rows"], saved["rows"])

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
        self.assertEqual(verification.role_key("Senior—Software Engineer"), "senior software engineer")
        self.assertNotEqual(verification.role_key("C++ Engineer"), verification.role_key("C# Engineer"))
        self.assertNotEqual(verification.role_key("Senior Engineer"), verification.role_key("Engineer"))

    def test_company_and_role_cleanup_preserves_identity(self):
        from mailcheck import sourcing_verification as verification
        for company, expected in (("4A Consulting, LLC", "4a consulting"), ("4AConsulting.LLC", "4aconsulting"), ("Cube Software", "cube software"), ("Cube.Software", "cube software"), ("CUBE-Software", "cube software"), ("A.C.M.E.", "acme")):
            with self.subTest(company=company):
                self.assertEqual(verification.company_key(company), expected)
        self.assertNotEqual(verification.company_key("First National"), verification.company_key("First Horizon"))
        self.assertNotEqual(verification.role_key("Engineer 2"), verification.role_key("Engineer 3"))
        self.assertNotEqual(verification.role_key("Engineer II"), verification.role_key("Engineer III"))
        self.assertEqual(verification.role_key("Sr. Engineer"), verification.role_key("Senior Engineer"))
        self.assertEqual(verification.role_key("Engineer | Remote, US"), "engineer")
        self.assertNotEqual(verification.role_key("Engineer, Remote Sensing"), "engineer")
        self.assertNotEqual(verification.role_key("Engineer | Hybrid Cloud"), "engineer")
        self.assertEqual(verification.company_key("Foo & Bar, Inc."), "foo bar")
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
                [["Cube Software", "Staff Backend Engineer | Remote, US & Canada", f"https://jobs.test/cleanup/{mode}"]], work_date="2026-10-20")
            if mode == "manual":
                verification.verify(self.conn, tab, "cleaned-manual", appended["revision"], "2026-10-20")
            else:
                verification.verify_all(self.conn)
            result = self.native.snapshot(self.conn, tab)
            self.assertEqual(result["rows"][1][3]["value"], "true" if mode == "manual" else "false", mode)

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

    def test_automatic_verification_does_not_reuse_receipts_across_books_and_dates(self):
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
        self.receipt("other-account", "Acme", "2026-10-20T12:00:00+00:00", account=other)
        self.conn.commit()
        summary = verification.verify_all(self.conn)
        self.assertEqual(summary["tabs"], 3)
        self.assertEqual(summary["checked"], 1)
        self.assertEqual(self.snapshot()["rows"][1][3]["value"], "false")
        other_tab = self.native.owned(self.conn, second_tab, self.principal)
        self.assertEqual(self.native.snapshot(self.conn, other_tab)["rows"][1][3]["value"], "true")
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

    def test_normal_refresh_preserves_existing_confirmation_timestamp(self):
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
        self.assertEqual(response.json()['from'],'2026-10-19')
        refreshed = self.snapshot()
        self.assertEqual(refreshed['rows'][1][3]['value'],'true')
        self.assertEqual(refreshed['rows'][1][3]['checked_at'],"2026-10-22T20:00:00+00:00")
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

    def test_payment_page_reconciles_links_registered_after_receipts(self):
        self.receipt('already-received', 'Acme', '2026-10-21T14:00:00+00:00')
        self.jobs('2026-10-20')
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')", (self.account_id,))
        self.conn.commit()
        runs = self.conn.execute('SELECT COUNT(*) FROM sourcing_activity_runs').fetchone()[0]
        response = self.client.get('/api/payments?week=2026-10-19')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM sourcing_activity_runs').fetchone()[0], runs)
        bidder = response.json()['bidders'][0]
        self.assertEqual(bidder['daily'][2], 1)
        self.assertEqual(bidder['checked_daily'][2], 1)
        self.assertEqual(self.snapshot()['rows'][1][3]['value'], 'true')

    def test_bounded_refresh_includes_older_links_with_receipts_in_window(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-14')
        self.receipt('last-valid-day', 'Acme', '2026-10-20T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn, refresh_since=date(2026,10,20), refresh_until=date(2026,10,26))
        self.assertEqual(self.snapshot()['rows'][1][3]['value'], 'true')

    def test_bounded_refresh_keeps_earliest_match_before_reporting_window(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-14')
        self.receipt('earliest', 'Acme', '2026-10-15T14:00:00+00:00')
        self.receipt('duplicate', 'Acme', '2026-10-20T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn, refresh_since=date(2026,10,20), refresh_until=date(2026,10,26))
        self.assertEqual(self.snapshot()['rows'][1][3]['checked_at'], '2026-10-15T14:00:00+00:00')

    def test_selected_week_refresh_and_rebuild_preserve_manual_and_adjacent_week(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        target = self.receipt('target', 'Acme', '2026-10-21T14:00:00+00:00')
        outside = self.receipt('outside', 'Beta', '2026-10-27T04:00:00+00:00')
        base = self.snapshot()
        self.native.save(self.conn, self.tab(), 'manual-other', [{
            'row_id': base['row_ids'][3], 'column_id': base['columns'][3]['id'],
            'expected_version': base['rows'][3][3]['version'], 'value': 'true'}])
        self.conn.commit()
        verification.verify_all(self.conn)
        db.save_classification(self.conn, target, Classification(category='other', company='Acme'), 'test', '1')
        db.save_classification(self.conn, outside, Classification(category='other', company='Beta'), 'test', '1')
        self.conn.commit()
        response = self.client.post('/api/payments/refresh', json={'week':'2026-10-21', 'mode':'refresh'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual((response.json()['from'], response.json()['through']), ('2026-10-19', '2026-10-25'))
        self.assertEqual(self.snapshot()['rows'][1][3]['value'], 'true')
        response = self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(response.status_code, 200, response.text)
        after = self.snapshot()
        self.assertEqual([r[3]['value'] for r in after['rows'][1:4]], ['true', 'true', 'true'])
        self.assertEqual(after['rows'][1][3]['checked_at'], '2026-10-21T14:00:00+00:00')
        again = self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(again.json()['changed'], 0)

    def test_manual_check_remains_manual_after_matching_and_rebuild(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        base = self.snapshot()
        self.native.save(self.conn, self.tab(), 'manual-acme', [{
            'row_id': base['row_ids'][1], 'column_id': base['columns'][3]['id'],
            'expected_version': base['rows'][1][3]['version'], 'value': 'true'}])
        pk = self.receipt('manual-match', 'Acme', '2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn)
        event = self.conn.execute('SELECT source FROM sourcing_check_activity WHERE row_id=?', (base['row_ids'][1],)).fetchone()
        self.assertEqual(event['source'], 'manual-edit')
        db.save_classification(self.conn, pk, Classification(category='other', company='Acme'), 'test', '1')
        self.conn.commit()
        self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(self.snapshot()['rows'][1][3]['value'], 'true')

    def test_week_refresh_leaves_other_week_receipt_metadata_untouched(self):
        self.receipt('outside-metadata', 'Acme', '2026-10-28T14:00:00+00:00')
        self.conn.execute("UPDATE application_receipts SET company='Retained outside metadata' WHERE message_id='outside-metadata'")
        self.conn.commit()
        response = self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(response.status_code, 200, response.text)
        receipt = self.conn.execute("SELECT company FROM application_receipts WHERE message_id='outside-metadata'").fetchone()
        self.assertEqual(receipt['company'], 'Retained outside metadata')

    def test_week_rebuild_includes_archived_sheets_in_payment_counts(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        pk = self.receipt('archived', 'Acme', '2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn)
        self.conn.execute('UPDATE native_tabs SET archived=1 WHERE id=?', (self.tab_id,))
        db.save_classification(self.conn, pk, Classification(category='other', company='Acme'), 'test', '1')
        self.conn.commit()
        response = self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(response.status_code, 200, response.text)
        cell = self.conn.execute('SELECT c.value FROM native_cells c JOIN native_columns col ON col.id=c.column_id WHERE c.row_id=? AND col.kind=\'check\'', (self.snapshot()['row_ids'][1],)).fetchone()
        self.assertEqual(cell['value'], 'true')

    def test_week_rebuild_preserves_saved_payment_and_rejects_invalid_scope(self):
        self.conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(1,'2026-10-19',42,12345,'2026-10-26T12:00:00+00:00','Saved payment')")
        self.conn.commit()
        before = dict(self.conn.execute('SELECT * FROM bidder_payments').fetchone())
        response = self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(dict(self.conn.execute('SELECT * FROM bidder_payments').fetchone()), before)
        for body in ({'week':'invalid'}, {'week':'1900-01-01'}, {'mode':'delete'}):
            self.assertEqual(self.client.post('/api/payments/refresh', json=body).status_code, 422)

    def test_week_rebuild_preserves_confirmation_even_if_row_became_undated(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        pk = self.receipt('undated-stale', 'Acme', '2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn)
        row_id = self.snapshot()['row_ids'][1]
        self.conn.execute('UPDATE native_rows SET work_date=NULL WHERE id=?', (row_id,))
        db.save_classification(self.conn, pk, Classification(category='other', company='Acme'), 'test', '1')
        self.conn.commit()
        response = self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.assertEqual(response.status_code, 200, response.text)
        event = self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?', (row_id,)).fetchone()
        self.assertEqual(event['confirmed_at'], '2026-10-21T14:00:00+00:00')
        self.assertEqual(event['source'], 'confirmation')

    def test_week_rebuild_does_not_break_future_check_run_activity_cursor(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')", (self.account_id,))
        pk = self.receipt('before-rebuild', 'Acme', '2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn)
        db.save_classification(self.conn, pk, Classification(category='other', company='Acme'), 'test', '1')
        self.conn.commit()
        self.client.post('/api/payments/refresh', json={'week':'2026-10-19', 'mode':'rebuild'})
        self.receipt('after-rebuild', 'Beta', '2026-10-21T15:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn)
        sample = self.conn.execute('SELECT new_checks FROM sourcing_activity_samples WHERE bidder_id=1 ORDER BY run_id DESC LIMIT 1').fetchone()
        self.assertEqual(sample['new_checks'], 1)

    def test_scoped_query_preserves_confirmation_at_last_microsecond_of_week(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-25')
        self.receipt('last-microsecond', 'Acme', '2026-10-26T04:59:59.999999+00:00')
        self.conn.commit()
        verification.verify_all(self.conn, refresh_since=date(2026,10,19), refresh_until=date(2026,10,25), week_only=True, sample=False)
        cell = self.snapshot()['rows'][1][3]
        self.assertEqual(cell['value'], 'true')
        self.assertEqual(cell['checked_at'], '2026-10-26T04:59:59.999999+00:00')

    def test_automatic_check_includes_pre_registered_future_rows(self):
        from unittest.mock import patch
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-11-20')
        self.receipt('early-acme','Acme','2026-10-20T15:00:00+00:00')
        self.conn.commit()
        with patch.object(payments,'today',return_value=date(2026,10,20)):
            verification.verify_all(self.conn)
        row=self.snapshot()['rows'][1][3]
        self.assertEqual(row['value'],'true')
        self.assertEqual(row['checked_at'],'2026-10-20T15:00:00+00:00')
        self.assertEqual(self.snapshot()['row_dates'][1],'2026-11-20')

    def test_selected_week_refresh_includes_future_pre_registered_rows(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-11-20')
        self.receipt('early-acme','Acme','2026-10-20T15:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn,refresh_since=date(2026,10,19),refresh_until=date(2026,10,25),week_only=True,sample=False)
        self.assertEqual(self.snapshot()['rows'][1][3]['value'],'true')
        self.assertEqual(self.snapshot()['rows'][1][3]['checked_at'],'2026-10-20T15:00:00+00:00')

    def test_manual_check_from_today_also_checks_future_rows(self):
        from unittest.mock import patch
        from mailcheck import sourcing_verification as verification
        base=self.jobs('2026-10-21')
        self.receipt('early-acme','Acme','2026-10-20T15:00:00+00:00')
        self.conn.commit()
        with patch.object(payments,'today',return_value=date(2026,10,20)):
            verification.verify(self.conn,self.tab(),'early-manual',base['revision'],'2026-10-20')
        self.assertEqual(self.snapshot()['rows'][1][3]['value'],'true')

    def test_manual_check_on_future_date_finds_early_confirmation(self):
        from unittest.mock import patch
        from mailcheck import sourcing_verification as verification
        base=self.jobs('2026-11-20')
        self.receipt('early-acme','Acme','2026-10-20T15:00:00+00:00')
        self.conn.commit()
        with patch.object(payments,'today',return_value=date(2026,10,20)):
            verification.verify(self.conn,self.tab(),'early-future',base['revision'],'2026-11-20')
        self.assertEqual(self.snapshot()['rows'][1][3]['value'],'true')

    def test_future_completion_is_counted_on_actual_receipt_day(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-11-20')
        self.receipt('early-acme','Acme','2026-10-20T15:00:00+00:00')
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')",(self.account_id,))
        self.conn.commit()
        verification.verify_all(self.conn,refresh_since=date(2026,10,19),refresh_until=date(2026,10,25),week_only=True,sample=False)
        table=payments.report(self.conn,date(2026,10,19))
        self.assertEqual(table['bidders'][0]['checked_daily'][1],1)
        self.assertEqual(table['bidders'][0]['daily'][1],1)

    def test_future_rows_do_not_match_wrong_account_role_or_old_receipts(self):
        from unittest.mock import patch
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-11-20')
        other=db.add_account(self.conn,label='wrong',email='wrong@example.test')
        self.receipt('wrong-account','Acme','2026-10-20T15:00:00+00:00',account=other)
        self.receipt('wrong-role','Beta','2026-10-20T15:00:00+00:00',role='Accountant')
        self.receipt('old-receipt','Other','2026-09-20T15:00:00+00:00')
        self.conn.commit()
        with patch.object(payments,'today',return_value=date(2026,10,20)):
            verification.verify_all(self.conn)
        self.assertEqual([r[3]['value'] for r in self.snapshot()['rows'][1:4]],['false','false','false'])

    def test_company_only_reply_does_not_check_multiple_roles(self):
        from mailcheck import sourcing_verification as verification
        base = self.snapshot()
        jobs = self.native.append(self.conn, self.tab(), 'ambiguous-nscale', base['revision'], [
            ['Nscale', 'Developer Experience Engineer', 'https://jobs.test/nscale/1'],
            ['Nscale', 'Senior Developer Experience Engineer', 'https://jobs.test/nscale/2'],
        ], work_date='2026-10-20')
        self.receipt('company-only', 'Nscale', '2026-10-20T12:00:00Z', role=None)
        self.conn.commit()
        checked = verification.verify(self.conn, self.tab(), 'manual-ambiguous', jobs['revision'], '2026-10-20')
        self.assertEqual([row[3]['value'] for row in checked['rows'][1:3]], ['false', 'false'])
        self.assertEqual(checked['verification']['unmatched_count'],2)
        self.assertTrue(all('2 eligible jobs' in item['reason'] for item in checked['verification']['unmatched']))
        verification.verify_all(self.conn, sample=False)
        self.assertEqual([row[3]['value'] for row in self.snapshot()['rows'][1:3]], ['false', 'false'])
        self.receipt('specific-role', 'Nscale', '2026-10-20T12:01:00Z', role='Developer Experience Engineer')
        self.conn.commit()
        verification.verify_all(self.conn, sample=False)
        self.assertEqual([row[3]['value'] for row in self.snapshot()['rows'][1:3]], ['true', 'false'])

    def test_manual_check_sees_competing_jobs_in_another_bidder_tab(self):
        from mailcheck import sourcing_verification as verification
        base = self.jobs()
        other_book = self.native.create_book(self.conn, 2)
        other_tab = self.native.create_tab(self.conn, other_book, self.account_id, 'Shared')
        tab = self.native.owned(self.conn, other_tab, self.principal)
        snap = self.native.snapshot(self.conn, tab)
        self.native.append(self.conn, tab, 'competing-job', snap['revision'], [['Acme', 'Engineer', 'https://jobs.test/competitor']], work_date='2026-10-20')
        self.receipt('one-receipt', 'Acme', '2026-10-20T12:00:00Z')
        self.conn.commit()
        checked = verification.verify(self.conn, self.tab(), 'cross-tab-check', base['revision'], '2026-10-20')
        self.assertEqual(checked['rows'][1][3]['value'], 'false')

    def test_reserved_receipt_is_not_reused_and_unchanged_refresh_has_no_writes(self):
        from mailcheck import sourcing_verification as verification
        self.jobs()
        self.receipt('reserved', 'Acme', '2026-10-20T12:00:00Z')
        self.conn.commit()
        verification.verify_all(self.conn, sample=False)
        snap = self.snapshot()
        self.native.append(self.conn, self.tab(), 'another-acme', snap['revision'], [['Acme', 'Engineer', 'https://jobs.test/another']], work_date='2026-10-20')
        verification.verify_all(self.conn, sample=False)
        rows = self.snapshot()['rows']
        self.assertEqual(rows[1][3]['value'], 'true')
        self.assertEqual(rows[4][3]['value'], 'false')
        self.conn.commit()
        before = self.conn.total_changes
        verification.verify_all(self.conn, sample=False)
        self.assertEqual(self.conn.total_changes, before)

    def test_scoped_rebuild_never_reassigns_a_saved_receipt(self):
        from mailcheck import sourcing_verification as verification
        self.jobs()
        pk = self.receipt('corrected-company', 'Acme', '2026-10-20T12:00:00Z')
        self.conn.commit()
        verification.verify_all(self.conn, sample=False)
        self.assertEqual(self.snapshot()['rows'][1][3]['value'], 'true')
        db.save_classification(self.conn,pk,Classification(category='application_ack',company='Beta',role='Engineer'),'test','1')
        verification.verify_all(self.conn,refresh_since=date(2026,10,19),refresh_until=date(2026,10,25),week_only=True,rebuild=True,sample=False)
        self.assertEqual([row[3]['value'] for row in self.snapshot()['rows'][1:4]], ['true','false','false'])

    def test_rebuild_adds_new_matches_without_touching_saved_cells_or_proofs(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        base = self.snapshot()
        self.native.save(self.conn,self.tab(),'manual-before-rebuild',[{
            'row_id':base['row_ids'][3],'column_id':base['columns'][3]['id'],
            'expected_version':base['rows'][3][3]['version'],'value':'true'}])
        self.receipt('original-acme','Acme','2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn,sample=False)
        before = self.snapshot()
        ids = (before['row_ids'][1],before['row_ids'][3])
        proofs = [tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(i,)).fetchone()) for i in ids]
        self.receipt('earlier-acme','Acme','2026-10-20T14:00:00+00:00')
        self.receipt('new-beta','Beta','2026-10-22T14:00:00+00:00')
        self.conn.commit()
        response = self.client.post('/api/payments/refresh',json={'week':'2026-10-19','mode':'rebuild'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['changed'],1)
        after = self.snapshot()
        self.assertEqual([r[3]['value'] for r in after['rows'][1:4]],['true']*3)
        for index in (1,3):
            self.assertEqual(after['rows'][index][3],before['rows'][index][3])
        self.assertEqual([tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(i,)).fetchone()) for i in ids],proofs)
        self.assertEqual(after['rows'][2][3]['checked_at'],'2026-10-22T14:00:00+00:00')
        response = self.client.post('/api/payments/refresh',json={'week':'2026-10-19','mode':'rebuild'})
        self.assertEqual(response.json()['changed'],0)
        self.assertEqual(self.snapshot(),after)

    def test_all_check_paths_preserve_existing_credit_and_proofs(self):
        from unittest.mock import patch
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')",(self.account_id,))
        self.conn.commit()
        base = self.snapshot()
        self.native.save(self.conn,self.tab(),'manual-credit',[{
            'row_id':base['row_ids'][3],'column_id':base['columns'][3]['id'],
            'expected_version':base['rows'][3][3]['version'],'value':'true'}])
        self.receipt('original','Acme','2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn,sample=False)
        before = self.snapshot()
        ids = (before['row_ids'][1],before['row_ids'][3])
        proofs = [tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(i,)).fetchone()) for i in ids]
        self.receipt('earlier','Acme','2026-10-20T14:00:00+00:00')
        self.receipt('new','Beta','2026-10-22T14:00:00+00:00')
        self.conn.commit()
        for mode in ('auto-periodic','refresh','manual','rebuild','payment-poll'):
            with self.subTest(mode=mode):
                if mode == 'auto-periodic':
                    verification.verify_all(self.conn)
                    self.conn.commit()
                elif mode == 'manual':
                    verification.verify(self.conn,self.tab(),'check-with-saved-credit',self.snapshot()['revision'],'2026-10-20')
                    self.conn.commit()
                elif mode == 'payment-poll':
                    self.assertEqual(self.client.get('/api/payments?week=2026-10-19').status_code,200)
                else:
                    response = self.client.post('/api/payments/refresh',json={'week':'2026-10-19','mode':mode})
                    self.assertEqual(response.status_code,200,response.text)
                after = self.snapshot()
                for index in (1,3):
                    self.assertEqual(after['rows'][index][3],before['rows'][index][3])
                self.assertEqual([tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(i,)).fetchone()) for i in ids],proofs)
                self.assertEqual(after['rows'][2][3]['value'],'true')
                self.assertEqual(payments.report(self.conn,date(2026,10,19),read_only=True)['checked_daily'],[0,1,1,1,0,0,0])
        # Even a future rule that produces no matches must preserve credited rows.
        with patch.object(verification,'_matching_plan',return_value={}):
            verification.verify_all(self.conn,sample=False)
            self.assertEqual([r[3]['value'] for r in self.snapshot()['rows'][1:4]],['true']*3)

    def test_inspira_company_and_role_containment_check_the_application(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'inspira',base['revision'],[
            ['Inspira Financial','Principal AI Operations Engineer','https://jobs.test/inspira']],work_date='2026-10-20')
        self.receipt('inspira-confirmation','Inspira Financial Trust, LLC','2026-10-20T12:00:00Z',role='Principal AI Operations Engineer (Remote)')
        self.conn.commit();verification.verify_all(self.conn,sample=False)
        self.assertEqual(self.snapshot()['rows'][1][3]['value'],'true')

    def test_manual_matching_accepts_shorter_email_company_and_role(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        jobs=self.native.append(self.conn,self.tab(),'expanded-names',base['revision'],[
            ['Inspira Financial Trust LLC','Principal AI Operations Engineer (Remote)','https://jobs.test/inspira']],work_date='2026-10-20')
        self.receipt('short-names','Inspira Financial','2026-10-20T12:00:00Z',role='AI Operations Engineer')
        self.conn.commit()
        result=verification.verify(self.conn,self.tab(),'short-name-check',jobs['revision'],'2026-10-20')
        self.assertEqual(result['rows'][1][3]['value'],'true')

    def test_contained_role_does_not_choose_between_multiple_eligible_titles(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'role-alternatives',base['revision'],[
            ['Inspira Financial','Senior Software Engineer','https://jobs.test/senior'],
            ['Inspira Financial Trust LLC','Principal Software Engineer','https://jobs.test/principal']],work_date='2026-10-20')
        self.receipt('ambiguous-containment','Inspira Financial Trust LLC','2026-10-20T12:00:00Z',role='Software Engineer')
        self.conn.commit();verification.verify_all(self.conn,sample=False)
        self.assertEqual([row[3]['value'] for row in self.snapshot()['rows'][1:3]],['false','false'])

    def test_containment_does_not_match_word_fragments_or_conflicting_role_tokens(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        jobs=[['Metamask','Engineer','https://jobs.test/meta'],['Levels','Engineer III','https://jobs.test/level'],
            ['Languages','C++ Engineer','https://jobs.test/cpp'],['Titles','Engineering Manager','https://jobs.test/manager']]
        self.native.append(self.conn,self.tab(),'distinct-identities',base['revision'],jobs,work_date='2026-10-20')
        for key,company,role in [('meta','Meta','Engineer'),('level','Levels','Engineer II'),('language','Languages','C# Engineer'),('title','Titles','Engineer')]:
            self.receipt(key,company,'2026-10-20T12:00:00Z',role=role)
        self.conn.commit();verification.verify_all(self.conn,sample=False)
        self.assertEqual([row[3]['value'] for row in self.snapshot()['rows'][1:5]],['false']*4)

    def test_company_only_containment_remains_ambiguous_without_an_exact_company(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'company-alternatives',base['revision'],[
            ['Inspira Financial Services','Engineer','https://jobs.test/engineer'],
            ['Inspira Financial Trust LLC','Analyst','https://jobs.test/analyst']],work_date='2026-10-20')
        self.receipt('company-only-contained','Inspira Financial','2026-10-20T12:00:00Z',role=None)
        self.conn.commit();verification.verify_all(self.conn,sample=False)
        self.assertEqual([row[3]['value'] for row in self.snapshot()['rows'][1:3]],['false','false'])

    def test_out_of_window_exact_role_does_not_block_eligible_containment(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'old-exact-role',base['revision'],[
            ['Acme','Engineer','https://jobs.test/old']],work_date='2026-10-01')
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'current-contained-role',base['revision'],[
            ['Acme','Senior Engineer','https://jobs.test/current']],work_date='2026-10-20')
        self.receipt('current-short-role','Acme','2026-10-20T12:00:00Z',role='Engineer')
        self.conn.commit();verification.verify_all(self.conn,sample=False)
        checks=dict(self.conn.execute("""SELECT r.work_date,c.value FROM native_rows r
            JOIN native_cells c ON c.row_id=r.id JOIN native_columns col ON col.id=c.column_id
            WHERE col.kind='check' AND r.work_date IS NOT NULL"""))
        self.assertEqual(checks['2026-10-01'],'false')
        self.assertEqual(checks['2026-10-20'],'true')

    def test_expanded_company_aliases_do_not_remove_a_legacy_exact_check_on_rebuild(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        self.receipt('legacy-exact','Acme','2026-10-21T14:00:00Z')
        self.conn.commit();verification.verify_all(self.conn,sample=False)
        base=self.snapshot()
        self.assertEqual(base['rows'][1][3]['value'],'true')
        # Older activity records may have a counted time without a receipt ID.
        self.conn.execute('UPDATE sourcing_check_activity SET message_id=NULL WHERE row_id=?',(base['row_ids'][1],))
        self.conn.commit()
        self.native.append(self.conn,self.tab(),'new-company-alias',base['revision'],[
            ['Acme Trust LLC','Engineer','https://jobs.test/alias']],work_date='2026-10-20')
        self.conn.commit()
        verification.verify_all(self.conn,refresh_since=date(2026,10,19),refresh_until=date(2026,10,25),week_only=True,rebuild=True,sample=False)
        snap=self.snapshot()
        self.assertEqual(snap['rows'][1][3]['value'],'true')
        self.assertEqual(snap['rows'][4][3]['value'],'false')


    def test_broad_matches_add_credit_without_relocating_existing_checks(self):
        from mailcheck import sourcing_verification as verification
        self.jobs('2026-10-20')
        self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')",(self.account_id,))
        self.receipt('saved-exact','Acme','2026-10-21T14:00:00+00:00')
        self.conn.commit()
        verification.verify_all(self.conn,sample=False)
        base = self.snapshot()
        row_id = base['row_ids'][1]
        proof = tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(row_id,)).fetchone())
        self.native.append(self.conn,self.tab(),'broad-only-job',base['revision'],[
            ['Inspira Financial','Principal AI Operations Engineer','https://jobs.test/inspira-new']],work_date='2026-10-20')
        self.receipt('earlier-broad-alias','Acme Trust LLC','2026-10-20T14:00:00+00:00')
        self.receipt('new-broad-match','Inspira Financial Trust LLC','2026-10-22T14:00:00+00:00',role='AI Operations Engineer')
        self.conn.commit()
        for mode in ('rebuild','refresh','auto-periodic'):
            with self.subTest(mode=mode):
                if mode == 'auto-periodic':
                    verification.verify_all(self.conn,sample=False)
                    self.conn.commit()
                else:
                    response = self.client.post('/api/payments/refresh',json={'week':'2026-10-19','mode':mode})
                    self.assertEqual(response.status_code,200,response.text)
                after = self.snapshot()
                self.assertEqual(after['rows'][1][3],base['rows'][1][3])
                self.assertEqual(after['rows'][4][3]['value'],'true')
                self.assertEqual(tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(row_id,)).fetchone()),proof)
                self.assertEqual(payments.report(self.conn,date(2026,10,19),read_only=True)['checked_daily'],[0,0,1,1,0,0,0])

    def test_hp_company_only_diagnostic_is_read_only_and_exposes_ambiguity(self):
        from tools.explain_application_matches import explain
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'hp-first',base['revision'],[
            ['HP','Embedded AI/ML Developer','https://hp.test/first']],work_date='2026-10-20')
        self.receipt('hp-no-role','HP','2026-10-21T14:00:00Z',role=None)
        self.conn.commit()
        email=self.conn.execute('SELECT email FROM accounts WHERE id=?',(self.account_id,)).fetchone()[0]
        before=self.snapshot()
        result=explain(self.path,email,'HP')
        self.assertEqual(self.snapshot(),before)
        self.assertTrue(result['rows'][0]['would_add_check'])
        self.assertTrue(result['rows'][0]['has_job_link'])
        self.assertFalse(result['receipts'][0]['role'])
        self.assertNotIn('message_id',result['receipts'][0])
        self.assertNotIn('link',result['rows'][0])
        self.native.append(self.conn,self.tab(),'hp-second',before['revision'],[
            ['HP','Senior Engineer','https://hp.test/second']],work_date='2026-10-20')
        result=explain(self.path,email,'HP')
        self.assertEqual(len(result['rows']),2)
        self.assertFalse(any(row['would_add_check'] for row in result['rows']))
        result=explain(self.path,'different@example.test','HP')
        self.assertEqual(result['matching_account_ids'],[])
        self.assertFalse(any(row['same_email_account'] for row in result['rows']))

    def test_hp_company_only_checks_current_unchecked_job_despite_history(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'hp-history',base['revision'],[
            ['HP','Senior Engineer','https://hp.test/old']],work_date='2026-10-19')
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'hp-today',base['revision'],[
            ['HP','Embedded AI/ML Developer','https://hp.test/new']],work_date='2026-10-20')
        self.receipt('hp-company-only-today','HP','2026-10-20T12:00:00Z',role=None)
        self.conn.commit()
        before=self.snapshot()
        after=verification.verify(self.conn,self.tab(),'hp-manual',before['revision'],'2026-10-20')
        self.assertEqual([r[3]['value']=='true' for r in after['rows'][1:3]],[False,True])
        proof=tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(after['row_ids'][2],)).fetchone())
        for rebuild in (False,True):
            verification.verify_all(self.conn,refresh_since=date(2026,10,19),refresh_until=date(2026,10,25),week_only=True,rebuild=rebuild,sample=False)
            self.assertEqual([r[3]['value']=='true' for r in self.snapshot()['rows'][1:3]],[False,True])
            self.assertEqual(tuple(self.conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(after['row_ids'][2],)).fetchone()),proof)

    def test_hp_checked_job_does_not_block_an_unbound_company_only_confirmation(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'hp-two',base['revision'],[
            ['HP','Engineer','https://hp.test/checked'],
            ['HP','Embedded AI/ML Developer','https://hp.test/unchecked']],work_date='2026-10-20')
        base=self.snapshot()
        self.native.save(self.conn,self.tab(),'hp-existing-credit',[{
            'row_id':base['row_ids'][1],'column_id':base['columns'][3]['id'],
            'expected_version':base['rows'][1][3]['version'],'value':'true'}])
        before=self.snapshot()
        self.receipt('hp-new-company-only','HP','2026-10-20T12:00:00Z',role=None)
        self.conn.commit()
        verification.verify_all(self.conn,sample=False)
        after=self.snapshot()
        self.assertEqual([r[3]['value'] for r in after['rows'][1:3]],['true','true'])
        self.assertEqual(before['rows'][1][3],after['rows'][1][3])

    def test_hp_delayed_confirmation_prefers_latest_unchecked_source_day(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'older-hp',base['revision'],[
            ['HP','Senior Engineer','https://hp.test/older']],work_date='2026-10-19')
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'recent-hp',base['revision'],[
            ['HP','Embedded AI/ML Developer','https://hp.test/recent']],work_date='2026-10-20')
        self.receipt('next-day-hp','HP','2026-10-21T14:00:00Z',role=None)
        self.conn.commit()
        verification.verify_all(self.conn,sample=False)
        snap=self.snapshot()
        self.assertEqual([r[3]['value'] for r in snap['rows'][1:3]],['false','true'])
        self.assertEqual(snap['rows'][2][3]['checked_at'],'2026-10-21T14:00:00+00:00')
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM sourcing_check_activity WHERE message_id=?',('next-day-hp',)).fetchone()[0],1)
        for rebuild in (False,True):
            verification.verify_all(self.conn,refresh_since=date(2026,10,19),refresh_until=date(2026,10,25),week_only=True,rebuild=rebuild,sample=False)
            self.assertEqual(self.snapshot()['rows'][2][3],snap['rows'][2][3])
            self.assertEqual(self.snapshot()['rows'][1][3]['value'],'false')

    def test_unchecked_reason_identifies_a_confirmation_already_used_elsewhere(self):
        from mailcheck import sourcing_verification as verification
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'bound-hp-old',base['revision'],[
            ['HP','Engineer','https://hp.test/old']],work_date='2026-10-19')
        self.receipt('bound-hp','HP','2026-10-20T14:00:00Z',role=None)
        self.conn.commit()
        verification.verify_all(self.conn,sample=False)
        base=self.snapshot()
        self.native.append(self.conn,self.tab(),'unclaimed-hp-new',base['revision'],[
            ['HP','Embedded AI/ML Developer','https://hp.test/new']],work_date='2026-10-20')
        base=self.snapshot()
        result=verification.verify(self.conn,self.tab(),'explain-bound',base['revision'],'2026-10-20')
        self.assertEqual(result['verification']['unmatched_count'],1)
        self.assertIn('already linked to a checked job',result['verification']['unmatched'][0]['reason'])
        self.assertEqual(result['rows'][2][3]['value'],'false')
        self.assertEqual(result['rows'][1][3],base['rows'][1][3])
