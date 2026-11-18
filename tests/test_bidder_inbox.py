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
        invite=self.message('mine-invite',stamp=stamp,category='interview_invite')
        other=self.message('other-code',stamp=stamp,category='info_request',account=self.other)
        self.conn.commit()
        return mine,invite,other

    def test_list_reader_and_done_are_scoped_for_local_and_worker_bidders(self):
        mine,invite,other=self.prepare()
        sign_in_bidder(self.client)
        with WorkerClient(create_app(worker_secret='trusted')) as worker:
            headers={'x-offerpath-worker':'trusted','x-offerpath-viewer':'bidder','x-offerpath-bidder':'1'}
            for client,extra in ((self.client,{}),(worker,{'headers':headers})):
                data=client.get('/api/triage?days=90&view=all',**extra).json()
                self.assertIsNone(data['selected_category'])
                self.assertEqual({m['pk'] for g in data['groups'] for m in g['items']},{mine,invite})
                self.assertEqual(data['accounts'],[{'label':'personal','enabled':True}])
                self.assertEqual(data['counts'],{'info_request':1,'interview_invite':1})
                filtered=client.get('/api/triage?category=interview_invite&days=90&view=all',**extra).json()
                self.assertEqual(filtered['selected_category'],'interview_invite')
                self.assertEqual([m['pk'] for g in filtered['groups'] for m in g['items']],[invite])
                self.assertEqual(data['summary']['done'],0)
                self.assertEqual(client.get('/api/triage?days=90&account=work',**extra).json()['total'],0)
                reader=client.get(f'/api/messages/{mine}',**extra).json()
                self.assertIn('Thanks',reader['body_html'])
                self.assertIsNone(reader['message']['open_url'])
                self.assertIsNone(reader['message']['provider_url'])
                self.assertEqual(reader['replies'],[])
                for pk in (other,999999):
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
                self.assertEqual(client.get('/api/triage?days=90',**extra).json()['total'],1)
                self.assertEqual(client.get('/api/triage?view=completed&days=90',**extra).json()['total'],1)
                self.assertEqual(client.post(f'/api/messages/{mine}/handled?done=false',**extra).status_code,200)
        self.assertIsNone(db.get_message(self.conn,invite)['handled_at'])
        self.assertIsNone(db.get_message(self.conn,other)['handled_at'])

    def test_every_category_is_visible_and_filterable_for_assigned_accounts(self):
        mine, invite, other = self.prepare()
        stamp = datetime.now(timezone.utc).isoformat()
        ack = self.message('my-confirmation', stamp=stamp, category='application_ack')
        other_ack = self.message('other-confirmation', stamp=stamp, category='application_ack', account=self.other)
        self.conn.commit()
        sign_in_bidder(self.client)
        data = self.client.get('/api/triage?view=all&days=90').json()
        self.assertEqual({m['pk'] for g in data['groups'] for m in g['items']}, {mine, invite, ack})
        self.assertEqual(data['summary']['actionable'], 3)
        filtered = self.client.get('/api/triage?category=application_ack&days=90').json()
        self.assertEqual([m['pk'] for g in filtered['groups'] for m in g['items']], [ack])
        self.assertEqual(self.client.get(f'/api/messages/{ack}').status_code, 200)
        self.assertEqual(self.client.get(f'/api/messages/{other_ack}').status_code, 404)
        handled = self.client.post(f'/api/messages/{ack}/handled?done=true')
        self.assertEqual(handled.status_code, 200)
        self.assertEqual(handled.json()['summary']['done'], 1)

    def test_reassignment_and_disabled_accounts_revoke_access_but_reclassification_does_not(self):
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
        self.conn.commit()
        self.assertEqual(self.client.get(f'/api/messages/{mine}').status_code,200)
        self.conn.execute('UPDATE accounts SET enabled=0 WHERE id=?',(self.account,));self.conn.commit()
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


class BidderTimelineTests(unittest.TestCase):
    setUp=fixtures.PaymentTests.setUp
    assign=fixtures.PaymentTests.assign
    message=fixtures.PaymentTests.message

    def test_inbox_is_one_timeline_newest_first_regardless_of_category(self):
        self.assign(start=payments.today()-timedelta(days=1))
        now=datetime.now(timezone.utc)
        stamp=lambda hours:(now-timedelta(hours=hours)).isoformat()
        oldest_offer=self.message('offer',stamp=stamp(5),category='offer')
        newest_ack=self.message('ack',stamp=stamp(1),category='application_ack')
        middle_invite=self.message('invite',stamp=stamp(3),category='interview_invite')
        noise=self.message('noise',stamp=stamp(2),category='newsletter')
        self.conn.commit()
        sign_in_bidder(self.client)
        expected=[newest_ack,noise,middle_invite,oldest_offer]
        for view in ('queue','all'):
            data=self.client.get(f'/api/triage?view={view}&days=90').json()
            self.assertEqual([g['tier'] for g in data['groups']],['all'])
            self.assertEqual([m['pk'] for m in data['groups'][0]['items']],expected)
        # Completed keeps received order too, not the order messages were marked done.
        for pk in (oldest_offer,newest_ack,middle_invite,noise):
            self.assertEqual(self.client.post(f'/api/messages/{pk}/handled?done=true').status_code,200)
            time.sleep(0.01)
        done=self.client.get('/api/triage?view=completed&days=90').json()
        self.assertEqual([m['pk'] for g in done['groups'] for m in g['items']],expected)

    def test_empty_bidder_inbox_has_no_groups(self):
        self.assign(start=payments.today()-timedelta(days=1))
        sign_in_bidder(self.client)
        self.assertEqual(self.client.get('/api/triage?days=90').json()['groups'],[])
