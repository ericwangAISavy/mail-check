"""Automatic payment refresh must not block readers behind a database writer."""
from contextlib import contextmanager
from datetime import date
from types import SimpleNamespace

import pytest

from mailcheck import db
from mailcheck.web import app as web


def test_payment_page_remains_readable_during_another_writer(tmp_path, monkeypatch, request):
    path = tmp_path / 'mail.db'
    writer = db.connect(path)
    reader = db.connect(path)
    request.addfinalizer(writer.close)
    request.addfinalizer(reader.close)
    reader.execute('PRAGMA busy_timeout=1')
    writer.execute("INSERT INTO bidders(name,created_at) VALUES('Alex','2026-01-01')")
    writer.commit()
    monkeypatch.setattr(web, '_scheduler_started', SimpleNamespace(is_set=lambda: True))
    app = web.create_app()
    endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', None) == '/api/payments' and 'GET' in r.methods)

    @contextmanager
    def session():
        yield reader

    monkeypatch.setattr(db, 'session', session)
    writer.execute('BEGIN IMMEDIATE')
    try:
        result = endpoint(SimpleNamespace(state=SimpleNamespace(role='admin', bidder_id=None)), week=date(2026,10,12))
        assert result['bidders'][0]['name'] == 'Alex'
        assert result['bidders'][0]['total'] == 0
        assert reader.execute('PRAGMA busy_timeout').fetchone()[0] == 1
    finally:
        writer.rollback()
        reader.close()
        writer.close()


def test_simultaneous_payment_refresh_skips_matching_without_waiting(tmp_path):
    with db.session(tmp_path / 'mail.db') as conn:
        assert web._payment_refresh_lock.acquire(blocking=False)
        statements = []
        conn.set_trace_callback(statements.append)
        try:
            web._refresh_payment_week(conn, date(2026,10,12))
            assert not statements
        finally:
            web._payment_refresh_lock.release()


def test_payment_refresh_surfaces_unrelated_sql_errors_and_recovers_lock(tmp_path, monkeypatch):
    with db.session(tmp_path / 'mail.db') as conn:
        timeout = conn.execute('PRAGMA busy_timeout').fetchone()[0]
        def invalid_verification(*args, **kwargs):
            conn.execute('SELECT * FROM missing_table_for_regression')
        monkeypatch.setattr(web.sourcing_verification, 'verify_all', invalid_verification)
        import sqlite3
        with pytest.raises(sqlite3.OperationalError, match='no such table'):
            web._refresh_payment_week(conn, date(2026,10,12))
        assert not web._payment_refresh_lock.locked()
        assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == timeout
