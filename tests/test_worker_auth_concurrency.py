"""Bidder membership reads must not occupy the worker's HTTP event loop."""
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest

from mailcheck.web import app as web


@pytest.mark.parametrize("managed", [True, False])
def test_worker_membership_lookup_runs_outside_http_event_loop(monkeypatch, managed):
    monkeypatch.setattr(web, '_scheduler_started', SimpleNamespace(is_set=lambda: True))
    app = web.create_app(worker_secret='private' if managed else None, allowed_hosts=['testserver'])
    loop_reads = []
    identity_reads = []

    def identity(token):
        try:
            asyncio.get_running_loop()
            identity_reads.append(True)
        except RuntimeError:
            identity_reads.append(False)
        return {'role': 'bidder', 'bidder_id': 1}

    monkeypatch.setattr(app.state.auth_store, 'identity', identity)

    @contextmanager
    def database():
        try:
            asyncio.get_running_loop()
            loop_reads.append(True)
        except RuntimeError:
            loop_reads.append(False)
        yield SimpleNamespace(execute=lambda *args: SimpleNamespace(fetchone=lambda: {'id': 1}))

    monkeypatch.setattr(web.db, 'session', database)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            response = await client.get('/dashboard', headers={
                'x-offerpath-worker': 'private', 'x-offerpath-viewer': 'bidder',
                'x-offerpath-bidder': '1'})
        assert response.status_code == 200

    asyncio.run(scenario())
    assert loop_reads == [False], 'SQLite membership checks block all worker HTTP requests'
    assert identity_reads == ([] if managed else [False])
