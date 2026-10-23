"""Native booking collection: real Graph transport, real SQLite, no message reads."""
from __future__ import annotations
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
import httpx
from mailcheck import config, db, interviews, outlook_auth, pipeline
from mailcheck.sources.outlook import OutlookGraphSource, GRAPH
from mailcheck.sources.imap import IMAPSource
from mailcheck.sources import SourceError
from tests import test_interviews as fixtures
ics = fixtures.ics


def event(identity="booking-1", **values):
    return dict(id=identity,iCalUId="uid-"+identity,subject="Booked appointment",
        start={"dateTime":"2026-10-18T15:30:00.0000000","timeZone":"UTC"},
        end={"dateTime":"2026-10-18T16:30:00.0000000","timeZone":"UTC"},
        originalStartTimeZone="Central Standard Time",isCancelled=False,
        lastModifiedDateTime="2026-10-15T12:00:00Z",**values)


class NativeCalendarTests(unittest.TestCase):
    def setUp(self):
        fixtures.InterviewTests.setUp(self)
        self.conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?",(self.a,))
        self.conn.commit()

    def source(self, items=None, handler=None):
        self.requests=[]
        def respond(request):
            self.requests.append(request)
            if handler:
                return handler(request)
            return httpx.Response(200,json={"value":[{"id":"calendar-1","name":"Calendar"}]} if request.url.path.endswith('/calendars') else {"value":items or []})
        source = OutlookGraphSource(label="work",client_id="test")
        source._client=lambda **kwargs:httpx.Client(transport=httpx.MockTransport(respond))
        return source

    def collect(self, source, label="work"):
        with patch.object(pipeline,"build_source",return_value=source),patch.object(source,"fetch_unread",side_effect=AssertionError("Do not read mail")),patch.object(interviews.LLMClient,"from_config",side_effect=AssertionError("Do not classify or analyze mail")):
            return interviews.collect_calendar_events(self.conn,config.Config(),account_label=label)

    def test_all_booking_kinds_use_calendar_events_only(self):
        kinds=[("teams","https://teams.microsoft.com/l/meetup-join/ABC","teamsForBusiness","Microsoft Teams"),
            ("google","https://meet.google.com/abc-defg-hij","unknown","Google Meet"),
            ("zoom","https://zoom.us/j/12345","unknown","Zoom"),
            ("webex","https://example.webex.com/meet/name","unknown","Webex"),
            ("phone",None,"unknown",None),("office",None,"unknown",None)]
        items=[]
        for name,link,provider,platform in kinds:
            item=event(name);item.update(subject=name,onlineMeeting={"joinUrl":link} if link else None,
                onlineMeetingProvider=provider,location={"displayName":"Phone" if name=="phone" else "Office"})
            items.append(item)
        result=self.collect(self.source(items))
        self.assertFalse(result['errors'])
        self.assertEqual(len(result['changes']),6)
        rows=self.conn.execute('SELECT * FROM interview_events ORDER BY id').fetchall()
        self.assertEqual([r['meeting_platform'] for r in rows],[k[3] for k in kinds])
        self.assertTrue(all(r['extraction_rank']==3 for r in rows))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM classifications').fetchone()[0],0)
        self.assertTrue(all(r[0] is None for r in self.conn.execute('SELECT message_pk FROM interview_sources')))
        for request in self.requests:
            self.assertNotIn('messages',request.url.path)
            self.assertNotIn('body',request.url.params.get('$select',''))
            self.assertNotIn('$expand',request.url.params)
        self.assertTrue(any('/calendarView' in r.url.path for r in self.requests))

    def test_all_calendars_and_event_pages_are_followed(self):
        def respond(r):
            if r.url.path.endswith('/calendars'):
                return httpx.Response(200,json={'value':[{'id':'one','name':'Personal'}],'@odata.nextLink':GRAPH+'/calendar-page-2'})
            if r.url.path.endswith('/calendar-page-2'):
                return httpx.Response(200,json={'value':[{'id':'two','name':'Work'}]})
            if '/one/calendarView' in r.url.path:
                return httpx.Response(200,json={'value':[event('one')],'@odata.nextLink':GRAPH+'/event-page-2'})
            return httpx.Response(200,json={'value':[event('page-two' if r.url.path.endswith('event-page-2') else 'work')]})
        result=self.collect(self.source(handler=respond))
        self.assertFalse(result['errors']);self.assertEqual(len(result['changes']),3)
        views=[r for r in self.requests if 'calendarView' in r.url.path]
        self.assertEqual(len(views),2)
        for r in views:
            self.assertIn('startDateTime',r.url.params);self.assertIn('endDateTime',r.url.params)
            self.assertNotIn('receivedDateTime',str(r.url))

    def test_repeat_import_reschedule_and_cancellation_keep_event_identity(self):
        item=event()
        self.collect(self.source([item]));self.assertFalse(self.collect(self.source([item]))['changes'])
        item['start']['dateTime']='2026-10-18T16:00:00';item['end']['dateTime']='2026-10-18T17:00:00'
        item['lastModifiedDateTime']='2026-10-16T12:00:00Z'
        self.collect(self.source([item]))
        row=self.conn.execute('SELECT * FROM interview_events').fetchone()
        self.assertEqual(row['status'],'Rescheduled');identity=row['id']
        item['isCancelled']=True;item['lastModifiedDateTime']='2026-10-17T12:00:00Z'
        self.collect(self.source([item]))
        rows=self.conn.execute('SELECT * FROM interview_events').fetchall()
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['id'],identity)
        self.assertEqual(rows[0]['status'],'Cancelled')

    def test_recurring_occurrences_keep_separate_identity(self):
        first=event('first');second=event('second')
        first.update(iCalUId='series',originalStart='2026-10-18T15:30:00Z',type='occurrence')
        second.update(iCalUId='series',originalStart='2026-10-19T15:30:00Z',type='exception')
        self.collect(self.source([first,second]))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],2)

    def test_bad_event_does_not_prevent_later_valid_bookings(self):
        broken=event('bad');broken['start']={}
        result=self.collect(self.source([broken,event('valid')]))
        self.assertTrue(result['errors'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],1)

    def test_missing_permission_reports_reconnect_without_mail_fallback(self):
        result=self.collect(self.source(handler=lambda r:httpx.Response(403,json={'error':{'code':'ErrorAccessDenied'}})))
        self.assertIn('Calendars.Read',result['errors'][0])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0],0)

    def test_imap_does_not_read_messages_to_collect_events(self):
        source=IMAPSource(host='example.test',port=993,username='test',password='test')
        with patch.object(source,'_open',side_effect=AssertionError('No IMAP reads')):
            result=self.collect(source)
        self.assertIn('IMAP cannot read calendar events',result['errors'][0])

    def test_calendar_requests_use_calendar_scope(self):
        source=OutlookGraphSource(label='work',client_id='test')
        with patch('mailcheck.sources.outlook.acquire_token',return_value='test') as token:
            with source._client(calendar=True) as client:
                self.assertIn('outlook.timezone="UTC"',client.headers['Prefer'])
            token.assert_called_once_with('work','test',scopes=['Calendars.Read'])
        self.assertIn('Calendars.Read',outlook_auth.SCOPES)

    def test_native_update_supersedes_old_ics_sequence(self):
        pk,_=fixtures.InterviewTests.message(self,calendar_data=[ics(uid='uid-booking-1',sequence=5)])
        interviews.process_message(self.conn,pk,{},calendar_only=True)
        self.collect(self.source([event()]))
        rows=self.conn.execute('SELECT * FROM interview_events').fetchall()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['extraction_rank'],3)
        self.assertEqual(rows[0]['company'],'Booked appointment')

    def test_imap_account_is_rejected_before_mail_credentials_are_opened(self):
        with patch.object(pipeline,"build_source",side_effect=AssertionError("No mail source should be opened")):
            result=interviews.collect_calendar_events(self.conn,config.Config(),account_label="personal")
        self.assertIn('IMAP cannot read calendar events',result['errors'][0])


class CheckDispatchTests(unittest.TestCase):
    def run_check(self, mode):
        from mailcheck.web import app as web
        from mailcheck.models import RunResult
        with patch.object(web, "_start_job", side_effect=lambda work, **kwargs: work()), \
             patch.object(web.cfgmod, "load", return_value=config.Config()), \
             patch.object(web.db, "session"), \
             patch.object(web, "check_once", return_value=RunResult(started_at=datetime.now(timezone.utc))) as mail, \
             patch.object(web.interviews, "collect_calendar_events", return_value={"changes": [], "accounts": 2, "errors": []}) as calendar:
            web._run_check(web.CheckBody(**mode))
        return mail, calendar

    def test_default_check_classifies_mail_for_all_enabled_accounts(self):
        mail, calendar = self.run_check({})
        mail.assert_called_once()
        self.assertIsNone(mail.call_args.kwargs["account_label"])
        self.assertTrue(mail.call_args.kwargs["use_cache"])
        calendar.assert_not_called()

    def test_calendar_check_never_runs_mail_classification(self):
        mail, calendar = self.run_check({"mode": "calendar"})
        mail.assert_not_called()
        calendar.assert_called_once()
        self.assertIsNone(calendar.call_args.kwargs["account_label"])

class CalendarDuplicateTests(unittest.TestCase):
    setUp=NativeCalendarTests.setUp
    source=NativeCalendarTests.source
    collect=NativeCalendarTests.collect
    def test_copies_with_different_uids_merge_and_stay_merged(self):
        first=event('original');first.update(subject='Carta Phone Meeting',organizer={'emailAddress':{'address':'recruiter@carta.test'}})
        second=event('copy');second.update(subject='Carta Phone Meeting',organizer=first['organizer'])
        self.collect(self.source([first,second]))
        self.assertEqual(len(interviews.list_events(self.conn)),1)
        self.collect(self.source([second,first]))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_sources').fetchone()[0],2)

    def test_existing_duplicates_display_once_without_losing_sources_or_manual_edits(self):
        first=event('original',organizer={'emailAddress':{'address':'recruiter@test'}})
        second=event('copy',organizer=first['organizer']);second['subject']='Temporary different title'
        self.collect(self.source([first]))
        self.collect(self.source([second]))
        rows=self.conn.execute('SELECT id FROM interview_events ORDER BY id').fetchall()
        self.conn.execute("UPDATE interview_events SET company='Booked appointment'")
        interviews.correct_event(self.conn,rows[0][0],{'notes':'Keep my correction'})
        self.assertEqual(len(interviews.list_events(self.conn)),1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_sources').fetchone()[0],2)
        self.assertEqual(interviews.list_events(self.conn)[0]['notes'],'Keep my correction')
        self.assertEqual(len(interviews.event_sources(self.conn,rows[0][0])),2)
        interviews.remove_event(self.conn,rows[0][0])
        self.assertEqual(interviews.list_events(self.conn),[])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],2)

    def test_email_invitation_and_native_booking_with_different_ids_match(self):
        pk,_=fixtures.InterviewTests.message(self,calendar_data=[ics(uid='email-uid')])
        interviews.process_message(self.conn,pk,{},calendar_only=True)
        item=event('native');item['onlineMeeting']={'joinUrl':'https://zoom.us/j/12345'}
        item['organizer']={'emailAddress':{'address':'recruiter@acme.test'}}
        self.collect(self.source([item]))
        self.assertEqual(len(interviews.list_events(self.conn)),1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM interview_events').fetchone()[0],1)
        self.assertEqual(len(interviews.event_sources(self.conn,interviews.list_events(self.conn)[0]['id'])),2)

    def test_same_title_different_times_or_organizers_stay_separate(self):
        one=event('one',organizer={'emailAddress':{'address':'one@test'}})
        two=event('two',organizer={'emailAddress':{'address':'two@test'}})
        three=event('three');three['start']={'dateTime':'2026-10-19T15:30:00','timeZone':'UTC'};three['end']={'dateTime':'2026-10-19T16:30:00','timeZone':'UTC'}
        self.collect(self.source([one,two,three]))
        self.assertEqual(len(interviews.list_events(self.conn)),3)

    def test_incomplete_review_copy_is_hidden_behind_confirmed_booking(self):
        one=event('confirmed',organizer={'emailAddress':{'address':'recruiter@test'}})
        two=event('incomplete',organizer=one['organizer']);two['subject']='Temporary different title'
        self.collect(self.source([one,two]))
        ids=[row[0] for row in self.conn.execute('SELECT id FROM interview_events ORDER BY id')]
        self.conn.execute("UPDATE interview_events SET company='Carta Phone Meeting'")
        self.conn.execute("UPDATE interview_events SET end_at=NULL,extraction_rank=2,needs_review=1 WHERE id=?",(ids[1],))
        self.conn.execute('UPDATE interview_sources SET account_id=? WHERE event_id=?',(self.b,ids[1]))
        events=interviews.list_events(self.conn)
        self.assertEqual(len(events),1)
        self.assertEqual(events[0]['id'],ids[0])
        self.assertFalse(events[0]['needs_review'])
        self.assertEqual(len(interviews.event_sources(self.conn,ids[0])),2)
