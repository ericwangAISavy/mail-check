"""Native sourcing APIs are usable without Google and enforce bidder ownership."""

import unittest
from tests import test_frontend_api as fixtures
from tests.web_client import sign_in_bidder


class SourcingTests(unittest.TestCase):
    def setUp(self):
        fixtures.FrontendApiTests.setUp(self)
        for name in ("Alex", "Blair"):
            self.conn.execute(
                "INSERT INTO bidders(name,created_at) VALUES(?,'2026-10-15')", (name,)
            )
        self.conn.execute(
            "INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-01-01')",
            (self.account_id,),
        )
        self.conn.commit()

    def setup_tab(self):
        book = self.client.post(
            "/api/sourcing/books", json={"bidder_id": 1, "title": "Alex jobs"}
        )
        self.assertEqual(book.status_code, 200, book.text)
        tab = self.client.post(
            f"/api/sourcing/books/{book.json()['id']}/tabs",
            json={"account_id": self.account_id, "title": "Engineering"},
        )
        self.assertEqual(tab.status_code, 200, tab.text)
        return tab.json()["id"]

    def test_setup_and_save_need_no_google_connection(self):
        tab = self.setup_tab()
        snapshot = self.client.get(f"/api/sourcing/tabs/{tab}").json()
        response = self.client.post(
            f"/api/sourcing/tabs/{tab}/save",
            json={
                "operation": "00000000-0000-0000-0000-000000000001",
                "changes": [
                    {
                        "row_id": snapshot["row_ids"][1],
                        "column_id": snapshot["columns"][0]["id"],
                        "expected_version": 0,
                        "value": "Acme",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["rows"][1][0]["value"], "Acme")
        self.assertEqual(self.client.get("/api/sourcing/google").status_code, 404)

    def test_all_sheet_capabilities_reject_other_bidders(self):
        tab = self.setup_tab()
        sign_in_bidder(self.client, 2)
        self.assertEqual(self.client.get("/api/sourcing").json()["books"], [])
        self.assertEqual(self.client.get(f"/api/sourcing/tabs/{tab}").status_code, 404)
        self.assertEqual(
            self.client.get(f"/api/sourcing/tabs/{tab}/export").status_code, 404
        )
        self.assertEqual(
            self.client.post(
                f"/api/sourcing/tabs/{tab}/structure",
                json={
                    "operation": "00000000-0000-0000-0000-000000000001",
                    "revision": "1",
                    "action": "insert_rows",
                    "count": 1,
                },
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f"/api/sourcing/tabs/{tab}/import",
                json={
                    "operation": "00000000-0000-0000-0000-000000000001",
                    "revision": "1",
                    "text": "Acme,Engineer,url",
                    "mode": "append",
                    "has_header": False,
                },
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/sourcing/search?q=Acme").json()["results"], []
        )

    def test_structure_conflicts_and_server_format_validation(self):
        tab = self.setup_tab()
        result = self.client.post(
            f"/api/sourcing/tabs/{tab}/structure",
            json={
                "operation": "00000000-0000-0000-0000-000000000001",
                "revision": "1",
                "action": "insert_rows",
                "count": 1,
            },
        )
        self.assertEqual(result.status_code, 200, result.text)
        stale = self.client.post(
            f"/api/sourcing/tabs/{tab}/structure",
            json={
                "operation": "00000000-0000-0000-0000-000000000002",
                "revision": "1",
                "action": "insert_rows",
                "count": 1,
            },
        )
        self.assertEqual(stale.status_code, 409)
        snapshot = result.json()
        bad = self.client.post(
            f"/api/sourcing/tabs/{tab}/save",
            json={
                "operation": "00000000-0000-0000-0000-000000000003",
                "changes": [
                    {
                        "row_id": snapshot["row_ids"][1],
                        "column_id": snapshot["columns"][0]["id"],
                        "expected_version": 0,
                        "style": {"background": "url(evil)"},
                    }
                ],
            },
        )
        self.assertEqual(bad.status_code, 422)
