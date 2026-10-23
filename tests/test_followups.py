"""Follow-up discovery remains local, scoped, and explicit."""
from datetime import datetime, timezone
from unittest.mock import patch
import unittest

from mailcheck import db, followups, interviews, interview_processes
from mailcheck.models import Classification
from tests import test_interviews as fixtures

NOW = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)


class FollowupTests(unittest.TestCase):
    message = fixtures.InterviewTests.message
    setUpBase = fixtures.InterviewTests.setUp

    def setUp(self):
        self.setUpBase()
        self.conn.executescript(followups.SCHEMA)

    def booking(self, **kwargs):
        pk, _ = self.message(calendar_data=[fixtures.ics().replace("candidate@example.test", "work@example.test")], **kwargs)
        interviews.process_message(self.conn, pk, {'category': 'interview_invite', 'company': 'Acme', 'role': 'Engineer'})
        return pk

    def items(self, **kwargs):
        return followups.list_followups(self.conn, now=NOW, **kwargs)['items']

    def test_business_days_and_neutral_past_scheduled_reason(self):
        self.booking()
        item = self.items()[0]
        self.assertEqual(item['elapsed_business_days'], 4)
        self.assertEqual(item['status'], 'suggested')
        self.assertIn('past scheduled', item['reason'])
        friday = datetime(2026, 10, 16, tzinfo=timezone.utc)
        monday = datetime(2026, 10, 19, tzinfo=timezone.utc)
        self.assertEqual(followups._business_days(friday, monday), 1)

    def test_account_isolation_and_saved_threshold(self):
        first = self.booking()
        second = self.booking(account_id=self.b, account_label='personal')
        self.conn.execute('CREATE TABLE IF NOT EXISTS agent_preferences(account_id INTEGER PRIMARY KEY,settings TEXT)')
        self.conn.execute('INSERT INTO agent_preferences VALUES(?,?)', (self.b, '{"followup_business_days": 5}'))
        a, b = self.items(account_id=self.a)[0], self.items(account_id=self.b)[0]
        self.assertNotEqual(a['id'], b['id'])
        self.assertEqual(a['target_message_pk'], first)
        self.assertEqual(b['target_message_pk'], second)
        self.assertEqual(b['status'], 'awaiting_response')

    def test_recent_inbound_and_sent_reply_reset_clock(self):
        pk = self.booking()
        response, _ = self.message(subject='Next steps', date_utc=datetime(2026, 10, 21, 12))
        db.save_classification(self.conn, response, Classification(category='info_request'), 'test', '1')
        self.assertEqual(self.items()[0]['status'], 'awaiting_response')
        self.conn.execute('DELETE FROM messages WHERE id=?', (response,))
        mid = db.get_message(self.conn, pk)['message_id']
        self.conn.execute("INSERT INTO mail_replies(operation,message_pk,account_id,original_message_id,body,mode,mark_done,status,created_at,sent_at) VALUES('sent',?,?,?,'hello','reply',0,'sent',?,?)", (pk,self.a,mid,'2026-10-21T12:00:00Z','2026-10-21T12:00:00Z'))
        self.assertEqual(self.items()[0]['elapsed_business_days'], 1)
        self.assertEqual(self.items()[0]['status'], 'awaiting_response')

    def test_snooze_dismiss_restore_and_new_response(self):
        self.booking()
        key = self.items()[0]['id']
        with patch.object(followups, '_now', return_value=NOW):
            followups.update_state(self.conn, key, followups.FollowupAction(action='snooze'))
            self.assertEqual(self.items()[0]['status'], 'snoozed')
            followups.update_state(self.conn, key, followups.FollowupAction(action='dismiss'))
            self.assertEqual(self.items()[0]['status'], 'dismissed')
            followups.update_state(self.conn, key, followups.FollowupAction(action='restore'))
            self.assertEqual(self.items()[0]['status'], 'suggested')
            followups.update_state(self.conn, key, followups.FollowupAction(action='dismiss'))
        self.message(date_utc=datetime(2026, 10, 21, 12))
        self.assertEqual(self.items()[0]['status'], 'awaiting_response')

    def test_response_in_same_thread_from_another_domain_and_wrong_account_reply(self):
        pk = self.booking()
        response, _ = self.message(from_addr='recruiter@agency.test', date_utc=datetime(2026, 10, 21, 12))
        db.save_classification(self.conn, response, Classification(category='info_request'), 'test', '1')
        self.assertEqual(self.items()[0]['status'], 'awaiting_response')
        self.conn.execute('DELETE FROM messages WHERE id=?', (response,))
        mid = db.get_message(self.conn, pk)['message_id']
        self.conn.execute("INSERT INTO mail_replies(operation,message_pk,account_id,original_message_id,body,mode,mark_done,status,created_at,sent_at) VALUES('wrong',?,?,?,'hello','reply',0,'sent',?,?)", (pk,self.b,mid,'2026-10-21T12:00:00Z','2026-10-21T12:00:00Z'))
        self.assertEqual(self.items()[0]['status'], 'suggested')

    def test_missing_target_and_removed_cancelled_future(self):
        self.booking()
        self.conn.execute('DELETE FROM messages')
        item = self.items()[0]
        self.assertIsNone(item['target_message_pk'])
        self.assertIn('No retained message', item['reason'])
        self.conn.execute("UPDATE interview_events SET status='Cancelled'")
        self.assertEqual(self.items(), [])
        self.conn.execute("UPDATE interview_events SET status='Scheduled',start_at='2026-11-01T12:00:00Z',end_at='2026-11-01T13:00:00Z'")
        self.assertEqual(self.items(), [])
        self.conn.execute("UPDATE interview_events SET start_at='2026-10-18T12:00:00Z',end_at='2026-10-18T13:00:00Z'")
        interview_processes.set_removed(self.conn, 'acme.test', True, account_id=self.a)
        self.assertEqual(self.items(), [])

    def test_personal_meeting_is_not_interview_and_no_generation(self):
        self.booking()
        self.conn.execute('DELETE FROM messages')
        self.conn.execute("UPDATE interview_events SET stage='Other',company='Coffee',notes='Catch up with a friend'")
        with patch('mailcheck.llm.LLMClient.from_config', side_effect=AssertionError('No generation')):
            self.assertEqual(self.items(), [])

    def test_retained_classified_interview_without_event_and_draft(self):
        pk, msg = self.message()
        self.assertEqual(self.items()[0]['target_message_pk'], pk)
        self.conn.execute('CREATE TABLE IF NOT EXISTS agent_drafts(message_pk INTEGER,account_id INTEGER,original_message_id TEXT,body TEXT,case_name TEXT,created_at TEXT)')
        self.conn.execute('INSERT INTO agent_drafts VALUES(?,?,?,?,?,?)', (pk,self.a,msg.message_id,'Review me','follow_up','2026-10-22T10:00:00Z'))
        self.assertEqual(self.items()[0]['status'], 'draft_ready')
