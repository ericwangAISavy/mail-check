"""Durable analysis batches use stored native events, not repeated Graph scans."""
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from mailcheck import calendar_queue as queue, config, db, interviews, pipeline
from mailcheck.llm import LLMError
from tests import test_calendar_collection as fixtures
event = fixtures.event


class QueueTests(unittest.TestCase):
    setUp = fixtures.NativeCalendarTests.setUp
    source = fixtures.NativeCalendarTests.source
    Model = fixtures.CalendarAnalysisTests.Model

    def collect(self, items, label='work'):
        cfg=config.Config();cfg.llm.base_url='http://model.test'
        with patch.object(pipeline,'build_source',return_value=self.source(items)),patch('mailcheck.calendar_analysis.LLMClient.from_config',side_effect=AssertionError('Collection must not wait for inference')):
            result=interviews.collect_calendar_events(self.conn,cfg,account_label=label,defer_analysis=True)
        self.assertFalse(result['errors'])
        return cfg,result

    def test_collection_queues_then_resumes_after_reopen_without_reading_calendars(self):
        cfg,result=self.collect([event('one'),event('two'),event('three')])
        self.assertEqual(result['analysis_pending'],3)
        self.assertEqual(queue.progress(self.conn)['pending'],3)
        self.conn.close();self.conn=db.connect(self.path);self.addCleanup(self.conn.close)
        with patch.object(pipeline,'build_source',side_effect=AssertionError('No calendar refetch')):
            first=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=self.Model(),limit=1)
            second=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=self.Model(),limit=3)
        self.assertEqual((first['done'],first['pending']),(1,2))
        self.assertEqual((second['done'],second['pending']),(3,0))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM calendar_analysis_tasks WHERE booking IS NOT NULL').fetchone()[0],0)

    def test_failed_event_backs_off_and_does_not_starve_untried_events(self):
        cfg,_=self.collect([event('bad'),event('good')])
        model=self.Model()
        with patch.object(model,'complete',side_effect=LLMError('timeout',category='timeout')) as complete:
            first=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=model,limit=3)
            self.assertEqual(complete.call_count,1)
        self.assertEqual(first['retrying'],1)
        self.assertIn('timed out',first['last_error'])
        self.assertFalse(queue.due(self.conn))
        with patch('mailcheck.calendar_queue.time.time',return_value=time.time()+61):
            second=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=model,limit=1)
        self.assertEqual(second['done'],1)
        done=self.conn.execute("SELECT external_id FROM calendar_analysis_tasks WHERE state='done'").fetchone()[0]
        self.assertEqual(done,'graph-event:good')

    def test_upcoming_events_first_and_batches_rotate_accounts(self):
        now=datetime.now(timezone.utc)
        def booking(identity,days):
            item=event(identity);start=now+timedelta(days=days)
            item.update(start={'dateTime':start.isoformat(),'timeZone':'UTC'},end={'dateTime':(start+timedelta(hours=1)).isoformat(),'timeZone':'UTC'})
            return item
        cfg,_=self.collect([booking('old',-200),booking('soon',1),booking('later',20)])
        self.conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?",(self.b,));self.conn.commit()
        self.collect([booking('personal',2)],'personal')
        first=queue.claim(self.conn)
        self.assertEqual(first['external_id'],'graph-event:soon')
        queue.finish(self.conn,first);self.conn.commit()
        second=queue.claim(self.conn)
        self.assertEqual(second['account_id'],self.b)
        queue.finish(self.conn,second);self.conn.commit()
        third=queue.claim(self.conn)
        self.assertEqual(third['external_id'],'graph-event:later')

    def test_old_claim_cannot_overwrite_new_provider_snapshot(self):
        cfg,_=self.collect([event()]);task=queue.claim(self.conn)
        newer=event();newer['start']['dateTime']='2026-10-18T18:00:00';newer['end']['dateTime']='2026-10-18T19:00:00'
        self.collect([newer])
        self.assertFalse(queue.current(self.conn,task))
        result=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=self.Model())
        self.assertEqual(result['done'],1)
        self.assertEqual(self.conn.execute('SELECT start_at FROM interview_events').fetchone()[0],'2026-10-18T18:00:00+00:00')

    def test_complete_snapshot_cancels_missing_tasks_but_failed_fetch_does_not(self):
        cfg,_=self.collect([event()]);self.collect([])
        self.assertEqual(queue.progress(self.conn)['pending'],0)
        self.collect([event()])
        source=self.source([])
        from mailcheck.sources import SourceError
        with patch.object(pipeline,'build_source',return_value=source),patch.object(source,'fetch_calendar',side_effect=SourceError('offline')):
            interviews.collect_calendar_events(self.conn,cfg,account_label='work',defer_analysis=True)
        self.assertEqual(queue.progress(self.conn)['pending'],1)

    def test_expired_claim_recovers_and_manual_corrections_are_preserved(self):
        cfg,_=self.collect([event()]);task=queue.claim(self.conn)
        identity=self.conn.execute('SELECT id FROM interview_events').fetchone()[0]
        interviews.correct_event(self.conn,identity,{'company':'Manual company','role':'Manual role'})
        self.conn.execute('UPDATE calendar_analysis_tasks SET lease_until=0 WHERE id=?',(task['id'],));self.conn.commit()
        result=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=self.Model())
        self.assertEqual(result['done'],1)
        self.assertEqual(tuple(self.conn.execute('SELECT company,role FROM interview_events').fetchone()),('Manual company','Manual role'))

    def test_negative_analysis_hides_fallback_event_and_retry_now_is_explicit(self):
        cfg,_=self.collect([event()])
        result=interviews.resume_calendar_analysis(self.conn,cfg,analysis_client=self.Model(is_interview_event=False))
        self.assertEqual(result['done'],1)
        self.assertEqual(interviews.list_events(self.conn),[])
        self.collect([event('retry')]);task=queue.claim(self.conn)
        queue.retry(self.conn,task,'Busy',service_unavailable=True);self.conn.commit()
        self.assertFalse(queue.due(self.conn))
        queue.retry_now(self.conn);self.conn.commit()
        self.assertTrue(queue.due(self.conn))

    def test_expired_worker_cannot_finish_or_retry_a_reclaimed_task(self):
        self.collect([event()]);old=queue.claim(self.conn)
        self.conn.execute('UPDATE calendar_analysis_tasks SET lease_until=0');self.conn.commit()
        new=queue.claim(self.conn)
        self.assertFalse(queue.current(self.conn,old));self.assertTrue(queue.current(self.conn,new))
        queue.finish(self.conn,old);queue.retry(self.conn,old,'Stale failure',service_unavailable=True);self.conn.commit()
        self.assertTrue(queue.current(self.conn,new))
        self.assertEqual(self.conn.execute('SELECT next_run FROM calendar_analysis_worker').fetchone()[0],0)
        queue.finish(self.conn,new);self.conn.commit()
        self.assertEqual(queue.progress(self.conn)['done'],1)
