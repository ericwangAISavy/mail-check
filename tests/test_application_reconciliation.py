"""Synthetic SQLite receipt reconciliation; no mailbox data or writes."""
import unittest
from datetime import date
from mailcheck import db


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(':memory:')
        self.addCleanup(self.conn.close)
        self.account = db.add_account(self.conn, label='private-label', email=' TEST@example.test ')
        for who in (1, 2):
            self.conn.execute("INSERT INTO bidders(id,name,created_at) VALUES(?,?,'2026-01-01')", (who,str(who)))
            self.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(?,?,'private-label','2026-10-01')", (who,self.account))
            self.conn.execute("INSERT INTO native_books(id,bidder_id,title) VALUES(?,?,'book')",(who,who))
            self.conn.execute("INSERT INTO native_tabs(id,book_id,account_id,account_label,title,updated_at) VALUES(?,?,?,'private-label','tab',0)",(who,who,self.account))
            for kind in ('company','role','link','check'):
                self.conn.execute("INSERT INTO native_columns(id,tab_id,position,title,kind) VALUES(?,?,0,?,?)",(f'{who}-{kind}',who,kind,kind))

    def receipt(self, key, company='Acme', role='Engineer', stamp='2026-10-12T05:00:00Z', account=None):
        self.conn.execute("INSERT OR REPLACE INTO application_receipts(account_id,message_id,received_at,category,company,role) VALUES(?,?,?,'application_ack',?,?)",(account or self.account,key,stamp,company,role))

    def row(self, key, receipt=None, link='https://jobs.test/job?id=1', who=1, role='Engineer'):
        self.conn.execute("INSERT INTO native_rows(id,tab_id,position,work_date) VALUES(?,?,0,'2026-10-12')",(key,who))
        for kind,value in [('company','Acme'),('role',role),('link',link),('check','true')]:
            self.conn.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)',(key,f'{who}-{kind}',value))
        self.conn.execute("INSERT INTO sourcing_check_activity(row_id,bidder_id,account_id,work_date,source,confirmed_at,message_id) VALUES(?,?,?,'2026-10-12',?,?,?)",(key,who,self.account,'confirmation' if receipt else 'manual-edit','2026-10-12T05:00:00Z' if receipt else None,receipt))

    def report(self, **kwargs):
        from mailcheck.application_reconciliation import reconcile
        result = reconcile(self.conn,date(2026,10,12),date(2026,10,18),**kwargs)
        self.assertEqual(result['raw_receipts'],sum(result[k] for k in ('verified_applications','possible_extra_confirmations','unmatched_receipts')))
        return result

    def test_repeated_fetch_two_receipts_one_verified_and_read_only(self):
        self.receipt('a'); self.receipt('a'); self.receipt('b'); self.row('r','a')
        before = self.conn.total_changes
        self.conn.execute('PRAGMA query_only=ON')
        report = self.report()
        self.assertEqual((report['raw_receipts'],report['verified_applications'],report['possible_extra_confirmations']), (2,1,1))
        self.assertEqual(report['bidders'][1]['verified_daily'],[1,0,0,0,0,0,0])
        self.assertEqual(self.conn.total_changes,before)

    def test_conflicting_claims_across_bidders_never_credit(self):
        self.receipt('a'); self.row('r','a'); self.row('s','a',who=2)
        report=self.report(bidder_id=1)
        self.assertEqual(report['verified_applications'],0)
        self.assertEqual(report['accounts'][0]['conflicting_receipt_rows'],1)
        self.assertEqual(set(report['bidders']),{1})

    def test_canonical_duplicate_urls_never_credit_but_job_ids_stay_distinct(self):
        self.receipt('a'); self.receipt('b'); self.row('r','a'); self.row('s','b',link='http://JOBS.test/job/?utm_source=x&id=1')
        self.assertEqual(self.report()['accounts'][0]['duplicate_link_rows'],2)
        self.assertEqual(self.report()['verified_applications'],0)
        self.conn.execute("UPDATE native_cells SET value='https://jobs.test/job?id=2' WHERE row_id='s' AND column_id='1-link'")
        self.assertEqual(self.report()['verified_applications'],2)

    def test_blank_metadata_and_different_roles_are_not_possible_extras(self):
        self.receipt('a'); self.receipt('b',role=''); self.receipt('c',role='Designer'); self.row('r','a')
        report=self.report()
        self.assertEqual(report['possible_extra_confirmations'],0)
        self.assertEqual(report['accounts'][0]['missing_metadata_receipts'],1)
        self.assertEqual(report['unmatched_receipts'],2)

    def test_date_scope_duplicate_connections_and_manual_checks(self):
        duplicate=db.add_account(self.conn,label='other',email='test@EXAMPLE.test')
        unrelated=db.add_account(self.conn,label='hidden',email='hidden@example.test')
        self.receipt('outside',stamp='2026-10-12T04:59:59Z')
        self.receipt('inside'); self.receipt('hidden',account=unrelated); self.row('manual')
        report=self.report(bidder_id=1)
        self.assertEqual(report['raw_receipts'],1)
        self.assertEqual(report['duplicate_connection_groups'],0) # inaccessible duplicate does not leak
        self.assertEqual([a['account_id'] for a in report['accounts']],[self.account])
        self.assertEqual(report['accounts'][0]['review_reason_counts']['manual_checks'],1)
        self.assertEqual(self.report()['duplicate_connection_groups'],1)

    def test_distinct_requisition_ids_and_metadata_disagreement_preserve_claims(self):
        self.receipt('a'); self.receipt('b')
        self.row('r','a',link='https://jobs.test/job?jr_id=1',role='Designer')
        self.row('s','b',link='https://jobs.test/job?jr_id=2')
        report=self.report()
        self.assertEqual(report['verified_applications'],2)
        self.assertEqual(report['accounts'][0]['review_reason_counts']['metadata_mismatch_rows'],1)

    def test_wrong_event_date_is_reviewed_without_moving_recorded_completion(self):
        self.receipt('a'); self.row('r','a')
        self.conn.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-10-13T12:00:00Z'")
        report=self.report()
        self.assertEqual(report['verified_applications'],0)
        self.assertEqual(report['accounts'][0]['review_reason_counts']['receipt_date_mismatch_rows'],1)

    def test_receipt_day_not_source_day_and_assignment_date_filter(self):
        self.receipt('a',stamp='2026-10-14T05:00:00Z'); self.row('r','a')
        self.conn.execute("UPDATE native_rows SET work_date='2026-09-01'")
        self.conn.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-10-14T05:00:00Z'")
        self.assertEqual(self.report()['bidders'][1]['verified_daily'],[0,0,1,0,0,0,0])
        self.conn.execute("UPDATE bidder_assignments SET end_date='2026-10-13' WHERE bidder_id=1")
        self.assertEqual(self.report(bidder_id=1)['raw_receipts'],0)
        self.assertEqual(self.report(bidder_id=1)['verified_applications'],0)

    def test_dst_receipt_boundary_uses_chicago_calendar_day(self):
        from mailcheck.application_reconciliation import reconcile
        self.receipt('sunday',stamp='2026-11-02T05:59:59Z')
        self.receipt('monday',stamp='2026-11-02T06:00:00Z')
        self.row('r','sunday')
        self.conn.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-11-02T05:59:59Z'")
        report=reconcile(self.conn,date(2026,10,26),date(2026,11,1))
        self.assertEqual(report['raw_receipts'],1)
        self.assertEqual(report['bidders'][1]['verified_daily'],[0,0,0,0,0,0,1])

    def test_removed_accounts_keep_receipts_and_assignment_label(self):
        self.receipt('a')
        self.conn.execute('DELETE FROM accounts WHERE id=?',(self.account,))
        for kwargs in ({}, {'bidder_id':1}):
            report=self.report(**kwargs)
            self.assertEqual(report['raw_receipts'],1)
            self.assertEqual(report['unmatched_receipts'],1)
            self.assertEqual(report['accounts'][0]['account_label'],'private-label')

    def test_same_first_company_word_is_not_possible_extra(self):
        self.receipt('a',company='First National'); self.row('r','a')
        self.receipt('b',company='First Citizens')
        self.assertEqual(self.report()['possible_extra_confirmations'],0)

    def test_full_company_and_role_metadata_keep_numbers_and_safe_aliases(self):
        self.receipt('a',role='Senior Engineer 2'); self.row('r','a',role='Senior Engineer 2')
        self.receipt('b',role='Sr. Engineer 2'); self.receipt('c',role='Senior Engineer 3')
        report=self.report()
        self.assertEqual(report['possible_extra_confirmations'],1)
        self.assertEqual(report['unmatched_receipts'],1)

    def test_historical_checked_same_url_requires_review_without_moving_receipts(self):
        self.receipt('old',stamp='2026-10-05T12:00:00Z')
        self.receipt('current')
        self.row('old-row','old',link='http://JOBS.test/job/?utm_source=old&id=1')
        self.row('new-row','current')
        self.conn.execute("UPDATE native_rows SET work_date='2026-10-05' WHERE id='old-row'")
        self.conn.execute("UPDATE sourcing_check_activity SET confirmed_at='2026-10-05T12:00:00Z',work_date='2026-10-05' WHERE row_id='old-row'")
        report=self.report()
        self.assertEqual(report['raw_receipts'],1)
        self.assertEqual(report['verified_applications'],0)
        self.assertEqual(report['accounts'][0]['duplicate_link_rows'],1)
        self.assertEqual(report['ambiguous_rows'],1)
        self.conn.execute("UPDATE native_cells SET value='https://jobs.test/job?id=2' WHERE row_id='old-row' AND column_id='1-link'")
        self.assertEqual(self.report()['verified_applications'],1)
