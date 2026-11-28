import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from mailcheck.shared.state import JobState, OperationLock, RuntimeStateUnavailable


class SharedStateTests(unittest.TestCase):
    def test_transient_status_read_access_failure_retries_without_resetting_running_state(self):
        with patch('pathlib.Path.read_text',side_effect=[PermissionError('sharing conflict'),'{"running":true}']), patch('mailcheck.shared.state.time.sleep'):
            self.assertTrue(JobState(Path('unused'))['running'])

    def test_persistent_status_read_failure_reports_unknown_instead_of_idle(self):
        with patch('pathlib.Path.read_text',side_effect=PermissionError('denied')), patch('mailcheck.shared.state.time.sleep'):
            with self.assertRaises(RuntimeStateUnavailable):
                JobState(Path('unused')).snapshot()
    def test_lock_excludes_another_instance_and_releases(self):
        with tempfile.TemporaryDirectory() as folder:
            first = OperationLock(Path(folder) / 'account.lock')
            second = OperationLock(Path(folder) / 'account.lock')
            self.assertTrue(first.acquire(False))
            self.assertFalse(second.acquire(False))
            first.release()
            self.assertTrue(second.acquire(False))
            second.release()

    def test_status_is_shared_between_instances_and_workspace_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            a = JobState(Path(folder) / 'a.json')
            b = JobState(Path(folder) / 'a.json')
            other = JobState(Path(folder) / 'b.json')
            a.update(running=True, message='Collecting')
            self.assertTrue(b['running'])
            self.assertFalse(other['running'])
            self.assertEqual(b['message'], 'Collecting')

    def test_status_updates_preserve_other_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            state = JobState(Path(folder) / 'job.json')
            state.update(message='one')
            state.update(detail='two')
            self.assertEqual(state['message'], 'one')
            self.assertEqual(state['detail'], 'two')
