"""Only the current, validated device flow may replace account credentials."""
from types import SimpleNamespace

import pytest

from mailcheck import config, db, outlook_auth
from mailcheck.web import app as web
from tests.web_client import TestClient


@pytest.fixture
def outlook_console(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: tmp_path / "config.toml")
    monkeypatch.setattr(config, "db_path", lambda: tmp_path / "mail.db")
    cfg = config.Config()
    cfg.outlook.client_id = "test-client"
    cfg.watch.auto_check = False
    config.save(cfg)
    monkeypatch.setattr(web, "_scheduler_started", SimpleNamespace(is_set=lambda: True))
    monkeypatch.setattr(web, "_outlook", {"pending": None, "active_id": None,
        "state": "idle", "message": "", "email": ""})
    runners = []
    class DeferredThread:
        def __init__(self, *, target, daemon):
            self.target = target
        def start(self):
            runners.append(self.target)
    monkeypatch.setattr(web, "threading", SimpleNamespace(Thread=DeferredThread))
    blobs = {}
    monkeypatch.setattr(outlook_auth, "_write_blob", lambda label, blob: blobs.__setitem__(label, blob))
    monkeypatch.setattr(outlook_auth, "delete_cache", lambda label: blobs.pop(label, None))
    def load_cache(label):
        cache = SimpleNamespace(has_state_changed=True, blob="")
        cache.serialize = lambda: cache.blob
        return cache
    monkeypatch.setattr(outlook_auth, "load_cache", load_cache)
    def microsoft(client_id, cache):
        def acquire(flow):
            if flow.get("expires_at") == 0 and not flow.get("late_success"):
                return {"error": "expired_token"}
            cache.blob = "token:" + flow["user_code"]
            return {"access_token": "token", "id_token_claims": {
                "preferred_username": flow.get("email", "mail@example.com")}}
        return SimpleNamespace(acquire_token_by_device_flow=acquire)
    monkeypatch.setattr(outlook_auth, "_app", microsoft)
    flows = []
    def begin(label, client_id):
        pending = outlook_auth.PendingFlow(label, client_id, {"user_code": f"CODE-{len(flows) + 1}", "expires_at": 9999999999})
        flows.append(pending)
        return pending
    monkeypatch.setattr(outlook_auth, "begin_device_flow", begin)
    client = TestClient(web.create_app())
    yield SimpleNamespace(client=client, blobs=blobs, runners=runners, flows=flows)
    client.close()


@pytest.mark.parametrize("late_success", [False, True])
def test_superseded_flow_cannot_erase_newer_success(outlook_console, late_success):
    ctx = outlook_console
    assert ctx.client.post("/api/outlook/start", json={"label": "mail"}).status_code == 200
    ctx.flows[0].flow["late_success"] = late_success
    assert ctx.client.post("/api/outlook/start", json={"label": "mail"}).status_code == 200
    ctx.runners[1]()
    assert ctx.blobs["mail"] == "token:CODE-2"
    ctx.runners[0]()
    assert ctx.blobs.get("mail") == "token:CODE-2"
    assert ctx.client.get("/api/outlook/status").json()["state"] == "connected"


@pytest.mark.parametrize("outcome", ["cancel", "cancel_late_success", "failure", "wrong_account"])
def test_unsuccessful_reconnect_preserves_existing_credentials(outlook_console, outcome):
    ctx = outlook_console
    with db.session() as conn:
        db.add_account(conn, label="mail", email="mail@example.com", provider="outlook")
    ctx.blobs["mail"] = "existing-token"
    assert ctx.client.post("/api/outlook/start", json={"label": "mail", "reconnect": True}).status_code == 200
    if outcome.startswith("cancel"):
        ctx.flows[0].flow["late_success"] = outcome == "cancel_late_success"
        assert ctx.client.post("/api/outlook/cancel").status_code == 200
    elif outcome == "failure":
        ctx.flows[0].flow["expires_at"] = 0
    else:
        ctx.flows[0].flow["email"] = "other@example.com"
    ctx.runners[0]()
    assert ctx.blobs.get("mail") == "existing-token"
    with db.session() as conn:
        assert db.get_account(conn, "mail").email == "mail@example.com"


def test_direct_device_flow_keeps_immediate_persistence(outlook_console):
    ctx = outlook_console
    pending = outlook_auth.PendingFlow("mail", "test-client", {"user_code": "DIRECT"})
    assert outlook_auth.complete_device_flow(pending) == "mail@example.com"
    assert ctx.blobs["mail"] == "token:DIRECT"


def test_database_failure_after_sign_in_exits_waiting_state(outlook_console, monkeypatch):
    ctx = outlook_console
    assert ctx.client.post("/api/outlook/start", json={"label": "mail"}).status_code == 200
    def failed_insert(*args, **kwargs):
        raise RuntimeError("database unavailable")
    monkeypatch.setattr(db, "add_account", failed_insert)
    ctx.runners[0]()
    status = ctx.client.get("/api/outlook/status").json()
    assert status["state"] == "failed"
    assert "database unavailable" in status["message"]
