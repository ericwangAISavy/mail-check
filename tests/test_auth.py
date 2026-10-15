"""Authentication and authorization use the real file store and real HTTP cookies."""
import json
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from mailcheck import config
from mailcheck.web.app import create_app
from mailcheck.web.auth import COOKIE


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name, value in (("config_path", self.root / "config.toml"), ("db_path", self.root / "mail.db")):
            active = patch.object(config, name, return_value=value)
            active.start()
            self.addCleanup(active.stop)
        active = patch("mailcheck.web.app._scheduler_started.is_set", return_value=True)
        active.start()
        self.addCleanup(active.stop)
        self.app = create_app(allowed_hosts=["mail.example.test"])
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def login(self, role="admin", password=None, client=None):
        return (client or self.client).post("/api/auth/login", json={"role": role, "password": password or role})

    def test_anonymous_cannot_read_data_or_write(self):
        self.assertEqual(self.client.get("/api/auth/session").json(), {"role": None})
        for path in ("/api/bootstrap", "/api/dashboard", "/api/accounts", "/api/settings", "/api/messages/1"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 401)
        self.assertEqual(self.client.post("/api/check", json={}).status_code, 401)
        self.assertEqual(self.client.get("/settings", follow_redirects=False).headers["location"], "/login")
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_default_login_and_private_hashed_file(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/auth/session").json(), {"role": "admin"})
        path = self.root / "web-auth.json"
        data = json.loads(path.read_text())
        self.assertEqual(set(data["users"]), {"admin", "guest"})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for role in ("admin", "guest"):
            self.assertNotEqual(data["users"][role]["hash"], role)
            self.assertEqual(len(data["users"][role]["hash"]), 64)
        self.assertEqual(self.client.get("/api/settings").status_code, 200)
        self.assertNotIn(data["secret"], self.client.get("/api/settings").text)

    def test_admin_can_access_all_pages(self):
        self.login()
        for path in ("/", "/dashboard", "/accounts", "/settings", "/api/triage", "/api/accounts", "/api/settings"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_guest_can_only_read_dashboard_and_its_reader(self):
        self.assertEqual(self.login("guest").status_code, 200)
        for path in ("/dashboard", "/api/dashboard", "/api/bootstrap", "/api/dashboard/accounts"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get("/", follow_redirects=False).headers["location"], "/dashboard")
        self.assertEqual(self.client.get("/api/messages/999").status_code, 404)
        for path in ("/settings", "/accounts", "/api/triage", "/api/accounts", "/api/settings", "/api/status", "/api/outlook/status", "/api/messages/1/body"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 403)
        for path in ("/api/auth/password", "/api/check", "/api/settings", "/api/accounts", "/api/messages/1/handled", "/api/reclassify"):
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json={"role": "guest", "password": "new"}).status_code, 403)

    def test_admin_changes_guest_password_and_revokes_existing_guest_sessions(self):
        with TestClient(self.app) as guest:
            self.login("guest", client=guest)
            self.login()
            response = self.client.post("/api/auth/password", json={"role": "guest", "password": "a new guest password"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(guest.get("/api/dashboard").status_code, 401)
            self.assertEqual(self.login("guest", client=guest).status_code, 401)
            self.assertEqual(self.login("guest", "a new guest password", guest).status_code, 200)
            self.assertEqual(self.client.get("/api/settings").status_code, 200)
        with TestClient(create_app()) as restarted:
            self.assertEqual(self.login("guest", "a new guest password", restarted).status_code, 200)

    def test_admin_password_change_revokes_admin_session(self):
        self.login()
        self.assertEqual(self.client.post("/api/auth/password", json={"role": "admin", "password": "new admin password"}).status_code, 200)
        self.assertEqual(self.client.get("/api/settings").status_code, 401)
        self.assertEqual(self.client.post("/api/auth/logout", json={}).status_code, 200)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login("admin", "new admin password").status_code, 200)

    def test_logout_and_cookie_flags(self):
        response = self.login()
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertIn("SameSite=strict", response.headers["set-cookie"])
        self.assertEqual(self.client.post("/api/auth/logout", json={}).status_code, 200)
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        with TestClient(create_app(secure_cookies=True), base_url="https://testserver") as secure:
            response = self.login(client=secure)
            self.assertIn("Secure", response.headers["set-cookie"])
            self.assertEqual(secure.get("/api/dashboard").status_code, 200)

    def test_tampered_and_expired_sessions_are_rejected(self):
        self.login()
        token = self.client.cookies.get(COOKIE)
        self.client.cookies.clear()
        self.client.cookies.set(COOKIE, token + "x")
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        self.client.cookies.set(COOKIE, token)
        with patch("mailcheck.web.auth.time.time", return_value=time.time() + 13 * 3600):
            self.assertEqual(self.client.get("/api/dashboard").status_code, 401)

    def test_host_allowlist_and_exact_origin(self):
        self.assertEqual(self.client.get("/login", headers={"host": "attacker.test"}).status_code, 403)
        with TestClient(self.app, base_url="http://mail.example.test") as public:
            self.assertEqual(public.get("/login").status_code, 200)
            self.assertEqual(public.post("/api/auth/login", json={"role": "admin", "password": "admin"}, headers={"origin": "http://mail.example.test"}).status_code, 200)
            for origin in ("https://evil.test", "http://mail.example.test:9999", "https://mail.example.test", "null"):
                self.assertEqual(public.post("/api/auth/password", json={"role": "guest", "password": "oops"}, headers={"origin": origin}).status_code, 403)

    def test_failed_sign_in_is_rate_limited(self):
        for _ in range(10):
            self.assertEqual(self.login(password="wrong").status_code, 401)
        response = self.login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers["retry-after"], "60")

    def test_corrupt_auth_file_fails_closed(self):
        self.login()
        (self.root / "web-auth.json").write_text('{"secret":"broken"}')
        self.assertEqual(self.client.get("/api/settings").status_code, 503)
        self.assertEqual(self.login().status_code, 503)
        self.assertEqual((self.root / "web-auth.json").read_text(), '{"secret":"broken"}')

    def test_invalid_password_change_leaves_credentials_unchanged(self):
        self.login()
        for payload in ({"role": "guest", "password": ""}, {"role": "root", "password": "x"}, {"role": "admin", "password": "x" * 257}):
            self.assertEqual(self.client.post("/api/auth/password", json=payload).status_code, 422)
        self.assertEqual(self.login("guest").status_code, 200)


if __name__ == "__main__":
    unittest.main()
