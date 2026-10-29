"""Real SQLite accounting, dated assignments, settlements and server permissions."""
from tests.web_client import sign_in_bidder
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from mailcheck import config, db, payments
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.web.app import create_app
from tests.web_client import TestClient


class PaymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "mail.db"
        self.conn = db.connect(self.path)
        self.addCleanup(self.conn.close)
        for name, value in (("db_path", self.path), ("config_dir", self.root), ("config_path", self.root / "config.toml")):
            active = patch.object(config, name, return_value=value)
            active.start(); self.addCleanup(active.stop)
        active = patch.object(payments, "today", return_value=date(2026, 10, 20))
        active.start(); self.addCleanup(active.stop)
        self.account = db.add_account(self.conn, label="personal", email="me@example.test")
        self.other = db.add_account(self.conn, label="work", email="work@example.test")
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('Alex','2026-01-01')")
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('Blair','2026-01-01')")
        self.conn.commit()
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def assign(self, who=1, account=None, start=date(2026,10,12), end=None):
        payments.assign(self.conn, who, payments.AssignmentBody(account_id=account or self.account, start_date=start, end_date=end))
        self.conn.commit()

    def message(self, key, stamp="2026-10-13T01:00:00+00:00", category="application_ack", account=None):
        msg = NormalizedMessage(account_id=account or self.account, account_label="personal", message_id=key, uid=key, folder="INBOX", from_addr="hr@example.test", from_name="HR", subject="Received", date_utc=datetime.fromisoformat(stamp) if stamp else None, body="Thanks")
        pk = db.upsert_message(self.conn, msg)
        db.save_classification(self.conn, pk, Classification(category=category), "model", "v1")
        return pk

    def report(self, week=date(2026,10,12)):
        result = payments.report(self.conn, week, admin=True)
        self.conn.commit()
        return result

    def test_received_today_uses_chicago_day_and_unique_receipts_across_accounts(self):
        with patch.object(payments, 'today', return_value=date(2026,10,12)):
            self.message('before', '2026-10-12T04:59:59Z')
            self.message('start', '2026-10-12T05:00:00Z')
            self.message('start', '2026-10-12T05:00:00Z')
            self.message('end', '2026-10-13T04:59:59Z', account=self.other)
            self.message('after', '2026-10-13T05:00:00Z')
            self.message('noise', '2026-10-12T12:00:00Z', category='noise')
            self.assertEqual(payments.received_today(self.conn), 2)

    def test_multi_account_daily_weekly_and_repeated_fetch_counts(self):
        self.assign(); self.assign(account=self.other)
        self.message("one"); self.message("one"); self.message("two", account=self.other)
        self.message("unrelated", category="interview_invite")
        row = self.report()["bidders"][0]
        self.assertEqual(row["daily"], [2,0,0,0,0,0,0])
        self.assertEqual(row["total"], 2)
        db.set_handled(self.conn, 1, True)
        self.assertEqual(self.report()["bidders"][0]["total"], 2)

    def test_transfer_uses_receipt_date_and_rejects_overlaps(self):
        self.assign(end=date(2026,10,14))
        self.assign(who=2, start=date(2026,10,15))
        self.message("before", "2026-10-14T15:00:00Z")
        self.message("after", "2026-10-15T15:00:00Z")
        self.assertEqual([b["total"] for b in self.report()["bidders"]], [1,1])
        with self.assertRaisesRegex(ValueError, "already has an assignment"):
            self.assign(who=2, start=date(2026,10,15), end=date(2026,10,15))

    def test_week_boundary_and_dst_use_chicago_calendar_days(self):
        self.assign(start=date(2026,10,1))
        self.message("sunday", "2026-11-02T05:59:59Z")
        self.message("monday", "2026-11-02T06:00:00Z")
        row = self.report(date(2026,10,26))["bidders"][0]
        self.assertEqual(row["daily"], [0,0,0,0,0,0,1])
        self.assertEqual(self.report(date(2026,11,2))["bidders"][0]["daily"][0],1)

    def test_reclassification_changes_count_without_double_counting(self):
        self.assign(); pk=self.message("one")
        self.assertEqual(self.report()["bidders"][0]["total"],1)
        db.save_classification(self.conn,pk,Classification(category="other"),"model","v1")
        self.assertEqual(self.report()["bidders"][0]["total"],0)
        db.save_classification(self.conn,pk,Classification(category="application_ack"),"model","v1")
        self.assertEqual(self.report()["bidders"][0]["total"],1)

    def test_counts_survive_retention_and_account_deletion_without_id_reuse(self):
        self.assign(); self.message("one")
        db.prune_messages(self.conn,before_iso="2027-01-01")
        self.assertEqual(self.report()["bidders"][0]["total"],1)
        db.remove_account(self.conn,"personal")
        new=db.add_account(self.conn,label="replacement",email="new@example.test")
        self.assertNotEqual(new,self.account)
        self.message("one",account=new)
        self.assertEqual(self.report()["bidders"][0]["total"],1)
        self.assertEqual(self.report()["unassigned"],1)

    def test_manual_payment_snapshot_and_idempotency(self):
        self.assign(); self.message("one"); self.add_checks(1, self.account, 1)
        body=payments.PayBody(week=date(2026,10,12),expected_count=1,amount="125.50",note="Bank ref 123")
        payments.record_payment(self.conn,1,body); self.conn.commit()
        paid=self.report()["bidders"][0]["payment"]
        self.assertEqual(paid["amount_cents"],12550)
        self.assertEqual(paid["application_count"],1)
        self.message("late")
        self.assertEqual(self.report()["bidders"][0]["payment"],paid)
        with self.assertRaises(ValueError): payments.record_payment(self.conn,1,body)
        with self.assertRaisesRegex(ValueError,"recorded payment"):
            self.assign(who=1, account=self.other)
        self.assign(who=2, account=self.other)

    def test_reject_current_week_stale_count_invalid_amount_and_dates(self):
        self.assign(); self.message("one")
        for body in ({"week":"2026-10-19","expected_count":0,"amount":"10"}, {"week":"2026-10-12","expected_count":9,"amount":"10"}):
            response=self.client.post('/api/payments/bidders/1/paid',json=body)
            self.assertEqual(response.status_code,400,response.text)
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid',json={"week":"2026-10-12","expected_count":1,"amount":"1.001"}).status_code,422)
        self.assertEqual(self.client.get('/api/payments?week=9999-12-31').status_code,422)

    def test_guest_reads_all_totals_but_cannot_modify_any_accounting_data(self):
        self.assign(); self.message("one")
        sign_in_bidder(self.client)
        report=self.client.get('/api/payments?week=2026-10-12')
        self.assertEqual(report.status_code,200)
        self.assertEqual([b["name"] for b in report.json()["bidders"]],["Alex"])
        self.assertEqual(report.json()["accounts"],[])
        self.assertEqual(self.client.get('/payments').status_code,200)
        for route in ('/api/payments/bidders','/api/payments/bidders/1','/api/payments/bidders/1/assignments','/api/payments/assignments/1/end','/api/payments/bidders/1/paid','/api/payments/bidders/1/remove'):
            self.assertEqual(self.client.post(route,json={}).status_code,403)

    def test_admin_creates_bidder_assigns_accounts_and_records_manual_amount(self):
        self.message("one")
        self.assertEqual(self.client.post('/api/payments/bidders',json={"name":"Casey"}).status_code,200)
        self.assertEqual(self.client.post('/api/payments/bidders/3/assignments',json={"account_id":self.account,"start_date":"2026-10-12"}).status_code,200)
        self.add_checks(3, self.account, 1)
        response=self.client.post('/api/payments/bidders/3/paid',json={"week":"2026-10-12","expected_count":1,"amount":"42.05"})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.get('/api/payments?week=2026-10-12').json()
        self.assertEqual(next(b for b in response["bidders"] if b["id"]==3)["payment"]["amount_cents"],4205)

    def test_bidder_removal_refreshes_sourcing_and_preserves_history(self):
        from mailcheck import native_sourcing
        self.assign(); self.message("one")
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid', json={
            "week": "2026-10-12", "expected_count": 1, "amount": "10"}).status_code, 200)
        book = native_sourcing.create_book(self.conn, 1)
        native_sourcing.create_tab(self.conn, book, self.account, "Applications")
        response = self.client.post('/api/payments/bidders/1/remove', json={})
        self.assertEqual(response.status_code, 200, response.text)
        index = self.client.get('/api/sourcing').json()
        self.assertNotIn(1, [b["id"] for b in index["bidders"]])
        self.assertNotIn(1, [b["bidder_id"] for b in index["books"]])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bidder_payments WHERE bidder_id=1').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM native_tabs WHERE book_id=? AND archived=1', (book,)).fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT login_enabled FROM bidders WHERE id=1').fetchone()[0], 0)
        self.assertEqual(self.client.post('/api/payments/bidders/1/remove', json={}).status_code, 404)
        self.assertEqual(self.client.post('/api/payments/bidders', json={"name": "New bidder"}).status_code, 200)
        index = self.client.get('/api/sourcing').json()
        self.assertIn("New bidder", [b["name"] for b in index["books"]])

    def test_end_assignment_api_protects_paid_periods(self):
        self.assign(); self.message("one"); self.add_checks(1, self.account, 1)
        paid=self.client.post('/api/payments/bidders/1/paid',json={"week":"2026-10-12","expected_count":1,"amount":"10"})
        self.assertEqual(paid.status_code,200)
        self.assertEqual(self.client.post('/api/payments/assignments/1/end',json={"end_date":"2026-10-14"}).status_code,400)
        self.assertEqual(self.client.post('/api/payments/assignments/1/end',json={"end_date":"2026-10-18"}).status_code,200)

    def test_edit_and_remove_assignment_recalculate_totals_without_deleting_receipts(self):
        self.assign(); self.message("one")
        url='/api/payments/assignments/1'
        response=self.client.post(url,json={"account_id":self.other,"start_date":"2026-10-12","end_date":"2026-10-14"})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.report()["bidders"][0]["total"],0)
        self.assertEqual(self.client.post(url,json={"account_id":self.account,"start_date":"2026-10-12","end_date":None}).status_code,200)
        self.assertEqual(self.report()["bidders"][0]["total"],1)
        self.assertEqual(self.client.post(url+'/remove',json={}).status_code,200)
        self.assertEqual(self.report()["bidders"][0]["total"],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM application_receipts').fetchone()[0],1)
        self.assertEqual(self.client.post(url+'/remove',json={}).status_code,404)

    def test_shared_account_creation_edit_and_unassigned_counts(self):
        self.assign(end=date(2026,10,14))
        response = self.client.post('/api/payments/bidders/2/assignments', json={
            "account_id": self.account, "start_date": "2026-10-12"})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.post('/api/payments/assignments/1', json={
            "account_id": self.account, "start_date": "2026-10-12", "end_date": None})
        self.assertEqual(response.status_code, 200, response.text)
        self.message("shared")
        self.message("unassigned", account=self.other)
        result = self.report()
        self.assertEqual([b["total"] for b in result["bidders"]], [0, 0])
        self.assertEqual(result["unallocated_daily"][0], 1)
        self.assertEqual(result["unassigned"], 1)
        self.assertEqual(result["daily"], [1, 0, 0, 0, 0, 0, 0])
        duplicate = self.client.post('/api/payments/bidders/2/assignments', json={
            "account_id": self.account, "start_date": "2026-10-13"})
        self.assertEqual(duplicate.status_code, 400)

    def add_checks(self, who, account, count, day="2026-10-12"):
        from mailcheck import native_sourcing as sheets
        book = sheets.create_book(self.conn, who)
        tab_id = sheets.create_tab(self.conn, book, account, "Applications")
        tab = sheets.owned(self.conn, tab_id, {"role": "admin"})
        base = sheets.snapshot(self.conn, tab)
        sheets.append(self.conn, tab, f"checks-{who}-{account}", base["revision"],
            [["Acme", "Engineer", f"https://jobs.test/{who}/{account}/{i}", "true"] for i in range(count)], work_date=day)

    def test_shared_receipts_are_allocated_by_account_day_weights_and_rounded_to_total(self):
        self.assign(); self.assign(who=2)
        self.add_checks(1, self.account, 11)
        self.add_checks(2, self.account, 75)
        for i in range(105):
            self.message(str(i))
        result = self.report()
        self.assertEqual([b["daily"][0] for b in result["bidders"]], [13, 92])
        self.assertEqual(result["daily"][0], 105)
        self.assertEqual(result["unallocated_daily"][0], 0)
        # Bidder-scoped reports must use all competitors' weights before filtering.
        scoped = payments.report(self.conn, date(2026,10,12), bidder_id=1)
        self.conn.commit()
        self.assertEqual(scoped["daily"][0], 13)
        self.assertEqual([b["id"] for b in scoped["bidders"]], [1])
        payment = self.client.post('/api/payments/bidders/1/paid', json={
            "week":"2026-10-12", "expected_count":13, "amount":"10"})
        self.assertEqual(payment.status_code, 200, payment.text)
        self.assertEqual(self.report()["bidders"][0]["payment"]["application_count"], 13)

    def test_shared_weights_do_not_mix_accounts_and_zero_weight_gets_zero(self):
        self.assign(); self.assign(who=2)
        self.assign(account=self.other); self.assign(who=2, account=self.other)
        self.add_checks(1, self.account, 1)
        self.add_checks(2, self.other, 1)
        for i in range(3): self.message(f"a{i}")
        for i in range(7): self.message(f"b{i}", account=self.other)
        self.message("no-checks-next-day", "2026-10-13T15:00:00+00:00")
        result = self.report()
        self.assertEqual(result["unallocated_daily"][1], 1)
        self.assertEqual([b["total"] for b in result["bidders"]], [3, 7])
        self.assertEqual(result["daily"][0], 10)

    def test_two_shared_accounts_use_separate_contributors_before_summing_bidder_estimates(self):
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('Casey','2026-01-01')")
        self.assign(); self.assign(account=self.other)
        self.assign(who=2); self.assign(who=3, account=self.other)
        # Alex shares A with Blair and B with Casey. Neither account's weights
        # or receipt totals may enter the other account's allocation.
        self.add_checks(1, self.account, 1)
        self.add_checks(2, self.account, 3)
        self.add_checks(1, self.other, 3)
        self.add_checks(3, self.other, 1)
        for i in range(100): self.message(f"a-{i}")
        for i in range(40): self.message(f"b-{i}", account=self.other)
        result = self.report()
        rows = {b['id']: b for b in result['bidders']}
        # A: 25/75; B: 30/10. Alex receives 25 + 30, not a pooled share.
        self.assertEqual([rows[i]['daily'][0] for i in (1, 2, 3)], [55, 75, 10])
        self.assertEqual([rows[i]['checked_daily'][0] for i in (1, 2, 3)], [4, 3, 1])
        self.assertEqual(rows[1]['total'], 55)
        self.assertEqual(result['daily'][0], 140)
        self.assertEqual(result['unallocated_daily'][0], 0)
        scoped = payments.report(self.conn, date(2026,10,12), bidder_id=1)
        self.assertEqual(scoped['bidders'][0]['daily'][0], 55)

    def test_primary_application_count_sums_daily_estimates_across_assigned_accounts(self):
        self.assign(); self.assign(account=self.other)
        self.add_checks(1, self.account, 2)
        self.add_checks(1, self.other, 3)
        for i in range(9): self.message(f"received-{i}")
        row = self.report()["bidders"][0]
        self.assertEqual(row["application_total"], 9)
        self.assertEqual(row["checked_daily"][0], 5)
        response = self.client.post('/api/payments/bidders/1/paid', json={
            "week":"2026-10-12", "expected_count":9, "amount":"10"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.report()["bidders"][0]["payment"]["application_count"], 9)

    def test_allocation_rounding_is_deterministic_for_ties(self):
        self.assign(); self.assign(who=2)
        self.add_checks(1, self.account, 1); self.add_checks(2, self.account, 1)
        self.message("one")
        self.assertEqual([b["total"] for b in self.report()["bidders"]], [1, 0])

    def test_edit_rejects_same_bidder_overlaps_and_invalid_dates(self):
        self.assign(end=date(2026,10,14));self.assign(start=date(2026,10,15))
        for body in ({"account_id":self.account,"start_date":"2026-10-12","end_date":None},
                     {"account_id":self.account,"start_date":"2026-10-14","end_date":"2026-10-12"}):
            self.assertEqual(self.client.post('/api/payments/assignments/1',json=body).status_code,400)
        self.assertEqual(self.conn.execute('SELECT end_date FROM bidder_assignments WHERE id=1').fetchone()[0],'2026-10-14')

    def test_paid_weeks_block_remove_but_allow_edits_outside_paid_dates(self):
        self.assign();self.message("one");self.add_checks(1, self.account, 1)
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid',json={"week":"2026-10-12","expected_count":1,"amount":"10"}).status_code,200)
        url='/api/payments/assignments/1'
        self.assertEqual(self.client.post(url+'/remove',json={}).status_code,400)
        for body in ({"account_id":self.account,"start_date":"2026-10-13","end_date":None},
                     {"account_id":self.other,"start_date":"2026-10-12","end_date":None}):
            self.assertEqual(self.client.post(url,json=body).status_code,400)
        self.assertEqual(self.client.post(url,json={"account_id":self.account,"start_date":"2026-10-12","end_date":"2026-10-18"}).status_code,200)
        self.assertEqual(self.client.post(url,json={"account_id":self.account,"start_date":"2026-10-12","end_date":None}).status_code,200)

    def test_guest_cannot_edit_or_remove_assignments(self):
        self.assign()
        sign_in_bidder(self.client)
        for route in ('/api/payments/assignments/1','/api/payments/assignments/1/remove'):
            self.assertEqual(self.client.post(route,json={}).status_code,403)

    def test_preassigned_links_count_on_confirmation_day_and_allocate_shared_receipts(self):
        from mailcheck import sourcing_activity as activity
        self.assign(); self.assign(who=2)
        self.add_checks(1,self.account,1,day='2026-10-11')
        self.add_checks(2,self.account,3,day='2026-10-11')
        for row in self.conn.execute(activity._CHECKED_ROWS).fetchall():
            activity.confirm(self.conn,row['row_id'],datetime(2026,10,13,1,tzinfo=timezone.utc),'receipt-'+row['row_id'])
        for i in range(20): self.message('confirmation-'+str(i))
        report = self.report()
        self.assertEqual([b['checked_daily'][0] for b in report['bidders']],[1,3])
        self.assertEqual([b['daily'][0] for b in report['bidders']],[5,15])
        self.assertEqual(report['unallocated_daily'][0],0)
        self.assertEqual(report['checked_daily'][0],4)
        # Cross-week work is counted once, on the Chicago confirmation date.
        previous = self.report(date(2026,10,5))
        self.assertEqual(previous['checked_daily'],[0]*7)
        scoped = payments.report(self.conn,date(2026,10,12),bidder_id=1)
        self.assertEqual(scoped['bidders'][0]['checked_daily'][0],1)
        self.assertEqual(scoped['bidders'][0]['daily'][0],5)

    def test_completion_day_requires_assignment_on_that_day_and_survives_rechecks(self):
        from mailcheck import sourcing_activity as activity
        self.assign(start=date(2026,10,13)); self.assign(who=2,end=date(2026,10,12))
        self.add_checks(1,self.account,1)
        self.add_checks(2,self.account,1)
        for row in self.conn.execute(activity._CHECKED_ROWS).fetchall():
            activity.confirm(self.conn,row['row_id'],datetime(2026,10,13,4,59,tzinfo=timezone.utc),'receipt-'+row['row_id'])
        self.assertEqual(self.report()['checked_daily'],[1,0,0,0,0,0,0])
        for row in self.conn.execute(activity._CHECKED_ROWS).fetchall():
            activity.confirm(self.conn,row['row_id'],datetime(2026,10,13,6,tzinfo=timezone.utc),'receipt-'+row['row_id'])
        report = self.report()
        self.assertEqual([b['checked_daily'][1] for b in report['bidders']],[1,0])
        self.assertEqual(report['checked_daily'],[0,1,0,0,0,0,0])

    def test_wallet_save_validation_permissions_and_rename_preservation(self):
        address='0x6A33C5254C47DEfE820d93EAa2F4bd7ab9C378BD'
        response=self.client.post('/api/payments/bidders/1/wallet',json={'wallet_network':'usdt.bep20','wallet_address':address})
        self.assertEqual(response.status_code,200,response.text)
        row=self.client.get('/api/payments').json()['bidders'][0]
        self.assertEqual((row['wallet_network'],row['wallet_address']),('USDT.BEP20',address))
        self.client.post('/api/payments/bidders/1',json={'name':'Renamed'})
        self.assertEqual(self.conn.execute('SELECT wallet_address FROM bidders WHERE id=1').fetchone()[0],address)
        for invalid in ('0x123','bad\naddress','0x'+'g'*40):
            self.assertEqual(self.client.post('/api/payments/bidders/1/wallet',json={'wallet_address':invalid}).status_code,422)
        self.assertEqual(self.client.post('/api/payments/bidders/1/wallet',json={'wallet_address':''}).status_code,200)
        self.assertEqual(self.conn.execute('SELECT wallet_address FROM bidders WHERE id=1').fetchone()[0],'')
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.post('/api/payments/bidders/1/wallet',json={'wallet_address':address}).status_code,403)
        self.assertNotIn('wallet_address',self.client.get('/api/payments').json()['bidders'][0])

    def test_bidder_rate_calculates_money_with_adjustment_and_manual_week_override(self):
        self.assign()
        for i in range(309):self.message(f'rate-{i}')
        self.assertEqual(self.client.post('/api/payments/bidders/1/rate',json={'pay_per_bid':'0.05','adjustment_percent':'20'}).status_code,200)
        row=self.client.get('/api/payments?week=2026-10-12').json()['bidders'][0]
        self.assertEqual(row['calculated_amount_cents'],1854)
        self.assertEqual(row['payable_amount_cents'],1854)
        self.assertEqual(self.client.post('/api/payments/bidders/1/amount',json={'week':'2026-10-12','expected_count':309,'amount':'22.00'}).status_code,200)
        self.assertEqual(self.client.get('/api/payments?week=2026-10-12').json()['bidders'][0]['payable_amount_cents'],2200)
        self.assertEqual(self.client.post('/api/payments/bidders/1/amount',json={'week':'2026-10-12','expected_count':308,'amount':'30'}).status_code,400)
        self.assertEqual(self.client.post('/api/payments/bidders/1/amount',json={'week':'2026-10-12','expected_count':309,'amount':None}).status_code,200)
        self.assertEqual(self.client.get('/api/payments?week=2026-10-12').json()['bidders'][0]['payable_amount_cents'],1854)
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid',json={'week':'2026-10-12','expected_count':309,'amount':'18.54'}).status_code,200)
        self.client.post('/api/payments/bidders/1/rate',json={'pay_per_bid':'0.06','adjustment_percent':'20'})
        paid=self.client.get('/api/payments?week=2026-10-12').json()['bidders'][0]
        self.assertEqual(paid['calculated_amount_cents'],2225)
        self.assertEqual(paid['payable_amount_cents'],1854)
        self.assertEqual(self.client.post('/api/payments/bidders/1/amount',json={'week':'2026-10-12','expected_count':309,'amount':'25'}).status_code,400)

    def test_rate_rounding_validation_and_bidder_permissions(self):
        self.assertEqual(payments.calculate_amount('0.025',1,'0'),3)
        self.assertEqual(payments.calculate_amount('0.06',309,'20'),2225)
        self.assertIsNone(payments.calculate_amount(None,309,'20'))
        for invalid in ('-0.01','NaN','Infinity','0.0.6'):
            self.assertEqual(self.client.post('/api/payments/bidders/1/rate',json={'pay_per_bid':invalid}).status_code,422)
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.post('/api/payments/bidders/1/rate',json={'pay_per_bid':'0.05'}).status_code,403)
        self.assertEqual(self.client.post('/api/payments/bidders/1/amount',json={'week':'2026-10-12','expected_count':0,'amount':'1'}).status_code,403)

    def test_paid_amount_can_be_edited_with_history_and_stale_edit_protection(self):
        self.assign();self.message('first')
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid',json={'week':'2026-10-12','expected_count':1,'amount':'19.70','note':'Original'}).status_code,200)
        original=self.report()['bidders'][0]['payment']
        self.message('second')
        body={'week':'2026-10-12','expected_count':2,'expected_revision':0,'amount':'18.54','note':'Corrected'}
        response=self.client.post('/api/payments/bidders/1/paid/edit',json=body)
        self.assertEqual(response.status_code,200,response.text)
        paid=self.report()['bidders'][0]['payment']
        self.assertEqual((paid['amount_cents'],paid['application_count'],paid['revision']),(1854,2,1))
        self.assertEqual(paid['paid_at'],original['paid_at'])
        audit=self.conn.execute('SELECT * FROM bidder_payment_edits').fetchall()
        self.assertEqual(len(audit),1)
        import json
        self.assertEqual(json.loads(audit[0]['before_json'])['amount_cents'],1970)
        self.assertEqual(json.loads(audit[0]['after_json'])['amount_cents'],1854)
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid/edit',json=body).status_code,400)
        self.assertEqual(len(self.conn.execute('SELECT * FROM bidder_payment_edits').fetchall()),1)
        sign_in_bidder(self.client,1)
        self.assertEqual(self.client.post('/api/payments/bidders/1/paid/edit',json={**body,'expected_revision':1}).status_code,403)

    def test_viewer_reads_do_not_reconcile_or_sync_receipts(self):
        from fastapi.testclient import TestClient as WorkerClient
        with WorkerClient(create_app(worker_secret="worker-only")) as client:
            headers={"x-offerpath-worker":"worker-only","x-offerpath-viewer":"bidder","x-offerpath-bidder":"1"}
            with patch("mailcheck.web.app.sourcing_verification.verify_all") as verify, patch("mailcheck.payments.sync_receipts") as sync:
                result=client.get("/api/payments",headers=headers)
                self.assertEqual(result.status_code,200,result.text)
                self.assertEqual([b['name'] for b in result.json()['bidders']],['Alex','Blair'])
                verify.assert_not_called();sync.assert_not_called()
            self.assertEqual(client.post("/api/payments/refresh",json={},headers=headers).status_code,403)
            self.assertEqual(client.get("/api/accounts",headers=headers).status_code,403)
            self.conn.execute("UPDATE bidders SET removed_at='2026-10-28' WHERE id=1");self.conn.commit()
            self.assertEqual(client.get("/api/dashboard",headers=headers).status_code,401)
