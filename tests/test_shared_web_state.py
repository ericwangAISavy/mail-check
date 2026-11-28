import tempfile
import unittest
from pathlib import Path

from mailcheck.workspaces import WorkspaceContext, bind_workspace


class SharedWebStateTests(unittest.TestCase):
    def test_job_and_oauth_state_are_isolated_and_job_status_persisted(self):
        from mailcheck.web.app import _job, _outlook
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            legacy = (base/'owner/config.toml', base/'owner/mailcheck.db', base/'owner/web-auth.json')
            contexts = []
            for wid in ['a'*32, 'b'*32]:
                path = base/wid
                path.mkdir()
                (path/'workspace.id').write_text(wid)
                contexts.append(WorkspaceContext.from_record({'id':wid,'root':str(path)},legacy,base/'control'))
            with bind_workspace(contexts[0]):
                _job.update(message='A', running=True)
                _outlook['active_id'] = 'flow-A'
            with bind_workspace(contexts[1]):
                self.assertFalse(_job['running'])
                self.assertIsNone(_outlook['active_id'])
                _job.update(message='B')
            with bind_workspace(contexts[0]):
                self.assertEqual(_job['message'], 'A')
                self.assertEqual(_outlook['active_id'], 'flow-A')
