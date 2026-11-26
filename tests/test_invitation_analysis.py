import unittest
import time
from mailcheck.config import Config

from mailcheck import db,interviews,calendar_queue as queue
from tests import test_interviews as invitations
from tests import test_calendar_collection as native


class InvitationAnalysisTests(unittest.TestCase):
    setUp=invitations.InterviewTests.setUp
    message=invitations.InterviewTests.message

    def invite(self,uid='email-invite',extra=''):
        pk,_=self.message(calendar_data=[invitations.ics(uid=uid,extra=extra)])
        interviews.process_message(self.conn,pk,{},calendar_only=True)
        self.conn.commit()
        return pk

    def test_imap_invitation_is_analyzed_without_changing_schedule_or_source(self):
        pk=self.invite()
        before=dict(self.conn.execute('SELECT * FROM interview_events').fetchone())
        self.assertEqual(queue.progress(self.conn)['pending'],1)
        model=native.CalendarAnalysisTests.Model()
        result=interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=model)
        self.assertEqual(result['done'],1)
        after=dict(self.conn.execute('SELECT * FROM interview_events').fetchone())
        self.assertEqual((after['company'],after['role']),('Airbus','HR AI Solutions Lead'))
        for field in ('id','calendar_uid','start_at','end_at','status','timezone','meeting_url','extraction_rank'):
            self.assertEqual(after[field],before[field],field)
        self.assertEqual(self.conn.execute('SELECT message_pk FROM interview_sources').fetchone()[0],pk)
        self.assertEqual(len(self.conn.execute('SELECT * FROM interview_sources').fetchall()),1)

    def test_existing_import_is_discovered_by_due_and_shows_pending_analysis(self):
        self.invite()
        self.conn.execute('DELETE FROM calendar_analysis_tasks');self.conn.commit()
        self.assertTrue(queue.due(self.conn))
        row=self.conn.execute('SELECT * FROM calendar_analysis_tasks').fetchone()
        self.assertTrue(row['external_id'].startswith('email-event:'))
        event=self.conn.execute('SELECT id FROM interview_events').fetchone()[0]
        self.assertTrue(interviews.event_sources_many(self.conn,[event])[event][0]['analysis_pending'])

    def test_native_snapshot_does_not_cancel_email_invitation_tasks(self):
        self.invite()
        queue.snapshot_complete(self.conn,self.a,'2026-01-01','2027-01-01',time.time()+1)
        self.assertEqual(self.conn.execute('SELECT state FROM calendar_analysis_tasks').fetchone()[0],'pending')

    def test_manual_corrections_and_negative_decisions_preserve_imported_events(self):
        from mailcheck.config import Config
        self.invite()
        event=self.conn.execute('SELECT id FROM interview_events').fetchone()[0]
        interviews.correct_event(self.conn,event,{'company':'Manual Company','start_at':'2026-10-18T18:00:00Z','end_at':'2026-10-18T19:00:00Z'})
        interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=native.CalendarAnalysisTests.Model())
        row=self.conn.execute('SELECT company,start_at FROM interview_events').fetchone()
        self.assertEqual(tuple(row),('Manual Company','2026-10-18T18:00:00+00:00'))
        self.invite('negative')
        result=interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=native.CalendarAnalysisTests.Model(is_interview_event=False))
        self.assertEqual(result['needs_review'],1)
        self.assertEqual(len(interviews.list_events(self.conn)),2)

    def test_invitation_analysis_survives_email_retention(self):
        from mailcheck.config import Config
        self.invite();self.conn.execute('DELETE FROM calendar_analysis_tasks');self.conn.commit()
        db.prune_messages(self.conn,before_iso='2027-01-01')
        self.assertTrue(queue.due(self.conn))
        result=interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=native.CalendarAnalysisTests.Model())
        self.assertEqual(result['done'],1)

    def test_multiple_events_in_one_email_keep_independent_analysis_and_identity(self):
        pk,_=self.message(calendar_data=[invitations.ics(uid='one'),
            invitations.ics(uid='two',start='20261019T153000Z',end='20261019T163000Z')])
        interviews.process_message(self.conn,pk,{},calendar_only=True);self.conn.commit()
        self.assertEqual(queue.progress(self.conn)['pending'],2)
        result=interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=native.CalendarAnalysisTests.Model(),limit=3)
        self.assertEqual(result['done'],2)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_sources WHERE message_pk=?',(pk,)).fetchone()[0],2)

    def test_duplicate_invitation_does_not_reset_completed_analysis(self):
        self.invite('same')
        interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=native.CalendarAnalysisTests.Model())
        self.invite('same')
        self.assertEqual(queue.progress(self.conn)['done'],1)
        self.assertEqual(queue.progress(self.conn)['pending'],0)
        self.assertEqual(self.conn.execute('SELECT company FROM interview_events').fetchone()[0],'Airbus')

    def test_disabled_accounts_and_removed_events_are_not_backfilled(self):
        self.invite('disabled')
        self.conn.execute('DELETE FROM calendar_analysis_tasks')
        self.conn.execute('UPDATE accounts SET enabled=0 WHERE id=?',(self.a,));self.conn.commit()
        self.assertFalse(queue.due(self.conn))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM calendar_analysis_tasks').fetchone()[0],0)

    def test_negative_invitation_can_retry_fresh_inference_and_clear_its_review_reason(self):
        self.invite('retry-negative')
        interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=native.CalendarAnalysisTests.Model(is_interview_event=False))
        queue.retry_now(self.conn);self.conn.commit()
        model=native.CalendarAnalysisTests.Model()
        result=interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=model)
        self.assertEqual(len(model.calls),1)
        self.assertEqual(result['needs_review'],0)
        row=self.conn.execute('SELECT company,needs_review,review_reason FROM interview_events').fetchone()
        self.assertEqual(tuple(row),('Airbus',0,None))

    def test_legacy_negative_cache_does_not_block_email_invitation_retry(self):
        from mailcheck.calendar_analysis import CalendarAnalyzer
        self.invite('legacy-negative')
        task=dict(self.conn.execute('SELECT * FROM calendar_analysis_tasks').fetchone())
        account=next(a for a in db.list_accounts(self.conn) if a.id==task['account_id'])
        with CalendarAnalyzer(self.conn,Config(),lambda _:None,client=native.CalendarAnalysisTests.Model(is_interview_event=False)) as analyzer:
            analyzer.analyze(account,queue.decode(task))
        self.conn.execute("UPDATE interview_events SET needs_review=1,review_reason='Email invitation analysis needs review; retry analysis or correct event details.'")
        self.conn.commit()
        model=native.CalendarAnalysisTests.Model()
        result=interviews.resume_calendar_analysis(self.conn,Config(),analysis_client=model)
        self.assertEqual(len(model.calls),1)
        self.assertEqual(result['done'],1)
        row=self.conn.execute('SELECT company,needs_review,review_reason FROM interview_events').fetchone()
        self.assertEqual(tuple(row),('Airbus',0,None))
