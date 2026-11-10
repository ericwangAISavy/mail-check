import unittest
from unittest.mock import patch
from tests import test_frontend_api as fixtures


class InvitationMatchesApiTests(unittest.TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)

    def test_missing_and_read_only_matching(self):
        self.assertEqual(self.client.get('/api/interviews/999/job-matches').status_code, 404)
        self.conn.execute("INSERT INTO interview_events(id,company,created_at,updated_at) VALUES(1,'Acme','2026','2026')")
        self.conn.commit()
        def matcher(conn, event, sources, **kwargs):
            self.assertEqual(conn.execute('PRAGMA query_only').fetchone()[0], 1)
            self.assertEqual(event['company'], 'Acme')
            return {'matches': [], 'total': 0, 'next_cursor': None}
        with patch('mailcheck.interview_job_matches.match_jobs', side_effect=matcher):
            response = self.client.get('/api/interviews/1/job-matches')
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['total'], 0)
        self.assertEqual(self.client.get('/api/interviews/1/job-matches?cursor=bad').status_code, 400)
        self.assertEqual(self.client.get('/api/interviews/1/job-matches?limit=101').status_code, 422)

    def test_calendar_description_survives_processing_and_updates(self):
        from datetime import datetime, timezone
        from types import SimpleNamespace
        from mailcheck import db, interviews
        booking = SimpleNamespace(provider_id='native-booking', uid='uid-1', recurrence_id='',
            title='Acme recruiter screen', organizer_email='recruiter@acme.test',
            updated_at=datetime.now(timezone.utc), start=datetime.now(timezone.utc), end=None,
            timezone='UTC', meeting_platform=None, meeting_url=None, location=None,
            organizer_name=None, participants=[], calendar_name='Calendar', original_timezone='UTC',
            cancelled=False, description='x' * 20000)
        account = db.get_account(self.conn, 'personal')
        interviews._save_calendar_booking(self.conn, account, booking, None, analysis_enabled=False)
        source = self.conn.execute('SELECT id FROM interview_sources').fetchone()[0]
        self.assertEqual(len(self.conn.execute('SELECT description FROM interview_source_details').fetchone()[0]), 16000)
        booking.description = 'Job https://jobs.acme.test/42'
        interviews._save_calendar_booking(self.conn, account, booking, None, analysis_enabled=False)
        self.assertEqual(self.conn.execute('SELECT description FROM interview_source_details').fetchone()[0], booking.description)
        self.conn.execute('DELETE FROM interview_sources WHERE id=?', (source,))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM interview_source_details').fetchone()[0], 0)
