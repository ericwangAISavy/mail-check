import unittest
import httpx
from tests import test_calendar_collection as fixtures
from mailcheck.interview_pipeline import sync_status


class PipelineSyncTests(unittest.TestCase):
    setUp=fixtures.NativeCalendarTests.setUp
    source=fixtures.NativeCalendarTests.source
    collect=fixtures.NativeCalendarTests.collect

    def test_success_then_failure_keeps_last_successful_calendar_receipt(self):
        self.collect(self.source([]))
        first=sync_status(self.conn,self.a)['calendar']
        self.assertTrue(first['last_success'])
        result=self.collect(self.source(handler=lambda req:httpx.Response(403,json={'error':{'code':'ErrorAccessDenied'}})))
        self.assertTrue(result['errors'])
        current=sync_status(self.conn,self.a)['calendar']
        self.assertEqual(current['last_success'],first['last_success'])
        self.assertIn('Calendars.Read',current['error'])
