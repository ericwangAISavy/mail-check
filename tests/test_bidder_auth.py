"""Named bidder sessions must never inherit the old shared guest permissions."""
from unittest.mock import patch
import unittest
from tests import test_frontend_api as fixtures
from mailcheck import db


class BidderAuthTests(unittest.TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('Alex','2026-01-01')")
        self.conn.execute("INSERT INTO bidders(name,created_at) VALUES('Blair','2026-01-01')")
        self.conn.commit()

    def test_named_login_and_private_scope(self):
        response=self.client.post('/api/auth/bidders/1/password',json={'password':'alex-password','enabled':True})
        self.assertEqual(response.status_code,200,response.text)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.client.get('/api/auth/bidders').json(),{'bidders':[{'id':1,'name':'Alex'}]})
        response=self.client.post('/api/auth/login',json={'role':'bidder','bidder_id':1,'password':'alex-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['bidder_id'],1)
        for path in ('/api/dashboard','/api/accounts','/api/triage','/api/interviews'):
            self.assertEqual(self.client.get(path).status_code,403,path)
        report=self.client.get('/api/payments').json()
        self.assertEqual([b['name'] for b in report['bidders']],['Alex'])
        self.assertEqual(report['accounts'],[])

    def test_password_change_rotates_bidder_session(self):
        self.client.post('/api/auth/bidders/1/password',json={'password':'alex-password','enabled':True})
        self.client.post('/api/auth/login',json={'role':'bidder','bidder_id':1,'password':'alex-password'})
        old=self.client.cookies.get('mailcheck_session')
        response=self.client.post('/api/auth/password/self',json={'current_password':'alex-password','password':'new-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotEqual(old,self.client.cookies.get('mailcheck_session'))
        self.assertEqual(self.client.get('/api/auth/session').json()['role'],'bidder')
        self.client.cookies.set('mailcheck_session',old)
        self.assertEqual(self.client.get('/api/payments').status_code,401)

    def test_shared_guest_login_is_retired(self):
        response=self.client.post('/api/auth/login',json={'role':'guest','password':'guest'})
        self.assertIn(response.status_code,(401,422))
    def test_disabling_login_invalidates_an_active_session(self):
        self.client.post('/api/auth/bidders/1/password',json={'password':'alex-password'})
        self.client.post('/api/auth/login',json={'role':'bidder','bidder_id':1,'password':'alex-password'})
        self.conn.execute('UPDATE bidders SET login_enabled=0 WHERE id=1');self.conn.commit()
        self.assertEqual(self.client.get('/api/sourcing').status_code,401)
        self.assertIsNone(self.client.get('/api/auth/session').json()['role'])
    def test_own_password_rotation_does_not_depend_on_login_throttle(self):
        self.client.post('/api/auth/bidders/1/password',json={'password':'alex-password'})
        self.client.post('/api/auth/login',json={'role':'bidder','bidder_id':1,'password':'alex-password'})
        for _ in range(10):self.client.post('/api/auth/login',json={'role':'admin','password':'wrong'})
        response=self.client.post('/api/auth/password/self',json={'current_password':'alex-password','password':'updated-password'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.client.get('/api/auth/session').json()['role'],'bidder')
