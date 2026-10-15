"""Google transport contracts: only fixed API hosts, typed snapshots, literal patches."""
import importlib
import unittest
import httpx


class GoogleSheetsTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('mailcheck.google_sheets'),'Google Sheets transport is not implemented')
        return importlib.import_module('mailcheck.google_sheets')

    def test_url_validation(self):
        module=self.module()
        self.assertEqual(module.spreadsheet_id('https://docs.google.com/spreadsheets/d/abc_123-XYZ/edit#gid=0'),'abc_123-XYZ')
        for value in ('https://evil.test/spreadsheets/d/abc/edit','file:///etc/passwd','https://docs.google.com.evil.test/spreadsheets/d/abc/edit'):
            with self.assertRaises(ValueError):module.spreadsheet_id(value)

    def test_snapshot_preserves_formulas_and_links(self):
        module=self.module()
        data={'sheets':[{'properties':{'sheetId':12,'title':'Profile','gridProperties':{'rowCount':100,'columnCount':3}},'data':[{'startRow':0,'rowData':[{'values':[{'userEnteredValue':{'stringValue':'Company'}},{'userEnteredValue':{'stringValue':'Role'}},{'userEnteredValue':{'stringValue':'Job link'}}]},{'values':[{'userEnteredValue':{'stringValue':'Acme'}},{'userEnteredValue':{'formulaValue':'="Engineer"'},'formattedValue':'Engineer'},{'userEnteredValue':{'stringValue':'Apply'},'hyperlink':'https://jobs.example.test/1'}]}]}]}]}
        client=module.SheetsClient(lambda:'token',client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(200,json=data))))
        snapshot=client.snapshot('abc',12)
        self.assertTrue(snapshot['rows'][1][1]['formula'])
        self.assertEqual(snapshot['rows'][1][2]['link'],'https://jobs.example.test/1')
        self.assertTrue(snapshot['revision'])

    def test_writes_are_literal_and_errors_are_safe(self):
        module=self.module();requests=[]
        def respond(req):requests.append(req);return httpx.Response(200,json={'totalUpdatedCells':1})
        client=module.SheetsClient(lambda:'token',client=httpx.Client(transport=httpx.MockTransport(respond)))
        client.write('abc',[{'range':"'Profile'!A2",'values':[['=literal']]}])
        self.assertIn(b'"valueInputOption":"RAW"',requests[0].content)
        client=module.SheetsClient(lambda:'token',client=httpx.Client(transport=httpx.MockTransport(lambda req:httpx.Response(403,json={'error':{'message':'private provider detail'}}))))
        with self.assertRaisesRegex(module.GoogleError,'edit access'):client.metadata('abc')
    def test_quota_reads_back_off_but_writes_are_not_replayed(self):
        from unittest.mock import patch
        module=self.module();requests=[]
        def respond(req):requests.append(req);return httpx.Response(429,headers={'Retry-After':'0'},json={}) if len(requests)<3 else httpx.Response(200,json={})
        client=module.SheetsClient(lambda:'token',client=httpx.Client(transport=httpx.MockTransport(respond)))
        with patch.object(module.time,'sleep') as wait:
            client.metadata('abc');self.assertEqual(wait.call_count,2)
        requests.clear()
        with self.assertRaises(module.GoogleError):client.write('abc',[])
        self.assertEqual(len(requests),1)
