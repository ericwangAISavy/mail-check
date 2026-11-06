from datetime import datetime,timedelta,timezone
import unittest
from unittest.mock import patch
import time
from fastapi.testclient import TestClient as WorkerClient
from mailcheck import db,payments
from mailcheck.models import Classification
from mailcheck.web.app import create_app
from tests import test_payments as fixtures
from tests.web_client import sign_in_bidder


class BidderInboxTests(unittest.TestCase):
    setUp=fixtures.PaymentTests.setUp
    assign=fixtures.PaymentTests.assign
    message=fixtures.PaymentTests.message

    def prepare(self):
        self.assign(start=payments.today()-timedelta(days=1))
        stamp=datetime.now(timezone.utc).isoformat()
        mine=self.message('mine-code',stamp=stamp,category='info_request')
        forbidden=self.message('mine-private',stamp=stamp,category='interview_invite')
        other=self.message('other-code',stamp=stamp,category='info_request',account=self.other)
        self.conn.commit()
        return mine,forbidden,other

    def test_list_reader_and_done_are_scoped_for_local_and_worker_bidders(self):
        mine,forbidden,other=self.prepare()
        sign_in_bidder(self.client)
        with WorkerClient(create_app(worker_secret='trusted')) as worker:
            headers={'x-offerpath-worker':'trusted','x-offerpath-viewer':'bidder','x-offerpath-bidder':'1'}
            for client,extra in ((self.client,{}),(worker,{'headers':headers})):
                data=client.get('/api/triage?category=interview_invite&days=90&view=all',**extra).json()
                self.assertEqual(data['selected_category'],'info_request')
                self.assertEqual([m['pk'] for g in data['groups'] for m in g['items']],[mine])
                self.assertEqual(data['accounts'],[{'label':'personal','enabled':True}])
                self.assertEqual(set(data['counts']),{'info_request'})
                self.assertEqual(data['summary']['done'],0)
                self.assertEqual(client.get('/api/triage?days=90&account=work',**extra).json()['total'],0)
                reader=client.get(f'/api/messages/{mine}',**extra).json()
                self.assertIn('Thanks',reader['body_html'])
                self.assertIsNone(reader['message']['open_url'])
                self.assertIsNone(reader['message']['provider_url'])
                self.assertEqual(reader['replies'],[])
                for pk in (forbidden,other,999999):
                    self.assertEqual(client.get(f'/api/messages/{pk}',**extra).status_code,404)
                    self.assertEqual(client.post(f'/api/messages/{pk}/handled',**extra).status_code,404)
                for path in (f'/api/messages/{mine}/reply', '/api/reclassify','/api/messages/undo-last'):
                    self.assertEqual(client.post(path,json={},**extra).status_code,403)
                for suffix in ('reply','body','reader'):
                    self.assertEqual(client.get(f'/api/messages/{mine}/{suffix}',**extra).status_code,403)
                done=client.post(f'/api/messages/{mine}/handled?done=true',**extra)
                self.assertEqual(done.status_code,200,done.text)
                self.assertEqual(set(done.json()['summary']),{'actionable','informational','done'})
                self.assertEqual(done.json()['summary']['done'],1)
                self.assertEqual(client.get('/api/triage?days=90',**extra).json()['total'],0)
                self.assertEqual(client.get('/api/triage?view=completed&days=90',**extra).json()['total'],1)
                self.assertEqual(client.post(f'/api/messages/{mine}/handled?done=false',**extra).status_code,200)
        self.assertIsNone(db.get_message(self.conn,forbidden)['handled_at'])
        self.assertIsNone(db.get_message(self.conn,other)['handled_at'])

    def test_reassignment_and_reclassification_revoke_access_immediately(self):
        mine,_,_=self.prepare()
        sign_in_bidder(self.client)
        self.assertEqual(self.client.get(f'/api/messages/{mine}').status_code,200)
        self.conn.execute('UPDATE bidder_assignments SET end_date=?',( (payments.today()-timedelta(days=1)).isoformat(),))
        self.conn.commit()
        self.assertEqual(self.client.get('/api/triage?days=90').json()['accounts'],[])
        self.assertEqual(self.client.get(f'/api/messages/{mine}').status_code,404)
        self.assertEqual(self.client.post(f'/api/messages/{mine}/handled').status_code,404)
        self.conn.execute('UPDATE bidder_assignments SET end_date=NULL');self.conn.commit()
        db.save_classification(self.conn,mine,Classification(category='other'),'test','1')
        self.assertEqual(self.client.get(f'/api/messages/{mine}').status_code,404)
        self.assertEqual(self.client.get('/api/triage?days=90').json()['total'],0)

    def test_future_assignments_do_not_grant_inbox_access(self):
        self.assign(start=payments.today()+timedelta(days=1))
        mine=self.message('future-code',category='info_request');self.conn.commit()
        sign_in_bidder(self.client)
        self.assertEqual(self.client.get('/api/triage?days=90').json()['total'],0)
        self.assertEqual(self.client.get(f'/api/messages/{mine}').status_code,404)

    def test_schedule_is_available_without_exposing_job_details(self):
        self.prepare()
        sign_in_bidder(self.client)
        from mailcheck.web import app as web
        cfg = web.cfgmod.load()
        cfg.watch.auto_check = True
        due = time.time()+300
        with patch.object(web.cfgmod, 'load', return_value=cfg), patch.dict(web._sched, next_due=due):
            schedule=self.client.get('/api/triage').json()['check_schedule']
            self.assertEqual(set(schedule), {'automatic','running','next_at'})
            self.assertTrue(schedule['automatic'])
            self.assertAlmostEqual(datetime.fromisoformat(schedule['next_at']).timestamp(), due, places=5)
            cfg.watch.auto_check=False
            schedule=self.client.get('/api/triage').json()['check_schedule']
            self.assertFalse(schedule['automatic'])
            self.assertIsNone(schedule['next_at'])
        self.assertEqual(self.client.get('/api/status').status_code,403)
