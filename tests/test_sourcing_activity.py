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

    def test_calendar_day_has_quarter_hour_points_and_all_runs_before_midnight(self):
        self.assign()
        self.add_checks(1,self.account,1)
        with patch.object(activity,'now',return_value=datetime(2026,10,13,4,59,tzinfo=timezone.utc)):
            self.confirm_existing(activity.now())
            for _ in range(245): activity.record(self.conn,'global-check',sample=True)
            report = activity.report(self.conn,date(2026,10,12),day=date(2026,10,12))
        window = report['workday']
        self.assertEqual(window['start'],'2026-10-12T05:00:00+00:00')
        self.assertEqual(window['end'],'2026-10-13T05:00:00+00:00')
        self.assertEqual(len(window['confirmations']),96)
        self.assertEqual(window['confirmations'][-1]['counts']['1'],1)
        self.assertEqual(len(window['runs']),245)
        self.assertEqual(sum(p['counts']['1'] for p in window['runs']),1)
        self.assertEqual(sum(p['counts'][str(self.account)] for p in window['account_runs']),1)
        other = activity.report(self.conn,date(2026,10,12),day=date(2026,10,13))['workday']
        self.assertEqual(other['runs'],[])
        self.assertEqual(sum(p['counts']['1'] for p in other['confirmations']),0)

    def test_calendar_day_defaults_to_today_before_six_and_handles_dst(self):
        with patch.object(activity,'now',return_value=datetime(2026,11,1,10,tzinfo=timezone.utc)):
            window = activity.report(self.conn,date(2026,10,26))['workday']
        self.assertEqual(window['date'],'2026-11-01')
        self.assertEqual(len(window['confirmations']),100)

    def test_confirmation_graph_and_payment_table_use_same_completion_day_assignment(self):
        from mailcheck import payments
        self.assign(start=date(2026,10,13)); self.assign(who=2,start=date(2026,10,13))
        self.add_checks(1,self.account,2,day='2026-10-12')
        self.add_checks(2,self.account,3,day='2026-10-12')
        for i in range(10): fixtures.PaymentTests.message(self,'today-'+str(i),stamp='2026-10-13T15:00:00Z')
        self.confirm_existing(datetime(2026,10,13,15,tzinfo=timezone.utc))
        report = activity.report(self.conn,date(2026,10,12),day=date(2026,10,13))
        table = payments.report(self.conn,date(2026,10,12))
        self.assertEqual(report['bidders'][0]['daily'],table['bidders'][0]['checked_daily'])
        self.assertEqual(report['bidders'][0]['daily'],[0,2,0,0,0,0,0])
        self.assertEqual(sum(p['counts']['1'] for p in report['workday']['confirmations']),2)
        self.assertEqual([b['daily'][1] for b in table['bidders']],[4,6])
        self.assertEqual(table['unallocated_daily'],[0]*7)
        self.conn.commit()
        table_api = self.client.get('/api/payments?week=2026-10-12').json()
        graph_api = self.client.get('/api/payments/activity?week=2026-10-12&day=2026-10-13').json()
        self.assertEqual([b['checked_daily'] for b in table_api['bidders']], [b['daily'] for b in graph_api['bidders']])

    def test_graph_does_not_count_links_excluded_from_table(self):
        from mailcheck import payments
        self.assign(end=date(2026,10,12))
        self.add_checks(1,self.account,1)
        self.confirm_existing(datetime(2026,10,13,15,tzinfo=timezone.utc))
        graph = activity.report(self.conn,date(2026,10,12),day=date(2026,10,13))
        table = payments.report(self.conn,date(2026,10,12))
        self.assertEqual(graph['bidders'][0]['daily'],table['bidders'][0]['checked_daily'])
        self.assertEqual(graph['bidders'][0]['new_checks'],0)
        self.assertEqual(sum(p['counts']['1'] for p in graph['workday']['confirmations']),0)

    def test_midnight_boundaries_match_daily_checked_totals(self):
        from mailcheck import payments
        self.assign()
        self.add_checks(1,self.account,4)
        rows=self.conn.execute(activity._CHECKED_ROWS).fetchall()
        stamps=['2026-10-12T04:59:00+00:00','2026-10-12T05:00:00+00:00','2026-10-13T04:59:00+00:00','2026-10-13T05:00:00+00:00']
        for row,stamp in zip(rows,stamps):
            activity.confirm(self.conn,row['row_id'],datetime.fromisoformat(stamp),'receipt-'+row['row_id'])
        graph=activity.report(self.conn,date(2026,10,12),day=date(2026,10,12))
        table=payments.report(self.conn,date(2026,10,12))
        total=sum(p['counts']['1'] for p in graph['workday']['confirmations'])
        self.assertEqual(total,2)
        self.assertEqual(graph['workday']['confirmations'][0]['counts']['1'],1)
        self.assertEqual(graph['workday']['confirmations'][-1]['counts']['1'],1)
        self.assertEqual(total,table['bidders'][0]['checked_daily'][0])
        self.assertEqual(sum(p['counts'][str(self.account)] for p in graph['workday']['account_confirmations']),2)

    def test_spring_forward_day_uses_actual_midnight_bounds(self):
        window=activity.report(self.conn,date(2026,3,2),day=date(2026,3,8))['workday']
        self.assertEqual(window['start'],'2026-03-08T06:00:00+00:00')
        self.assertEqual(window['end'],'2026-03-09T05:00:00+00:00')
        self.assertEqual(len(window['confirmations']),92)

    def test_activity_reuses_confirmation_events_for_day_inside_week(self):
        from mailcheck import sourcing_verification
        self.assign()
        self.add_checks(1,self.account,1)
        self.confirm_existing(datetime(2026,10,12,15,tzinfo=timezone.utc))
        with patch.object(sourcing_verification,'confirmation_events',wraps=sourcing_verification.confirmation_events) as events:
            result=activity.report(self.conn,date(2026,10,12),day=date(2026,10,12))
        self.assertEqual(events.call_count,1)
        self.assertEqual(sum(p['counts']['1'] for p in result['workday']['confirmations']),1)

    def test_checkpoint_samples_are_loaded_with_one_query(self):
        self.assign()
        self.add_checks(1,self.account,1)
        with patch.object(activity,'now',return_value=datetime(2026,10,12,15,tzinfo=timezone.utc)):
            for _ in range(4):activity.record(self.conn,'global-check',sample=True)
        statements=[]
        self.conn.set_trace_callback(statements.append)
        try:
            result=activity.report(self.conn,date(2026,10,12),day=date(2026,10,12))
        finally:self.conn.set_trace_callback(None)
        queries=[sql for sql in statements if sql.startswith('SELECT ') and 'FROM sourcing_activity_samples WHERE' in sql]
        self.assertLessEqual(len(queries),1)
        self.assertEqual(len(result['workday']['runs']),4)
        self.assertEqual(sum(p['counts']['1'] for p in result['workday']['runs']),1)

    def test_default_graph_date_stays_inside_selected_historical_week(self):
        with patch.object(activity,'now',return_value=datetime(2026,10,29,18,tzinfo=timezone.utc)):
            report=activity.report(self.conn,date(2026,10,12))
        self.assertEqual(report['workday']['date'],'2026-10-12')

    def test_explicit_day_outside_week_still_has_its_own_confirmation_data(self):
        self.assign()
        self.add_checks(1,self.account,1,day='2026-10-20')
        self.confirm_existing(datetime(2026,10,20,15,tzinfo=timezone.utc))
        report=activity.report(self.conn,date(2026,10,12),day=date(2026,10,20))
        self.assertEqual(sum(p['counts']['1'] for p in report['workday']['confirmations']),1)
        self.assertEqual(report['bidders'][0]['new_checks'],0)
