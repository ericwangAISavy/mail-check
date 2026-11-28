"""Replacing a browser session must leave worker heartbeats responsive."""
import asyncio
import threading
from unittest.mock import patch

import httpx
from starlette.requests import Request

from mailcheck.web.gateway import Login
from tests.test_workspace_gateway import system


def test_login_session_replacement_does_not_block_heartbeat_on_control_writer(system):
    app, store, _ = system
    login = next(route.endpoint for route in app.routes if getattr(route, 'path', None) == '/api/auth/login')
    original_login = store.login
    locked, release, expired = threading.Event(), threading.Event(), threading.Event()
    writers = []

    def hold_writer():
        with store.connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            locked.set()
            if not release.wait(1):
                expired.set()

    def login_before_competing_writer(*args):
        token = original_login(*args)
        writer = threading.Thread(target=hold_writer)
        writers.append(writer)
        writer.start()
        assert locked.wait(2)
        return token

    request = Request({'type': 'http', 'method': 'POST', 'path': '/api/auth/login',
                       'headers': [(b'cookie', f'offerpath_session={store.owner_token}'.encode())],
                       'client': ('127.0.0.1', 1234)})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as browser:
            task = asyncio.create_task(login(Login(username='owner', password='owner-password-123'), request))
            try:
                assert await asyncio.to_thread(locked.wait, 2)
                heartbeat = await browser.get('/_internal/ping', headers={'x-offerpath-worker': 'internal-secret'})
                assert heartbeat.status_code == 200
                assert not expired.is_set(), 'Session replacement blocked the serving loop behind a control database writer'
            finally:
                release.set()
                response = await task
            assert response.status_code == 200
            assert store.identity(store.owner_token) is None

    try:
        with patch.object(store, 'login', side_effect=login_before_competing_writer):
            asyncio.run(scenario())
    finally:
        release.set()
        for writer in writers:
            writer.join(timeout=2)
