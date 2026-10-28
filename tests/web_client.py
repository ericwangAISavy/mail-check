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


def sign_in_bidder(client, bidder_id=1, password='bidder-password'):
    """Provision a named test principal without relying on shared guest access."""
    from mailcheck import db
    with db.session() as conn:
        if not conn.execute('SELECT 1 FROM bidders WHERE id=?',(bidder_id,)).fetchone():
            conn.execute('INSERT INTO bidders(id,name,created_at,login_enabled) VALUES(?,?,?,1)',(bidder_id,f'Bidder {bidder_id}','2026-01-01'))
        conn.execute('UPDATE bidders SET login_enabled=1 WHERE id=?',(bidder_id,))
    client.app.state.auth_store.set_bidder_password(bidder_id,password)
    result=client.post('/api/auth/login',json={'role':'bidder','bidder_id':bidder_id,'password':password})
    assert result.status_code==200,result.text
    return result
