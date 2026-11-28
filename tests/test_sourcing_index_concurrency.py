"""Job source navigation remains a reader after workbook reconciliation."""
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
import pytest

from mailcheck import db
from mailcheck.web import sourcing_routes


@pytest.fixture
def sourcing_index(tmp_path, monkeypatch):
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(tmp_path / 'maintenance.lock'))
    path = tmp_path / 'mail.db'
    conn = db.connect(path)
    conn.execute("INSERT INTO bidders(name,created_at) VALUES('Bidder','2026-01-01')")
    conn.commit()
    app = FastAPI()

    sourcing_routes.install(app, lambda: None, False)
    routes = getattr(app.routes[-1], 'original_router', app).routes
    endpoint = next(route.endpoint for route in routes
                    if route.path == '/api/sourcing' and 'GET' in route.methods)
    request = SimpleNamespace(state=SimpleNamespace(role='admin', bidder_id=None))
    original_session = db.session
    with patch.object(db, 'session', side_effect=lambda: original_session(path)):
        yield conn, lambda: endpoint(request)
    conn.close()


def test_existing_workbook_index_reads_during_another_writer(sourcing_index):
    conn, get_index = sourcing_index
    conn.execute("INSERT INTO native_books(bidder_id,title) VALUES(1,'Applications')")
    conn.commit()
    conn.execute('BEGIN IMMEDIATE')
    try:
        response = get_index()
        assert response['books'][0]['bidder_id'] == 1
    finally:
        conn.rollback()


def test_missing_legacy_workbook_is_still_created(sourcing_index):
    conn, get_index = sourcing_index
    response = get_index()
    assert response['books'][0]['bidder_id'] == 1
    assert conn.execute('SELECT COUNT(*) FROM native_books').fetchone()[0] == 1
