from datetime import datetime,timezone
from unittest import TestCase
from tests import test_followups as fixtures
from mailcheck import interview_processes,db

NOW=datetime(2026,10,22,18,tzinfo=timezone.utc)
class ProcessFollowupTests(TestCase):
    setUp=fixtures.FollowupTests.setUp
    setUpBase=fixtures.FollowupTests.setUpBase
    message=fixtures.FollowupTests.message
    booking=fixtures.FollowupTests.booking
    def state(self):
        return interview_processes.list_processes(self.conn,now=NOW)[0]['follow_up']
    def reply(self,pk,status='sent',original=None):
        row=db.get_message(self.conn,pk)
        self.conn.execute('''INSERT INTO mail_replies(operation,message_pk,account_id,original_message_id,body,mode,mark_done,status,created_at,sent_at)
            VALUES(?,?,?,?,?,'reply',0,?,?,?)''',(f'op-{status}',pk,row['account_id'],original or row['message_id'],'Any update?',status,'2026-10-22T17:00:00Z','2026-10-22T17:00:00Z'))
    def test_targets_original_email_and_marks_only_confirmed_send(self):
        pk=self.booking()
        self.assertEqual(self.state()['target_message_pk'],pk)
        self.assertEqual(self.state()['status'],'ready')
        self.reply(pk,'unknown')
        self.assertEqual(self.state()['status'],'ready')
        self.reply(pk)
        self.assertEqual(self.state()['status'],'sent')
    def test_wrong_identity_or_other_account_cannot_mark_sent(self):
        pk=self.booking();self.reply(pk,original='<stale-message>')
        self.assertEqual(self.state()['status'],'ready')
        self.conn.execute("DELETE FROM mail_replies")
        other,_=self.message(account_id=self.b,account_label='personal');self.reply(other)
        self.assertEqual(self.state()['status'],'ready')
    def test_new_inbound_resets_sent_indicator(self):
        pk=self.booking();self.reply(pk)
        self.assertEqual(self.state()['status'],'sent')
        self.message(subject='Interview update',date_utc=datetime(2026,10,22,17,30),thread_id='thread-1')
        self.assertEqual(self.state()['status'],'ready')
    def test_native_only_event_can_find_earlier_recruiter_email(self):
        pk=self.booking()
        self.conn.execute('UPDATE interview_sources SET message_pk=NULL')
        self.assertEqual(self.state()['target_message_pk'],pk)
    def test_no_mail_explains_unavailable_and_opening_never_marks_sent(self):
        pk=self.booking()
        self.conn.execute('UPDATE interview_sources SET message_pk=NULL')
        self.conn.execute('DELETE FROM messages WHERE id=?',(pk,))
        self.assertEqual(self.state(),{'target_message_pk':None,'status':'unavailable','sent_at':None})
