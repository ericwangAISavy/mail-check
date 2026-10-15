"""Real SQLite accounting, dated assignments, settlements and server permissions."""
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
        result = payments.report(self.conn, week)
        self.conn.commit()
        return result

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
            self.assign(who=2, start=date(2026,10,14), end=date(2026,10,14))

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
        self.assign(); self.message("one")
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
        self.client.post('/api/auth/login',json={"role":"guest","password":"guest"})
        report=self.client.get('/api/payments?week=2026-10-12')
        self.assertEqual(report.status_code,200)
        self.assertEqual([b["name"] for b in report.json()["bidders"]],["Alex","Blair"])
        self.assertEqual(report.json()["accounts"],[])
        self.assertEqual(self.client.get('/payments').status_code,200)
        for route in ('/api/payments/bidders','/api/payments/bidders/1','/api/payments/bidders/1/assignments','/api/payments/assignments/1/end','/api/payments/bidders/1/paid'):
            self.assertEqual(self.client.post(route,json={}).status_code,403)

    def test_admin_creates_bidder_assigns_accounts_and_records_manual_amount(self):
        self.message("one")
        self.assertEqual(self.client.post('/api/payments/bidders',json={"name":"Casey"}).status_code,200)
        self.assertEqual(self.client.post('/api/payments/bidders/3/assignments',json={"account_id":self.account,"start_date":"2026-10-12"}).status_code,200)
        response=self.client.post('/api/payments/bidders/3/paid',json={"week":"2026-10-12","expected_count":1,"amount":"42.05"})
        self.assertEqual(response.status_code,200,response.text)
        response=self.client.get('/api/payments?week=2026-10-12').json()
        self.assertEqual(next(b for b in response["bidders"] if b["id"]==3)["payment"]["amount_cents"],4205)

    def test_end_assignment_api_protects_paid_periods(self):
        self.assign(); self.message("one")
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

    def test_edit_rejects_overlaps_and_invalid_dates(self):
        self.assign(end=date(2026,10,14));self.assign(who=2,start=date(2026,10,15))
        for body in ({"account_id":self.account,"start_date":"2026-10-12","end_date":None},
                     {"account_id":self.account,"start_date":"2026-10-14","end_date":"2026-10-12"}):
            self.assertEqual(self.client.post('/api/payments/assignments/1',json=body).status_code,400)
        self.assertEqual(self.conn.execute('SELECT end_date FROM bidder_assignments WHERE id=1').fetchone()[0],'2026-10-14')

    def test_paid_weeks_block_remove_but_allow_edits_outside_paid_dates(self):
        self.assign();self.message("one")
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
        self.client.post('/api/auth/login',json={"role":"guest","password":"guest"})
        for route in ('/api/payments/assignments/1','/api/payments/assignments/1/remove'):
            self.assertEqual(self.client.post(route,json={}).status_code,403)
