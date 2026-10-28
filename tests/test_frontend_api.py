"""JSON page data contracts for the React console."""

from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from tests.web_client import TestClient

from mailcheck import config, db
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.web import app as web_app
from mailcheck.web.app import create_app


class FrontendApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "mail.db"
        self.conn = db.connect(self.path)
        self.addCleanup(self.conn.close)
        self.account_id = db.add_account(
            self.conn, label="personal", email="me@example.test", imap_host="imap.example.test"
        )
        self.patches = [
            patch.object(config, "db_path", return_value=self.path),
            patch.object(config, "config_dir", return_value=self.root),
            patch.object(config, "config_path", return_value=self.root / "config.toml"),
        ]
        for active in self.patches:
            active.start()
            self.addCleanup(active.stop)
        self.client = TestClient(create_app())
        self.addCleanup(self.client.close)

    def test_spa_shell_revalidates_html_and_contains_a_boot_recovery_message(self):
        response = self.client.get("/?view=queue&days=30")

        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response.headers.get("cache-control", ""))
        self.assertIn("Starting OfferPath", response.text)
        self.assertIn("reload this page", response.text)

    def test_check_routes_select_mail_or_calendar_and_share_lock(self):
        with patch.object(web_app, "_state", return_value={"has_accounts": True, "llm_ready": True}), \
             patch.object(web_app, "_job_lock") as lock, \
             patch.object(web_app, "_run_check") as run:
            lock.acquire.return_value = True
            for path, body, expected in [
                ("/api/check", {}, "mail"),
                ("/api/check", {"mode": "calendar"}, "calendar"),
                ("/api/interviews/sync", {"mode": "mail"}, "calendar"),
            ]:
                self.assertEqual(self.client.post(path, json=body).status_code, 200)
                self.assertEqual(run.call_args.args[0].mode, expected)
            lock.acquire.return_value = False
            self.assertEqual(self.client.post("/api/check", json={}).status_code, 409)

    def test_only_mail_checks_require_a_model(self):
        with patch.object(web_app, "_state", return_value={"has_accounts": True, "llm_ready": False}), \
             patch.object(web_app, "_job_lock"), patch.object(web_app, "_run_check") as run:
            self.assertEqual(self.client.post("/api/check", json={}).status_code, 400)
            run.assert_not_called()
            self.assertEqual(self.client.post("/api/interviews/sync").status_code, 200)
            self.assertEqual(run.call_args.args[0].mode, "calendar")

    def test_reader_keeps_original_layout_separate_from_classification_text(self):
        from mailcheck.models import RawMessage
        from mailcheck.normalize import normalize
        url = "https://example.test/application?token=" + "a" * 180
        original = f'<style>.letter {{ padding: 24px; }}</style><table class="letter" cellpadding="12"><tr><td><h2>Next steps</h2><p><b>Hello</b> applicant</p><a href="{url}">View application</a><script>alert(1)</script><img src="x" onerror="alert(1)"></td></tr></table>'
        raw = RawMessage(message_id="html@example.test", uid="1", folder="Inbox", from_addr="hr@example.test", from_name="HR", subject="Next steps", date_utc=None, text=original, original_html=original)
        message = normalize(raw, account_id=self.account_id, account_label="personal", max_body_chars=30)
        self.assertIn("truncated", message.body)
        pk = db.upsert_message(self.conn, message)
        db.save_classification(self.conn, pk, Classification(category="application_ack"), "model", "v1")
        self.conn.commit()
        response = self.client.get(f"/api/messages/{pk}")
        self.assertEqual(response.status_code, 200)
        html = response.json()["original_html"]
        for value in ("<table", "cellpadding", "<h2>", "<b>", url, "padding: 24px"):
            self.assertIn(value, html)
        self.assertNotIn("<script", html)
        self.assertNotIn("onerror", html)
        self.assertNotIn("alert(1)", html)
        db.set_handled(self.conn, pk, True)
        db.upsert_message(self.conn, message)
        self.assertIsNotNone(db.get_triaged(self.conn, pk)["handled_at"])

    def test_legacy_reader_still_has_plain_text_fallback(self):
        pk = self.add_message("legacy")
        response = self.client.get(f"/api/messages/{pk}").json()
        self.assertIsNone(response["original_html"])
        self.assertIn("Choose a time", response["body_html"])

    def add_message(self, key, *, category="interview_invite", done=False):
        message = NormalizedMessage(
            account_id=self.account_id,
            account_label="personal",
            message_id=f"<{key}@example.test>",
            uid=str(key),
            folder="INBOX",
            from_addr="recruiter@example.test",
            from_name="Recruiter",
            subject=f"Interview at Acme {key}",
            date_utc=(datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None),
            body="Hello <script>alert(1)</script> applicant.\n\nChoose a time.",
        )
        pk = db.upsert_message(self.conn, message)
        db.save_classification(
            self.conn,
            pk,
            Classification(
                category=category,
                summary="Choose a time for your interview.",
                company="Acme",
                role="Engineer",
                action_required=True,
            ),
            "model",
            "v1",
        )
        if done:
            db.set_handled(self.conn, pk, True)
        return pk

    def test_bootstrap_exposes_readiness_navigation_and_taxonomy(self):
        self.add_message("one")

        response = self.client.get("/api/bootstrap")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("readiness", payload)
        self.assertEqual(payload["counts"]["actionable"], 1)
        self.assertTrue(payload["taxonomy"])
        self.assertTrue(payload["presets"])

    def test_triage_filters_views_and_keeps_message_bodies_out_of_rows(self):
        active = self.add_message("active")
        self.add_message("finished", done=True)

        queue = self.client.get("/api/triage?view=queue")
        completed = self.client.get("/api/triage?view=completed")

        self.assertEqual(queue.status_code, 200)
        self.assertEqual([row["pk"] for group in queue.json()["groups"] for row in group["items"]], [active])
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["view"], "completed")
        serialized_rows = str(queue.json()["groups"])
        self.assertNotIn("body_text", serialized_rows)
        self.assertNotIn("Choose a time.\\n", serialized_rows)

    def test_message_reader_returns_sanitized_body_and_404_for_missing(self):
        pk = self.add_message("one")

        response = self.client.get(f"/api/messages/{pk}")

        self.assertEqual(response.status_code, 200)
        body_html = response.json()["body_html"]
        self.assertIn("&lt;script&gt;", body_html)
        self.assertNotIn("<script>", body_html)
        self.assertEqual(self.client.get("/api/messages/999999").status_code, 404)

    def test_account_api_never_returns_credentials(self):
        response = self.client.get("/api/accounts")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["accounts"][0]["label"], "personal")
        self.assertNotIn("password", str(response.json()).lower())

    def test_settings_api_provides_editable_state_without_secrets(self):
        response = self.client.get("/api/settings")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("llm", payload["settings"])
        self.assertIn("rules", payload)
        self.assertNotIn("client_secret", str(payload).lower())

    def test_status_completion_id_changes_after_a_job(self):
        first = self.client.get("/api/status").json()
        with patch("mailcheck.web.app._job", {"running": False, "message": "Done", "detail": "",
                                                "at": "12:00", "ok": True, "stage_started": None,
                                                "completion_id": 7}):
            second = self.client.get("/api/status").json()

        self.assertIn("completion_id", first)
        self.assertEqual(second["completion_id"], 7)

    def test_built_react_app_owns_existing_routes_and_deep_links(self):
        build = self.root / "frontend_dist"
        build.mkdir()
        (build / "index.html").write_text("<div id='root'>React app</div>", encoding="utf-8")
        with patch.object(web_app, "FRONTEND_DIST", build):
            client = TestClient(create_app())
            self.addCleanup(client.close)
            for path in ("/", "/dashboard", "/accounts", "/settings", "/future/page"):
                with self.subTest(path=path):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn("React app", response.text)


if __name__ == "__main__":
    unittest.main()
