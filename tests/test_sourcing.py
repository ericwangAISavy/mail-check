"""Ownership and conflict behavior using a synthetic shared Google workbook."""
import copy
import unittest
from tests import test_frontend_api as fixtures
from tests.web_client import sign_in_bidder
from mailcheck import sourcing

class FakeSheets:
    def __init__(self):
        self.writes=[]
        self.current={'title':'Profile','revision':'one','rows':[[{'value':'Company','display':'Company','formula':False}],[{'value':'Acme','display':'Acme','formula':False}]],'properties':{'gridProperties':{'rowCount':100,'columnCount':3}}}
    def snapshot(self,*args): return copy.deepcopy(self.current)
    def write(self,book,patches): self.writes.append(patches);self.current['revision']='two'

class SourcingTests(unittest.TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)
        sourcing.initialize(self.conn)
        for name in ('Alex','Blair'): self.conn.execute("INSERT INTO bidders(name,created_at) VALUES(?, '2026-01-01')",(name,))
        for bidder in (1,2):
            self.conn.execute('INSERT INTO sourcing_books(id,bidder_id,spreadsheet_id,title) VALUES(?,?,?,?)',(bidder,bidder,str(bidder),'Book'))
            self.conn.execute('INSERT INTO sourcing_tabs(id,book_id,sheet_id,account_id,title) VALUES(?,?,?,?,?)',(bidder,bidder,12,self.account_id,'Profile'))
        self.conn.commit()
        self.google=FakeSheets();self.client.app.state.sheets_client=self.google
    def test_owner_check_precedes_google_and_cache(self):
        sign_in_bidder(self.client,1)
        self.assertEqual(len(self.client.get('/api/sourcing').json()['books']),1)
        self.assertEqual(self.client.get('/api/sourcing/tabs/2').status_code,404)
        body={'operation':'00000000-0000-0000-0000-000000000001','revision':'one','changes':[{'row':1,'col':0,'value':'new'}]}
        self.assertEqual(self.client.post('/api/sourcing/tabs/2/save',json=body).status_code,404)
        self.assertEqual(self.client.get('/api/sourcing/books/2/metadata').status_code,403)
        self.assertEqual(self.google.writes,[])
    def test_conflict_and_idempotent_save(self):
        body={'operation':'00000000-0000-0000-0000-000000000001','revision':'old','changes':[{'row':1,'col':0,'value':'=literal'}]}
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/save',json=body).status_code,409)
        self.assertEqual(self.google.writes,[])
        body['revision']='one'
        result=self.client.post('/api/sourcing/tabs/1/save',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/save',json=body).status_code,200)
        self.assertEqual(len(self.google.writes),1)
    def test_search_is_owner_scoped(self):
        self.client.get('/api/sourcing/tabs/1');self.client.get('/api/sourcing/tabs/2')
        sign_in_bidder(self.client,1)
        results=self.client.get('/api/sourcing/search?q=acme').json()['results']
        self.assertEqual([r['bidder'] for r in results],['Alex'])
    def test_formula_and_header_are_never_written(self):
        self.google.current['rows'][1][0]['formula']=True
        for row in (0,1):
            result=self.client.post('/api/sourcing/tabs/1/save',json={'operation':'00000000-0000-0000-0000-000000000001','revision':'one','changes':[{'row':row,'col':0,'value':'erase'}]})
            self.assertEqual(result.status_code,400,result.text)
        self.assertEqual(self.google.writes,[])
    def test_deleted_profile_preserves_historical_sheet(self):
        self.conn.execute("UPDATE sourcing_tabs SET account_label='personal' WHERE id=1");self.conn.commit()
        from mailcheck import db
        db.remove_account(self.conn,'personal');self.conn.commit()
        tab=self.conn.execute('SELECT * FROM sourcing_tabs WHERE id=1').fetchone()
        self.assertIsNone(tab['account_id']);self.assertEqual(tab['account_label'],'personal')
    def test_ambiguous_append_is_not_replayed(self):
        from mailcheck.google_sheets import GoogleError
        calls=[]
        def fail(*args):calls.append(args);raise GoogleError('Connection lost after submission.')
        self.google.append=fail
        body={'operation':'00000000-0000-0000-0000-000000000001','revision':'one','rows':[['New','Engineer','https://jobs.test/1']]}
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/append',json=body).status_code,502)
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/append',json=body).status_code,502)
        body['operation']='00000000-0000-0000-0000-000000000002'
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/append',json=body).status_code,502)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/review').status_code,200)
    def test_hyperlink_labels_are_searchable_as_real_urls(self):
        self.google.current['rows'][1].extend([{'value':'Engineer','display':'Engineer','formula':False},{'value':'Apply','display':'Apply','formula':False,'link':'https://jobs.example.test/actual'}])
        self.client.get('/api/sourcing/tabs/1')
        result=self.client.get('/api/sourcing/search?q=actual').json()['results']
        self.assertEqual(result[0]['link'],'https://jobs.example.test/actual')
    def test_acknowledged_append_recovers_if_post_write_refresh_fails(self):
        from mailcheck.google_sheets import GoogleError
        original=self.google.snapshot
        acknowledged=False;calls=[]
        def append(*args):
            nonlocal acknowledged
            acknowledged=True;calls.append(args)
            return {'updates':{'updatedRange':"'Profile'!A3:C3"}}
        def snapshot(*args):
            if acknowledged:raise GoogleError('Temporary read failure after successful append.')
            return original(*args)
        self.google.append=append;self.google.snapshot=snapshot
        body={'operation':'00000000-0000-0000-0000-000000000001','revision':'one','rows':[['New','Engineer','https://jobs.test/1']]}
        self.assertEqual(self.client.post('/api/sourcing/tabs/1/append',json=body).status_code,502)
        record=self.conn.execute('SELECT google_result FROM sourcing_operations').fetchone()
        self.assertIn("A3:C3",record['google_result'])
        self.google.snapshot=original
        result=self.client.post('/api/sourcing/tabs/1/append',json=body)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(len(calls),1)
