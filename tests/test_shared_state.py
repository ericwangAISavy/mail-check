import tempfile
import unittest
from pathlib import Path

from mailcheck.shared.state import JobState, OperationLock


class SharedStateTests(unittest.TestCase):
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
