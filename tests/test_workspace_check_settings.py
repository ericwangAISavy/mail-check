import unittest
from tests import test_frontend_api as fixtures
from mailcheck import config

class WorkspaceCheckSettingsTests(unittest.TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)

    def test_saves_both_intervals_without_overwriting_either(self):
        result=self.client.post('/api/settings',json={'interval_minutes':2,'other_interval_minutes':10,'auto_check':True})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(config.load().watch.other_interval_minutes,10)
        self.client.post('/api/settings',json={'other_interval_minutes':5})
        self.assertEqual(config.load().watch.interval_minutes,2)
        self.assertEqual(self.client.get('/api/settings').json()['settings']['watch']['other_interval_minutes'],5)
        self.assertEqual(self.client.post('/api/settings',json={'other_interval_minutes':0}).status_code,400)
        self.assertEqual(config.load().watch.other_interval_minutes,5)
