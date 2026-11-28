from datetime import date
import json
import unittest

from mailcheck import db,payments
from mailcheck.models import Classification
from tests import test_payments as fixtures


class ConfirmationCountsTests(unittest.TestCase):
    setUp=fixtures.PaymentTests.setUp
    assign=fixtures.PaymentTests.assign
    message=fixtures.PaymentTests.message
    report=fixtures.PaymentTests.report
    def confirmation(self,key,day,company='Acme',role='Senior Engineer',job_id=None,account=None):
        pk=self.message(key,f'2026-10-{day:02d}T15:00:00Z',account=account)
        if job_id:
            self.conn.execute('UPDATE messages SET body_text=? WHERE id=?',(f'Job ID: {job_id}',pk))
        db.save_classification(self.conn,pk,Classification('application_ack',company=company,role=role),'model','v1')
        return pk

    def test_duplicate_confirmation_emails_count_as_one_application(self):
        self.assign()
        self.confirmation('first',13,job_id='12345')
        self.confirmation('second',13,company='ACME, Inc.',role='Sr. Engineer',job_id='12345')
        self.confirmation('third',13,job_id='12345')
        row=self.report()['bidders'][0]
        self.assertEqual(row['daily'],[0,1,0,0,0,0,0])
        self.assertEqual(row['received_reply_total'],1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM application_receipts').fetchone()[0],3)

    def test_different_roles_job_ids_and_profiles_remain_separate(self):
        self.assign();self.assign(account=self.other)
        self.confirmation('a',13,job_id='12345')
        self.confirmation('b',13,job_id='67890')
        self.confirmation('c',13,role='Designer')
        self.confirmation('d',13,job_id='12345',account=self.other)
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],4)

    def test_role_only_and_company_only_replies_do_not_inflate_a_clear_application(self):
        self.assign()
        self.confirmation('first',13)
        self.confirmation('second',13,role='Sr Engineer',company='ACME LLC')
        self.confirmation('generic',13,role=None)
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],1)

    def test_confirmations_on_different_days_and_weeks_count_separately(self):
        self.assign(start=date(2026,10,1))
        self.confirmation('first',11)
        self.confirmation('duplicate',12)
        self.assertEqual(self.report(date(2026,10,5))['bidders'][0]['received_reply_total'],1)
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],1)
        self.confirmation('next-day',13)
        self.assertEqual(self.report()['bidders'][0]['daily'][:2],[1,1])

    def test_ambiguous_generic_reply_and_different_reference_sets_are_not_guessed(self):
        self.assign()
        first=self.confirmation('a',13,job_id='12345')
        second=self.confirmation('b',13,job_id='67890')
        for pk in (first,second):
            self.conn.execute("UPDATE messages SET body_text=body_text || ' Job ID: 99999' WHERE id=?",(pk,))
        self.confirmation('generic',13,role=None)
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],3)

    def test_later_application_and_retained_job_identity(self):
        self.assign(start=date(2026,10,1))
        self.confirmation('first',12,job_id='12345')
        self.confirmation('second-job',13,job_id='67890')
        self.confirmation('duplicate',12,job_id='12345')
        self.confirmation('later',23,job_id='12345')
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],2)
        self.assertEqual(self.report(date(2026,10,19))['bidders'][0]['received_reply_total'],1)
        db.prune_messages(self.conn,before_iso='2027-01-01')
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],2)
        refs=self.conn.execute('SELECT job_refs FROM application_receipts WHERE message_id="first"').fetchone()[0]
        self.assertEqual(json.loads(refs),['12345'])

    def test_shared_recommended_job_does_not_merge_different_roles(self):
        self.assign()
        for key,role in [('engineer','Engineer'),('designer','Designer')]:
            pk=self.confirmation(key,13,role=role)
            self.conn.execute('UPDATE messages SET body_text=? WHERE id=?',
                ('Other opening: https://job-boards.greenhouse.io/acme/jobs/99999',pk))
        self.assertEqual(self.report()['bidders'][0]['received_reply_total'],2)

    def test_duplicate_date_uses_chicago_day_rather_than_utc_day(self):
        self.assign()
        for key,stamp in [('before','2026-10-13T04:59:00Z'),('after','2026-10-13T05:01:00Z'),('duplicate','2026-10-14T00:01:00Z')]:
            pk=self.message(key,stamp)
            db.save_classification(self.conn,pk,Classification('application_ack',company='Acme',role='Engineer'),'model','v1')
        self.assertEqual(self.report()['bidders'][0]['daily'][:2],[1,1])
