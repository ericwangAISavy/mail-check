import uuid
import unittest
import json

from tests import test_native_sourcing as fixtures


class LinkHistoryTests(unittest.TestCase):
    setUp = fixtures.NativeSheetTests.setUp
    tab = fixtures.NativeSheetTests.tab
    snapshot = fixtures.NativeSheetTests.snapshot

    def add_links(self):
        base = self.snapshot()
        first = self.native.append(self.conn, self.tab(), 'first-day', base['revision'],
            [['Acme', 'Engineer', 'https://jobs.test/first']], work_date='2026-10-01')
        self.native.append(self.conn, self.tab(), 'second-day', first['revision'],
            [['Beta', 'Engineer', 'https://jobs.test/second']], work_date='2026-10-10')

    def test_deleted_bidder_cleanup_is_scoped_and_retry_safe(self):
        self.add_links()
        self.conn.execute("UPDATE bidders SET removed_at='2026-11-18' WHERE id=1")
        self.conn.commit()
        url = f'/api/accounts/{self.account_id}/link-history'
        listing = self.client.get(url)
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.json()['bidders'][0]['link_count'], 2)
        self.assertTrue(listing.json()['bidders'][0]['deleted'])
        scope = {'bidder_id': 1, 'start': '2026-10-01', 'end': '2026-10-01'}
        preview = self.client.post(url + '/preview', json=scope)
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()['link_count'], 1)
        body = {**scope, 'preview_token': preview.json()['preview_token'], 'operation': str(uuid.uuid4())}
        result = self.client.post(url + '/clear', json=body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['deleted'], 1)
        self.assertEqual(self.client.post(url + '/clear', json=body).json(), result.json())
        self.assertEqual(self.client.get(url).json()['bidders'][0]['link_count'], 1)

    def test_stale_preview_and_invalid_range_are_rejected(self):
        self.add_links()
        url = f'/api/accounts/{self.account_id}/link-history'
        scope = {'bidder_id': 1}
        preview = self.client.post(url + '/preview', json=scope)
        self.assertEqual(preview.status_code, 200)
        self.conn.execute('UPDATE native_tabs SET revision=revision+1 WHERE id=?', (self.tab_id,))
        self.conn.commit()
        result = self.client.post(url + '/clear', json={**scope,
            'preview_token': preview.json()['preview_token'], 'operation': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(self.client.post(url + '/preview', json={**scope,
            'start': '2026-10-10', 'end': '2026-10-01'}).status_code, 422)
        self.assertEqual(self.client.get('/api/accounts/999999/link-history').status_code, 404)

    def test_partial_cleanup_preserves_other_links_in_import_copy(self):
        self.add_links()
        self.conn.execute("INSERT INTO sourcing_books(id,bidder_id,spreadsheet_id,title) VALUES(22,1,'old','Old')")
        snapshot = {'rows': [
            [{'value': 'Company'}, {'value': 'Role'}, {'value': 'Link'}],
            [{'value': 'Acme'}, {'value': 'Engineer'}, {'link': 'https://jobs.test/first'}],
            [{'value': 'Beta'}, {'value': 'Engineer'}, {'value': 'https://jobs.test/second'}],
        ]}
        self.conn.execute('''INSERT INTO sourcing_tabs(id,book_id,sheet_id,account_id,account_label,title,snapshot)
            VALUES(22,22,1,?,'personal','Old',?)''', (self.account_id, json.dumps(snapshot)))
        self.conn.execute('UPDATE native_tabs SET legacy_tab_id=22 WHERE id=?', (self.tab_id,))
        self.conn.execute("INSERT INTO sourcing_operations(id,tab_id,payload,status,created_at) VALUES('old-save',22,'{}','applied',0)")
        self.conn.commit()
        url = f'/api/accounts/{self.account_id}/link-history'
        scope = {'bidder_id': 1, 'start': '2026-10-01', 'end': '2026-10-01'}
        preview = self.client.post(url + '/preview', json=scope).json()
        result = self.client.post(url + '/clear', json={**scope, 'preview_token': preview['preview_token'],
            'operation': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 200, result.text)
        copy = self.conn.execute('SELECT snapshot FROM sourcing_tabs WHERE id=22').fetchone()
        self.assertIsNotNone(copy)
        self.assertNotIn('https://jobs.test/first', copy[0])
        self.assertIn('https://jobs.test/second', copy[0])
        self.assertEqual(len(json.loads(copy[0])['rows']), 2)
        self.assertIsNotNone(self.conn.execute("SELECT id FROM sourcing_operations WHERE id='old-save'").fetchone())

    def test_unreadable_import_rolls_back_cleanup(self):
        self.add_links()
        self.conn.execute("INSERT INTO sourcing_books(id,bidder_id,spreadsheet_id,title) VALUES(22,1,'old','Old')")
        self.conn.execute('''INSERT INTO sourcing_tabs(id,book_id,sheet_id,account_id,account_label,title,snapshot)
            VALUES(22,22,1,?,'personal','Old','broken-json')''', (self.account_id,))
        self.conn.execute('UPDATE native_tabs SET legacy_tab_id=22 WHERE id=?', (self.tab_id,))
        self.conn.commit()
        url = f'/api/accounts/{self.account_id}/link-history'
        scope = {'bidder_id': 1}
        preview = self.client.post(url + '/preview', json=scope).json()
        response = self.client.post(url + '/clear', json={**scope, 'preview_token': preview['preview_token'],
            'operation': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertEqual(self.client.get(url).json()['bidders'][0]['link_count'], 2)

    def test_cleanup_releases_duplicate_links_and_preserves_other_bidder(self):
        self.add_links()
        book = self.native.create_book(self.conn, 2, 'Other')
        tab_id = self.native.create_tab(self.conn, book, self.account_id, 'Other')
        tab = self.native.owned(self.conn, tab_id, self.principal)
        snapshot = self.native.snapshot(self.conn, tab)
        self.native.append(self.conn, tab, 'other-links', snapshot['revision'],
            [['Gamma', 'Engineer', 'https://jobs.test/other']], work_date='2026-10-01')
        self.conn.execute('UPDATE native_tabs SET archived=1 WHERE id=?', (self.tab_id,))
        self.conn.commit()
        url = f'/api/accounts/{self.account_id}/link-history'
        preview = self.client.post(url + '/preview', json={'bidder_id': 1}).json()
        result = self.client.post(url + '/clear', json={'bidder_id': 1,
            'preview_token': preview['preview_token'], 'operation': str(uuid.uuid4())})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()['deleted'], 2)
        self.assertEqual(self.client.get(url).json()['bidders'][0]['id'], 2)
        snapshot = self.native.snapshot(self.conn, tab)
        self.native.append(self.conn, tab, 'reuse-link', snapshot['revision'],
            [['Acme', 'Engineer', 'https://jobs.test/first']], work_date='2026-11-18')
        self.assertEqual(self.client.get(url).json()['bidders'][0]['link_count'], 2)

    def test_bidder_viewer_cannot_preview_or_clear_history(self):
        from fastapi.testclient import TestClient
        from mailcheck.web.app import create_app
        headers = {'x-offerpath-worker': 'worker-secret', 'x-offerpath-viewer': 'bidder',
                   'x-offerpath-bidder': '1'}
        url = f'/api/accounts/{self.account_id}/link-history'
        with TestClient(create_app(worker_secret='worker-secret')) as client:
            self.assertEqual(client.get(url, headers=headers).status_code, 403)
            self.assertEqual(client.post(url + '/preview', json={'bidder_id': 1}, headers=headers).status_code, 403)
            self.assertEqual(client.post(url + '/clear', json={'bidder_id': 1,
                'preview_token': 'a' * 64, 'operation': str(uuid.uuid4())}, headers=headers).status_code, 403)
