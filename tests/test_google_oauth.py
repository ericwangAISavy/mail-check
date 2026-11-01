import importlib
import unittest
from unittest.mock import patch
import httpx


class OAuthTests(unittest.TestCase):
    def test_browser_binding_and_single_use_state(self):
        self.assertIsNotNone(importlib.util.find_spec('mailcheck.google_oauth'),'Google OAuth is not implemented')
        module=importlib.import_module('mailcheck.google_oauth')
        store={}
        with patch.object(module,'read_secret',side_effect=lambda key:store.get(key)),patch.object(module,'write_secret',side_effect=lambda key,value:store.__setitem__(key,value)):
            connection=module.GoogleConnection(client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'access_token':'access','refresh_token':'refresh','expires_in':3600}))))
            connection.setup('client','secret','http://127.0.0.1:8765/api/google/callback')
            first=connection.begin()
            self.assertIn('code_challenge=',first['url'])
            with self.assertRaises(ValueError):connection.complete(first['state'],'code','wrong-cookie')
            second=connection.begin();connection.complete(second['state'],'code',second['cookie'])
            self.assertTrue(connection.status()['connected'])
            with self.assertRaises(ValueError):connection.complete(second['state'],'code',second['cookie'])
    def test_expired_state_and_failed_reconnect_preserve_connection(self):
        module=importlib.import_module('mailcheck.google_oauth');store={}
        with patch.object(module,'read_secret',side_effect=lambda key:store.get(key)),patch.object(module,'write_secret',side_effect=lambda key,value:store.__setitem__(key,value)):
            connection=module.GoogleConnection(client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json={'access_token':'access','refresh_token':'refresh','expires_in':3600}))))
            connection.setup('client','secret','https://app.test/api/google/callback')
            first=connection.begin();connection.complete(first['state'],'code',first['cookie']);old=store['tokens']
            expired=connection.begin();connection.pending[expired['state']]['expires']=0
            with self.assertRaises(ValueError):connection.complete(expired['state'],'code',expired['cookie'])
            connection.client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(400,json={'error':'invalid_grant'})))
            retry=connection.begin()
            with self.assertRaises(module.GoogleError):connection.complete(retry['state'],'bad',retry['cookie'])
            self.assertEqual(store['tokens'],old)
    def test_keyring_errors_are_recoverable(self):
        module=importlib.import_module('mailcheck.google_oauth')
        with patch.object(module.keyring,'get_password',side_effect=module.keyring.errors.KeyringError('private detail')):
            with self.assertRaisesRegex(module.GoogleError,'credential store'):module.read_secret('tokens')
    def test_failed_chunk_replacement_preserves_the_working_secret(self):
        module=importlib.import_module('mailcheck.google_oauth');store={}
        def put(service,key,value):store[key]=value
        with patch.object(module.keyring,'get_password',side_effect=lambda service,key:store.get(key)),patch.object(module.keyring,'set_password',side_effect=put),patch.object(module.keyring,'delete_password',side_effect=lambda service,key:store.pop(key,None)):
            original='old-refresh-token-'*160
            module.write_secret('tokens',original)
            calls=0
            def fail(service,key,value):
                nonlocal calls
                calls+=1
                if calls==2:raise module.keyring.errors.KeyringError('credential store failure')
                store[key]=value
            with patch.object(module.keyring,'set_password',side_effect=fail):
                with self.assertRaises(module.GoogleError):module.write_secret('tokens','new-refresh-token-'*170)
            self.assertEqual(module.read_secret('tokens'),original)
