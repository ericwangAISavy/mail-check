from mailcheck.sourcing_progress import ProgressStore, report


def test_progress_is_row_based_and_completed_only_after_operation_returns():
    store=ProgressStore()
    with store.track(1,'one'):
        report(2,5)
        assert store.get(1,'one') == {'stage':'filtering','processed':2,'total':5}
    assert store.get(1,'one')['stage']=='complete'
    assert store.get(2,'one') is None


def test_failed_operation_does_not_report_complete():
    store=ProgressStore()
    try:
        with store.track(1,'bad'):
            report(1,3)
            raise ValueError('invalid')
    except ValueError:
        pass
    assert store.get(1,'bad')['stage']=='error'

from tests import test_native_sourcing as native_fixtures
import unittest
import uuid


class SourcingProgressApiTests(unittest.TestCase):
    setUp=native_fixtures.NativeSheetTests.setUp
    tab=native_fixtures.NativeSheetTests.tab
    snapshot=native_fixtures.NativeSheetTests.snapshot

    def test_append_returns_matching_completed_progress(self):
        operation=str(uuid.uuid4())
        response=self.client.post(f'/api/sourcing/tabs/{self.tab_id}/append',json={
            'operation':operation,'revision':self.snapshot()['revision'],
            'rows':[['Acme','Engineer','https://jobs.test/1'],['Acme','Engineer','https://jobs.test/1']]})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['filtered']['duplicates'],1)
        state=self.client.get(f'/api/sourcing/tabs/{self.tab_id}/progress/{operation}')
        self.assertEqual(state.status_code,200,state.text)
        self.assertEqual(state.json(),{'stage':'complete','processed':2,'total':2})
        self.assertEqual(self.client.get(f'/api/sourcing/tabs/9999/progress/{operation}').status_code,404)

    def test_failed_append_reports_error_not_completion(self):
        operation=str(uuid.uuid4())
        response=self.client.post(f'/api/sourcing/tabs/{self.tab_id}/append',json={
            'operation':operation,'revision':'stale','rows':[['Acme','Engineer','https://jobs.test/1']]})
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.client.get(f'/api/sourcing/tabs/{self.tab_id}/progress/{operation}').json()['stage'],'error')

    def test_progress_is_readable_while_filter_transaction_is_running(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from unittest.mock import patch
        from mailcheck import sourcing_filters
        entered,release=Event(),Event()
        original=sourcing_filters.filter_rows
        def paused(conn,tab,ids):
            report(1,2)
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test gate expired')
            return original(conn,tab,ids)
        operation=str(uuid.uuid4())
        payload={'operation':operation,'revision':self.snapshot()['revision'],
                 'rows':[['Acme','Engineer','https://jobs.test/1'],['Beta','Engineer','https://jobs.test/2']]}
        with patch.object(sourcing_filters,'filter_rows',side_effect=paused),ThreadPoolExecutor(max_workers=1) as executor:
            pending=executor.submit(self.client.post,f'/api/sourcing/tabs/{self.tab_id}/append',json=payload)
            try:
                self.assertTrue(entered.wait(3))
                state=self.client.get(f'/api/sourcing/tabs/{self.tab_id}/progress/{operation}')
                self.assertEqual(state.json(),{'stage':'filtering','processed':1,'total':2})
            finally:
                release.set()
            self.assertEqual(pending.result(timeout=5).status_code,200)
