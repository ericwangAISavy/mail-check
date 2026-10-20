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

    def test_verification_is_revision_checked_and_owned(self):
        tab = self.setup_tab()
        body = {"operation": "00000000-0000-0000-0000-000000000010", "revision": "1", "work_date": "2026-10-20"}
        response = self.client.post(f"/api/sourcing/tabs/{tab}/verify", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["verification"]["day"], "2026-10-20")
        self.assertEqual(self.client.post(f"/api/sourcing/tabs/{tab}/verify", json=body).status_code, 200)
        stale = {**body, "operation": "00000000-0000-0000-0000-000000000011"}
        self.assertEqual(self.client.post(f"/api/sourcing/tabs/{tab}/verify", json=stale).status_code, 409)
        sign_in_bidder(self.client, 2)
        self.assertEqual(self.client.post(f"/api/sourcing/tabs/{tab}/verify", json=body).status_code, 404)

    def test_delete_tab_checks_revision_removes_rows_and_allows_recreation(self):
        tab = self.setup_tab()
        base = self.client.get(f"/api/sourcing/tabs/{tab}").json()
        stale = self.client.post(f"/api/sourcing/tabs/{tab}/delete", json={"revision": "0"})
        self.assertEqual(stale.status_code, 409)
        response = self.client.post(f"/api/sourcing/tabs/{tab}/delete", json={"revision": base["revision"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get(f"/api/sourcing/tabs/{tab}").status_code, 404)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM native_rows WHERE tab_id=?", (tab,)).fetchone()[0], 0)
        book = self.client.get("/api/sourcing").json()["books"][0]
        self.assertEqual(book["tabs"], [])
        replacement = self.client.post(f"/api/sourcing/books/{book['id']}/tabs", json={"account_id": self.account_id})
        self.assertEqual(replacement.status_code, 200, replacement.text)

    def test_bidder_cannot_delete_tabs_even_in_their_own_workbook(self):
        tab = self.setup_tab()
        sign_in_bidder(self.client, 1)
        response = self.client.post(f"/api/sourcing/tabs/{tab}/delete", json={"revision": "1"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(f"/api/sourcing/tabs/{tab}").status_code, 200)

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

    def test_daily_save_and_export_use_the_requested_date(self):
        tab = self.setup_tab()
        base = self.client.get(f"/api/sourcing/tabs/{tab}").json()
        change = {
            "row_id": base["row_ids"][1],
            "column_id": base["columns"][0]["id"],
            "expected_version": 0,
            "value": "Dated job",
        }
        body = {
            "operation": "00000000-0000-0000-0000-000000000011",
            "changes": [change],
            "work_date": "2026-10-15",
        }
        response = self.client.post(f"/api/sourcing/tabs/{tab}/save", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["row_dates"][1], "2026-10-15")
        exported = self.client.get(
            f"/api/sourcing/tabs/{tab}/export?work_date=2026-10-15"
        )
        self.assertIn("Dated job", exported.text)
        self.assertIn("2026-10-15.csv", exported.headers["content-disposition"])
        self.assertNotIn(
            "Dated job",
            self.client.get(f"/api/sourcing/tabs/{tab}/export?work_date=undated").text,
        )
        self.assertEqual(
            self.client.get(
                f"/api/sourcing/tabs/{tab}/export?work_date=2026-02-30"
            ).status_code,
            400,
        )
        matches = self.client.get("/api/sourcing/search?q=Dated").json()["results"]
        self.assertEqual(matches[0]["work_date"], "2026-10-15")
