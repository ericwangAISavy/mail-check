from datetime import datetime, timezone
from unittest import TestCase
from mailcheck import availability
from mailcheck.calendar_events import CalendarBooking

class AvailabilityTests(TestCase):
    def test_friday_buffers_all_free_ranges_and_duration(self):
        now=datetime(2026,10,23,12,tzinfo=timezone.utc) # Friday 7 AM Chicago
        bookings=[CalendarBooking('one','one','Interview',datetime(2026,10,23,15,tzinfo=timezone.utc),datetime(2026,10,23,16,tzinfo=timezone.utc)),
            CalendarBooking('two','two','Interview',datetime(2026,10,23,19,tzinfo=timezone.utc),datetime(2026,10,23,20,tzinfo=timezone.utc))]
        result=availability.calculate(bookings,now=now,days=1,duration=60)
        self.assertEqual([(r['start'],r['end']) for r in result['ranges']], [('2026-10-23T16:15:00+00:00','2026-10-23T18:45:00+00:00')])
        shorter=availability.calculate(bookings,now=now,days=1,duration=30)
        self.assertEqual(len(shorter['ranges']),3)
        self.assertEqual(shorter['ranges'][-1]['end'],'2026-10-23T21:00:00+00:00')

    def test_free_cancelled_and_duplicate_busy_events(self):
        now=datetime(2026,10,22,12,tzinfo=timezone.utc)
        start=datetime(2026,10,22,15,tzinfo=timezone.utc);end=datetime(2026,10,22,16,tzinfo=timezone.utc)
        events=[CalendarBooking('a','a','free',start,end,show_as='free'),CalendarBooking('b','b','cancelled',start,end,cancelled=True)]
        free=availability.calculate(events,now=now,days=1)
        self.assertEqual(len(free['ranges']),1)
        events += [CalendarBooking('c','c','busy',start,end),CalendarBooking('d','d','duplicate',start,end)]
        self.assertEqual(len(availability.calculate(events,now=now,days=1)['ranges']),2)

    def test_dst_weekend_and_elapsed_time(self):
        result=availability.calculate([],now=datetime(2026,10,30,20,45,tzinfo=timezone.utc),days=2,duration=30)
        self.assertEqual(result['ranges'][0]['date'],'2026-11-02') # Friday has <30m remaining
        self.assertEqual(result['ranges'][0]['start'],'2026-11-02T15:00:00+00:00')
        self.assertEqual(len(result['ranges']),2)
        today=availability.calculate([],now=datetime(2026,10,22,15,7,tzinfo=timezone.utc),days=1)
        self.assertEqual(today['ranges'][0]['start'],'2026-10-22T15:15:00+00:00')

    def test_missing_end_is_not_claimed_free(self):
        now=datetime(2026,10,22,12,tzinfo=timezone.utc)
        event=CalendarBooking('x','x','Incomplete',datetime(2026,10,22,15,tzinfo=timezone.utc),None)
        with self.assertRaisesRegex(ValueError,'end time'):availability.calculate([event],now=now,days=1)

    def test_refresh_combines_all_accounts_and_buffered_boundary(self):
        from unittest.mock import patch, MagicMock
        from tests import test_frontend_api as fixtures
        from mailcheck import config, db
        fixture=fixtures.FrontendApiTests();fixture.setUp()
        try:
            fixture.conn.execute("UPDATE accounts SET provider='outlook' WHERE id=?",(fixture.account_id,))
            extra=db.add_account(fixture.conn,label='extra',email='extra@test',provider='outlook',imap_host='')
            # Saved email/manual events from an IMAP account also block the shared schedule.
            imap=db.add_account(fixture.conn,label='imap',email='imap@test',imap_host='imap.test')
            fixture.conn.execute("INSERT INTO interview_events(company,start_at,end_at,created_at,updated_at) VALUES('IMAP interview','2026-10-22T18:00:00+00:00','2026-10-22T19:00:00+00:00','now','now')")
            event=fixture.conn.execute('SELECT last_insert_rowid()').fetchone()[0]
            fixture.conn.execute("INSERT INTO interview_sources(event_id,account_id,external_message_id) VALUES(?,?,?)",(event,imap,'email:imap'))
            from mailcheck.assistant import Preferences
            prefs=Preferences(lookahead_business_days=1).model_dump()
            source=MagicMock();source.fetch_calendar.return_value=[CalendarBooking('other','other','Busy',datetime(2026,10,22,16,tzinfo=timezone.utc),datetime(2026,10,22,17,tzinfo=timezone.utc))]
            with patch('mailcheck.pipeline.build_source',return_value=source):
                result=availability.refresh(fixture.conn,fixture.account_id,prefs,config.Config(),now=datetime(2026,10,22,12,tzinfo=timezone.utc))
            self.assertEqual(set(result['calendar_labels']),{'personal','extra','imap'})
            self.assertEqual(source.fetch_calendar.call_count,2)
            self.assertEqual(result['ranges'][1]['start'],'2026-10-22T17:15:00+00:00')
            self.assertEqual(result['ranges'][1]['end'],'2026-10-22T17:45:00+00:00')
            self.assertEqual(result['ranges'][0]['end'],'2026-10-22T15:45:00+00:00')
            self.assertEqual(source.fetch_calendar.call_args.kwargs['until'],datetime(2026,10,22,22,15,tzinfo=timezone.utc))
        finally:fixture.doCleanups()
