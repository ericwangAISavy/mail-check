"""Existing console tests exercise the app as a signed-in admin."""
import tempfile
import weakref
from pathlib import Path

from fastapi.testclient import TestClient as BaseClient


class TestClient(BaseClient):
    def __init__(self, app, *args, **kwargs):
        tmp = tempfile.TemporaryDirectory()
        app.state.auth_store.path = lambda: Path(tmp.name) / "web-auth.json"
        super().__init__(app, *args, **kwargs)
        weakref.finalize(self, tmp.cleanup)
        response = self.post("/api/auth/login", json={"role": "admin", "password": "admin"})
        assert response.status_code == 200, response.text
