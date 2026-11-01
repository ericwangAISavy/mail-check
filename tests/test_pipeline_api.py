"""Real API, SQLite, authorization and request retries for opportunities."""
import unittest
import uuid
from tests import test_frontend_api as fixtures
from tests.web_client import sign_in_bidder


def operation(**values):
    return {'operation':str(uuid.uuid4()),**values}


class PipelineApiTests(unittest.TestCase):
    setUp=fixtures.FrontendApiTests.setUp

    def create(self,**values):
        response=self.client.post('/api/pipeline',json=operation(account_id=self.account_id,company='Acme',**values))
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_stable_opportunity_identity_and_request_replay(self):
        payload=operation(account_id=self.account_id,company='Acme',role='Engineer')
        first=self.client.post('/api/pipeline',json=payload)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(self.client.post('/api/pipeline',json=payload).json(),first.json())
        second=self.create(role='Engineer')
        self.assertNotEqual(first.json()['id'],second['id'])
        listing=self.client.get('/api/pipeline')
        self.assertEqual(listing.status_code,200,listing.text)
        self.assertEqual(len(listing.json()['opportunities']),2)
        before=self.conn.total_changes
        self.client.get('/api/pipeline/review')
        self.client.get('/api/pipeline/'+second['id'])
        self.assertEqual(self.conn.total_changes,before)

    def test_conflicting_edit_does_not_overwrite_and_status_is_explicit(self):
        item=self.create()
        response=self.client.post('/api/pipeline/'+item['id'],json=operation(revision=item['revision'],changes={'status':'Rejected'}))
        self.assertEqual(response.status_code,200,response.text)
        conflict=self.client.post('/api/pipeline/'+item['id'],json=operation(revision=item['revision'],changes={'company':'Wrong'}))
        self.assertEqual(conflict.status_code,409,conflict.text)
        detail=self.client.get('/api/pipeline/'+item['id']).json()
        self.assertEqual(detail['opportunity']['company'],'Acme')
        self.assertEqual(detail['opportunity']['status'],'Rejected')
        self.assertTrue(detail['history'])
        self.assertEqual(len(self.client.get('/api/pipeline?view=closed').json()['opportunities']),1)

    def test_no_bidder_access_and_deleted_account_does_not_leak_details(self):
        item=self.create()
        self.conn.execute('UPDATE accounts SET enabled=0 WHERE id=?',(self.account_id,));self.conn.commit()
        response=self.client.get('/api/pipeline/'+item['id'])
        self.assertEqual(response.status_code,404,response.text)
        self.conn.execute('UPDATE accounts SET enabled=1 WHERE id=?',(self.account_id,));self.conn.commit()
        sign_in_bidder(self.client)
        for endpoint in ['/api/pipeline','/api/pipeline/review','/api/pipeline/'+item['id']]:
            self.assertEqual(self.client.get(endpoint).status_code,403,endpoint)

    def test_task_note_and_outcome_updates_appear_in_detail(self):
        item=self.create()
        base='/api/pipeline/'+item['id']
        result=self.client.post(base+'/tasks',json=operation(revision=item['revision'],title='Complete assessment',due_at='2026-11-02'))
        self.assertEqual(result.status_code,200,result.text)
        item=result.json()
        note=self.client.post(base+'/notes',json=operation(revision=item['revision'],text='Recruiter promised feedback Friday'))
        self.assertEqual(note.status_code,200,note.text)
        detail=self.client.get(base).json()
        self.assertEqual(detail['tasks'][0]['title'],'Complete assessment')
        self.assertTrue(any('Recruiter promised' in str(row) for row in detail['history']))

    def test_activated_followups_use_shared_actions_and_support_dismiss_restore(self):
        from mailcheck import followups
        item=self.create()
        base='/api/pipeline/'+item['id']
        contacted=self.client.post(base+'/contact',json=operation(revision=item['revision'],at='2026-10-01T10:00:00Z',expects_reply=True,note='Contacted recruiter directly in Outlook'))
        self.assertEqual(contacted.status_code,200,contacted.text)
        activated=self.client.post('/api/pipeline/activate',json=operation())
        self.assertEqual(activated.status_code,200,activated.text)
        listing=self.client.get('/api/agent/followups')
        self.assertEqual(listing.status_code,200,listing.text)
        entry=listing.json()['items'][0]
        self.assertTrue(entry['id'].startswith('pipeline:'))
        self.assertIsNone(entry['target_message_pk'])
        from urllib.parse import quote
        dismissed=self.client.post('/api/agent/followups/'+quote(entry['id'],safe=''),json={'action':'dismiss'})
        self.assertEqual(dismissed.status_code,200,dismissed.text)
        restored=self.client.post('/api/agent/followups/'+quote(entry['id'],safe=''),json={'action':'restore'})
        self.assertEqual(restored.status_code,200,restored.text)
        followups.update_state(self.conn,entry['id'],followups.FollowupAction(action='dismiss'))
        self.assertEqual(followups.list_followups(self.conn)['items'][0]['status'],'dismissed')
        followups.update_state(self.conn,entry['id'],followups.FollowupAction(action='restore'))
        self.assertEqual(followups.list_followups(self.conn)['items'][0]['status'],'suggested')
