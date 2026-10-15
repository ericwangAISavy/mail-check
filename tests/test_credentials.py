"""Unavailable OS stores must fail per account and leave sign-in recoverable."""
import time
import unittest
from unittest.mock import patch

import keyring
from mailcheck import config, db, outlook_auth, pipeline, secrets
from mailcheck.web import app as web
from tests import test_review_fixes as review_fixtures


class CredentialErrors(unittest.TestCase):
    def test_imap_store_errors_are_safe_domain_errors(self):
        for method, operation in (
            ("get_password", lambda: secrets.get_account_password("work")),
            ("set_password", lambda: secrets.set_account_password("work", "test-password")),
            ("delete_password", lambda: secrets.delete_account_password("work")),
        ):
            with self.subTest(operation=method), patch.object(keyring, method, side_effect=keyring.errors.NoKeyringError("backend failure")):
                with self.assertRaisesRegex(secrets.SecretError, "credential store is unavailable or locked"):
                    operation()

    def test_outlook_store_errors_are_handled_by_the_provider(self):
        for method, operation in (
            ("get_password", lambda: outlook_auth.load_cache("work")),
            ("set_password", lambda: outlook_auth._write_blob("work", "synthetic-cache")),
            ("delete_password", lambda: outlook_auth.delete_cache("work")),
            ("get_password", lambda: outlook_auth.has_cache("work")),
        ):
            with self.subTest(operation=method), patch.object(keyring, method, side_effect=keyring.errors.NoKeyringError("backend failure")):
                with self.assertRaisesRegex(outlook_auth.OutlookAuthError, "credential store is unavailable or locked"):
                    operation()


class CredentialApiTests(unittest.TestCase):
    setUp = review_fixtures.ReviewFixTests.setUp

    def test_connection_test_reports_store_error_instead_of_crashing(self):
        with patch.object(keyring,"get_password",side_effect=keyring.errors.NoKeyringError("backend failure")):
            response = self.client.post('/api/accounts/personal/test')
        self.assertEqual(response.status_code,400)
        self.assertIn('credential store',response.json()['error'])

    def test_failed_credential_cleanup_keeps_account_recoverable(self):
        with patch.object(keyring,"delete_password",side_effect=keyring.errors.NoKeyringError("backend failure")):
            response = self.client.post('/api/accounts/personal/delete')
        self.assertEqual(response.status_code,400)
        self.assertIsNotNone(db.get_account(self.conn,'personal'))

    def test_one_locked_account_does_not_abort_other_accounts(self):
        db.add_account(self.conn,label='second',email='second@example.test')
        with patch.object(pipeline,'fetch_account',side_effect=[secrets.SecretError('credential store locked'),[]]) as fetch:
            result = pipeline.check_once(self.conn, config.Config())
        self.assertEqual(fetch.call_count,2)
        self.assertEqual(result.accounts_checked,1)
        self.assertEqual(len(result.errors),1)

    def test_outlook_failure_reaches_failed_state_even_if_cleanup_fails(self):
        pending = outlook_auth.PendingFlow(label='work',client_id='test',flow={'user_code':'test','verification_uri':'https://example.test','expires_at':time.time()+900})
        cfg = config.Config();cfg.outlook.client_id='test'
        with patch.dict(web._outlook,{'pending':None,'active_id':None,'state':'idle','message':'','email':''}), \
             patch.object(config,'load',return_value=cfg), \
             patch.object(outlook_auth,'begin_device_flow',return_value=pending), \
             patch.object(outlook_auth,'complete_device_flow',side_effect=outlook_auth.OutlookAuthError('Could not save token')), \
             patch.object(keyring,'delete_password',side_effect=keyring.errors.NoKeyringError('backend failure')):
            self.assertEqual(self.client.post('/api/outlook/start',json={'label':'work'}).status_code,200)
            for _ in range(100):
                if web._outlook['state'] != 'waiting':break
                time.sleep(0.005)
            status=self.client.get('/api/outlook/status').json()
            self.assertEqual(status['state'],'failed')
            self.assertIn('credential',status['message'])
            self.assertIsNone(web._outlook['pending'])
