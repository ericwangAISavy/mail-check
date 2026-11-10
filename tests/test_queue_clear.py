"""Bulk Queue completion is local, scoped, durable and reversible as one action."""
from datetime import datetime, timezone

from mailcheck import db
from mailcheck.models import Classification, NormalizedMessage
from unittest import TestCase
from tests import test_frontend_api as fixtures
from tests.web_client import sign_in_bidder


class QueueClearTests(TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)
    def add(self, key, category='interview_invite', done=False):
        pk = db.upsert_message(self.conn, NormalizedMessage(account_id=self.account_id,
            account_label='personal',message_id=key,uid=key,folder='INBOX',from_addr='hr@example.test',
            from_name='HR',subject=key,body='Saved body',date_utc=datetime(2020,1,1,tzinfo=timezone.utc)))
        db.save_classification(self.conn,pk,Classification(category=category),'test','1')
        if done: db.set_handled(self.conn,pk,True)
        self.conn.commit()
        return pk

    def test_bulk_clear_includes_older_queue_but_preserves_other_mail_and_future_arrivals(self):
        old = self.add('old')
        info = self.add('receipt', 'application_ack')
        noise = self.add('noise', 'noise')
        already_done = self.add('done', done=True)
        previous_stamp = db.get_message(self.conn,already_done)['handled_at']
        self.conn.execute("INSERT INTO classifications(message_pk,category,model,prompt_version,created_at) VALUES(?, 'application_ack', 'later', '2', '9999')",(old,))
        self.conn.commit()
        self.add('queued')
        count_before = self.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        response = self.client.post('/api/messages/clear-queue')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['count'],1)
        self.assertTrue(response.json()['operation'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0],count_before)
        for pk in (old,info,noise): self.assertIsNone(db.get_message(self.conn,pk)['handled_at'])
        self.assertEqual(db.get_message(self.conn,already_done)['handled_at'],previous_stamp)
        later = self.add('arrived-later')
        self.assertIsNone(db.get_message(self.conn,later)['handled_at'])

    def test_bulk_undo_restores_only_its_members_and_does_not_override_manual_changes(self):
        a,b,c = [self.add(key) for key in ('a','b','c')]
        previous = self.add('previous',done=True)
        cleared = self.client.post('/api/messages/clear-queue').json()
        db.set_handled(self.conn,b,False)
        db.set_handled(self.conn,b,True)
        manual_stamp = db.get_message(self.conn,b)['handled_at']
        response = self.client.post(f"/api/messages/clear-queue/{cleared['operation']}/undo")
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['count'],2)
        for pk in (a,c): self.assertIsNone(db.get_message(self.conn,pk)['handled_at'])
        self.assertEqual(db.get_message(self.conn,b)['handled_at'],manual_stamp)
        self.assertIsNotNone(db.get_message(self.conn,previous)['handled_at'])
        self.assertEqual(self.client.post(f"/api/messages/clear-queue/{cleared['operation']}/undo").json()['count'],0)

    def test_existing_undo_restores_the_bulk_action_and_retention_cannot_restore_reused_ids(self):
        a,b = self.add('a'),self.add('b')
        cleared = self.client.post('/api/messages/clear-queue').json()
        self.conn.execute('DELETE FROM messages WHERE id=?',(b,)); self.conn.commit()
        replacement = self.add('replacement')
        self.assertEqual(replacement,b)
        db.set_handled(self.conn,replacement,True)
        # Single-message Undo stays separate from the earlier bulk action.
        self.assertEqual(self.client.post('/api/messages/undo-last').json()['pk'],replacement)
        response = self.client.post('/api/messages/undo-last')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['count'],1)
        self.assertIsNone(db.get_message(self.conn,a)['handled_at'])
        self.assertIsNone(db.get_message(self.conn,replacement)['handled_at'])

    def test_bulk_clear_is_not_limited_to_500_rows_and_empty_clear_is_safe(self):
        stamp = datetime.now(timezone.utc).isoformat()
        self.conn.executemany('INSERT INTO messages(account_id,message_id,subject,fetched_at) VALUES(?,?,?,?)',
            [(self.account_id,f'bulk-{i}',f'Bulk {i}',stamp) for i in range(650)])
        self.conn.execute("INSERT INTO classifications(message_pk,category,model,prompt_version,created_at) SELECT id,'interview_invite','test','1',? FROM messages",(stamp,))
        self.conn.commit()
        response = self.client.post('/api/messages/clear-queue')
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['count'],650)
        second = self.client.post('/api/messages/clear-queue')
        self.assertEqual(second.json()['count'],0)
        self.assertIsNone(second.json()['operation'])
        undo = self.client.post('/api/messages/undo-last')
        self.assertEqual(undo.json()['count'],650)

    def test_bidder_cannot_bulk_clear_or_bulk_restore(self):
        self.add('queue')
        sign_in_bidder(self.client)
        self.assertEqual(self.client.post('/api/messages/clear-queue').status_code,403)
        self.assertEqual(self.client.post('/api/messages/clear-queue/11111111-1111-4111-8111-111111111111/undo').status_code,403)

    def test_clear_failure_rolls_back_both_completion_and_undo_membership(self):
        import sqlite3
        from mailcheck import queue_actions
        pk = self.add('saved')
        self.conn.execute("CREATE TRIGGER reject_completion BEFORE UPDATE OF handled_at ON messages BEGIN SELECT RAISE(ABORT,'blocked'); END")
        self.conn.commit()
        with self.assertRaises(sqlite3.IntegrityError):
            queue_actions.clear(self.conn)
        self.assertIsNone(db.get_message(self.conn,pk)['handled_at'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM queue_clear_members').fetchone()[0],0)

    def test_existing_database_upgrade_preserves_mail_and_completed_state(self):
        pk = self.add('previously-completed',done=True)
        before = dict(db.get_message(self.conn,pk))
        self.conn.execute('DROP TABLE queue_clear_members')
        self.conn.execute('PRAGMA user_version=45')
        self.conn.commit()
        upgraded = db.connect(self.path)
        try:
            self.assertEqual(dict(db.get_message(upgraded,pk)),before)
            self.assertEqual(upgraded.execute('SELECT COUNT(*) FROM queue_clear_members').fetchone()[0],0)
            self.assertEqual(upgraded.execute('PRAGMA user_version').fetchone()[0],db.SCHEMA_VERSION)
        finally:
            upgraded.close()

    def test_undo_order_is_exact_even_when_clock_values_repeat(self):
        from unittest.mock import patch
        from mailcheck import queue_actions
        first = self.add('bulk-member')
        second = self.add('single-message')
        with patch.object(db,'_now',return_value='2026-11-01T00:00:00+00:00'):
            db.set_handled(self.conn,second,True)
            queue_actions.clear(self.conn)
            self.assertEqual(db.last_handled(self.conn)['pk'],first)
            db.set_handled(self.conn,second,True)
            self.assertEqual(db.last_handled(self.conn)['pk'],second)
            self.assertEqual(self.client.post('/api/messages/undo-last').json()['pk'],second)
            self.assertEqual(self.client.post('/api/messages/undo-last').json()['pk'],first)

    def test_retry_of_confirmed_operation_does_not_clear_new_arrivals_or_reapply_after_undo(self):
        operation = '11111111-1111-4111-8111-111111111111'
        first = self.add('first')
        response = self.client.post('/api/messages/clear-queue',json={'operation':operation})
        self.assertEqual(response.status_code,200,response.text)
        later = self.add('later')
        retried = self.client.post('/api/messages/clear-queue',json={'operation':operation})
        self.assertEqual(retried.json()['count'],1)
        self.assertEqual(retried.json()['operation'],response.json()['operation'])
        self.assertTrue(retried.json()['replayed'])
        self.assertIsNone(db.get_message(self.conn,later)['handled_at'])
        self.client.post(f'/api/messages/clear-queue/{operation}/undo')
        repeated = self.client.post('/api/messages/clear-queue',json={'operation':operation})
        self.assertTrue(repeated.json()['replayed'])
        for pk in (first,later):self.assertIsNone(db.get_message(self.conn,pk)['handled_at'])

    def test_retry_of_empty_clear_does_not_capture_future_queue(self):
        operation = '22222222-2222-4222-8222-222222222222'
        response = self.client.post('/api/messages/clear-queue',json={'operation':operation})
        self.assertEqual(response.json()['count'],0)
        later = self.add('future')
        retried = self.client.post('/api/messages/clear-queue',json={'operation':operation})
        self.assertEqual(retried.json()['count'],0)
        self.assertTrue(retried.json()['replayed'])
        self.assertIsNone(db.get_message(self.conn,later)['handled_at'])

    def test_schema_upgrade_retains_legacy_batch_replay_protection(self):
        from mailcheck import queue_actions
        self.add('legacy-batch')
        result = queue_actions.clear(self.conn)
        later = self.add('later')
        self.conn.execute('DROP TABLE queue_clear_operations')
        self.conn.execute('PRAGMA user_version=46')
        self.conn.commit()
        upgraded = db.connect(self.path)
        try:
            retried = queue_actions.clear(upgraded,result['operation'])
            self.assertTrue(retried['replayed'])
            self.assertEqual(retried['count'],1)
            self.assertIsNone(db.get_message(upgraded,later)['handled_at'])
        finally:
            upgraded.close()

    def test_concurrent_confirmations_of_same_operation_apply_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from mailcheck import queue_actions
        self.add('concurrent')
        operation = '33333333-3333-4333-8333-333333333333'
        def confirm(_):
            with db.session(self.path) as conn:
                return queue_actions.clear(conn,operation)
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(confirm,range(2)))
        self.assertEqual([result['count'] for result in results],[1,1])
        self.assertEqual(sorted(result['replayed'] for result in results),[False,True])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM queue_clear_operations').fetchone()[0],1)
