from datetime import date, datetime, timezone
from unittest.mock import patch
import unittest
from mailcheck import sourcing_activity as activity
from tests import test_payments as fixtures
from tests.web_client import sign_in_bidder

class ActivityTests(unittest.TestCase):
    setUp = fixtures.PaymentTests.setUp
    assign = fixtures.PaymentTests.assign
    add_checks = fixtures.PaymentTests.add_checks

    def confirm_existing(self, stamp):
        for row in self.conn.execute(activity._CHECKED_ROWS).fetchall():
            activity.confirm(self.conn,row['row_id'],stamp,'receipt-'+row['row_id'])

    def test_new_checks_are_recorded_once_and_zero_runs_are_visible(self):
        self.assign()
        self.add_checks(1,self.account,2)
        with patch.object(activity,'now',return_value=datetime(2026,10,12,15,30,tzinfo=timezone.utc)):
            self.confirm_existing(activity.now())
            activity.record(self.conn,'global-check',sample=True)
            activity.record(self.conn,'global-check',sample=True)
        report = activity.report(self.conn,date(2026,10,12))
        alex = report['bidders'][0]
        self.assertEqual(alex['new_checks'],2)
        self.assertEqual(alex['hourly'][10],2)
        self.assertEqual(alex['active_half_hours'],1)
        self.assertEqual([p['counts']['1'] for p in report['timeline']],[2,0])
        self.assertEqual(alex['latest_check']['checked_total'],2)

    def test_accounts_combine_shared_documents_and_preserve_per_run_zeroes(self):
        self.assign(); self.assign(who=2)
        self.add_checks(1,self.account,2); self.add_checks(2,self.account,3)
        with patch.object(activity,'now',return_value=datetime(2026,10,12,15,30,tzinfo=timezone.utc)):
            self.confirm_existing(activity.now())
            activity.record(self.conn,'global-check',sample=True)
            activity.record(self.conn,'global-check',sample=True)
        report = activity.report(self.conn,date(2026,10,12))
        self.assertEqual(len(report['accounts']),1)
        account = report['accounts'][0]
        self.assertEqual(account['id'],self.account)
        self.assertEqual(account['new_checks'],5)
        self.assertEqual(account['hourly'][10],5)
        self.assertEqual([p['counts'][str(self.account)] for p in report['account_timeline']],[5,0])
        scoped = activity.report(self.conn,date(2026,10,12),bidder_id=1)
        self.assertEqual(scoped['accounts'][0]['new_checks'],2)
        self.assertEqual([p['counts'][str(self.account)] for p in scoped['account_timeline']],[2,0])

    def test_existing_checks_have_no_invented_historical_time(self):
        self.assign(); self.add_checks(1,self.account,3)
        self.conn.execute('DELETE FROM sourcing_activity_meta')
        activity.initialize(self.conn)
        with patch.object(activity,'now',return_value=datetime(2026,10,12,15,tzinfo=timezone.utc)):
            activity.record(self.conn,'global-check',sample=True)
        row = activity.report(self.conn,date(2026,10,12))['bidders'][0]
        self.assertEqual(row['new_checks'],0)
        self.assertEqual(row['latest_check']['checked_total'],3)

    def test_manual_changes_are_included_in_next_check_and_bidder_scope_is_private(self):
        self.assign(); self.assign(who=2,account=self.other)
        self.add_checks(1,self.account,1); self.add_checks(2,self.other,2)
        with patch.object(activity,'now',return_value=datetime(2026,10,13,4,59,tzinfo=timezone.utc)):
            self.confirm_existing(activity.now())
            activity.record(self.conn,'manual-edit')
            activity.record(self.conn,'global-check',sample=True)
        self.conn.commit()
        report = activity.report(self.conn,date(2026,10,12),bidder_id=1)
        self.assertEqual(len(report['bidders']),1)
        self.assertEqual(report['bidders'][0]['daily'],[1,0,0,0,0,0,0])
        self.assertEqual(set(report['timeline'][0]['counts']),{'1'})
        sign_in_bidder(self.client,1)
        response = self.client.get('/api/payments/activity?week=2026-10-12')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual([b['id'] for b in response.json()['bidders']],[1])
        self.assertEqual([a['id'] for a in response.json()['accounts']],[self.account])
        self.assertEqual(response.json()['accounts'][0]['new_checks'],1)
        attempted = self.client.get('/api/payments/activity?week=2026-10-12&bidder=2&day=2026-10-12').json()
        self.assertEqual([a['id'] for a in attempted['accounts']],[self.account])
        self.assertEqual(attempted['workday']['runs'][0]['counts'],{'1':1})
        self.assertEqual(attempted['workday']['account_runs'][0]['counts'],{str(self.account):1})
        self.assertEqual(self.client.get('/api/payments/activity?week=2026-10-12&bidder_id=2').json()['bidders'][0]['id'],1)

    def test_workday_has_quarter_hour_points_and_all_runs_across_midnight(self):
        self.assign()
        self.add_checks(1,self.account,1)
        with patch.object(activity,'now',return_value=datetime(2026,10,13,10,59,tzinfo=timezone.utc)):
            self.confirm_existing(activity.now())
            for _ in range(245): activity.record(self.conn,'global-check',sample=True)
            report = activity.report(self.conn,date(2026,10,12),day=date(2026,10,12))
        window = report['workday']
        self.assertEqual(window['start'],'2026-10-12T11:00:00+00:00')
        self.assertEqual(window['end'],'2026-10-13T11:00:00+00:00')
        self.assertEqual(len(window['confirmations']),96)
        self.assertEqual(window['confirmations'][-1]['counts']['1'],1)
        self.assertEqual(len(window['runs']),245)
        self.assertEqual(sum(p['counts']['1'] for p in window['runs']),1)
        self.assertEqual(sum(p['counts'][str(self.account)] for p in window['account_runs']),1)
        other = activity.report(self.conn,date(2026,10,12),day=date(2026,10,13))['workday']
        self.assertEqual(other['runs'],[])
        self.assertEqual(sum(p['counts']['1'] for p in other['confirmations']),0)

    def test_workday_defaults_to_previous_date_before_six_and_handles_dst(self):
        with patch.object(activity,'now',return_value=datetime(2026,11,1,10,tzinfo=timezone.utc)):
            window = activity.report(self.conn,date(2026,10,26))['workday']
        self.assertEqual(window['date'],'2026-10-31')
        self.assertEqual(len(window['confirmations']),100)
