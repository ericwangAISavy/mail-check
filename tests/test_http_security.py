import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from mailcheck.web.gateway import create_gateway
from tests.test_workspace_gateway import system, login


def test_login_rejects_large_body_before_pydantic(system):
    app, _, _ = system
    with TestClient(app) as client:
        response = client.post('/api/auth/login', content=b' ' * 17000, headers={'content-type': 'application/json'})
        assert response.status_code == 413


def test_chunked_login_body_is_bounded(system):
    app, _, _ = system
    async def run():
        async def chunks():
            for _ in range(20):
                yield b' ' * 1000
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
            response = await client.post('/api/auth/login', content=chunks(), headers={'content-type': 'application/json'})
            assert response.status_code == 413
    asyncio.run(run())


@pytest.mark.parametrize('headers', [{'host': '['}, [('host', 'testserver'), ('host', 'evil.test')]])
def test_malformed_or_ambiguous_host_is_rejected(system, headers):
    app, _, _ = system
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get('/api/auth/session', headers=headers).status_code == 400


def test_denied_requests_also_have_security_headers(system):
    app, _, _ = system
    with TestClient(app) as client:
        response = client.get('/api/accounts')
        assert response.status_code == 401
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-content-type-options'] == 'nosniff'
        assert response.headers['content-security-policy'].find("script-src 'self'") >= 0


def test_public_hostname_cannot_access_internal_worker_routes(system):
    _, store, pool = system
    app = create_gateway(allowed_hosts=['app.example.test'], store=store, pool=pool, start_workers=False)
    with TestClient(app, base_url='https://app.example.test') as client:
        response = client.get('/_internal/ping', headers={'x-offerpath-worker': 'internal-secret'})
        assert response.status_code == 403


def test_tunnel_profile_rejects_direct_public_requests_to_local_hostname(system):
    _, store, pool = system
    app = create_gateway(allowed_hosts=['app.example.test'], secure_cookies=True,
                         tunnel_mode=True, store=store, pool=pool, start_workers=False)
    with TestClient(app) as client:
        assert client.get('/login').status_code == 403
    with TestClient(app, base_url='https://app.example.test') as client:
        assert client.get('/login').status_code == 200
        assert client.get('/login').headers['strict-transport-security'] == 'max-age=31536000'
        result = client.post('/api/auth/login', json={'username':'owner','password':'owner-password-123'})
        assert result.status_code == 200
        assert 'Secure' in result.headers['set-cookie']
        assert client.get('/openapi.json').status_code != 200


def test_server_pins_proxy_trust_and_removes_banner():
    from mailcheck.web.server import run
    with patch('mailcheck.web.server.uvicorn.run') as serve:
        run(object(), host='127.0.0.1', port=52400)
        options = serve.call_args.kwargs
        assert options['server_header'] is False
        assert options['forwarded_allow_ips'] == '127.0.0.1,::1'
        assert options['limit_concurrency'] == 64


def test_streaming_body_has_total_deadline(monkeypatch):
    from mailcheck.web import security
    monkeypatch.setattr(security, 'BODY_TOTAL_SECONDS', .03, raising=False)
    received = []
    async def app(scope, receive, send):
        pytest.fail('timed-out request must not reach application')
    async def receive():
        await asyncio.sleep(.01)
        return {'type':'http.request','body':b' ', 'more_body':True}
    async def send(event):
        received.append(event)
    scope = {'type':'http','path':'/api/auth/login','headers':[(b'host',b'testserver')], 'method':'POST'}
    async def run():
        await asyncio.wait_for(security.HTTPBoundary(app)(scope, receive, send), timeout=.15)
    asyncio.run(run())
    assert next(event['status'] for event in received if event['type']=='http.response.start') == 408


def test_unexpected_server_errors_are_private_and_have_policies(system, monkeypatch):
    app, store, _ = system
    def crash(*args):
        raise RuntimeError('private implementation detail')
    monkeypatch.setattr(store, 'identity', crash)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/api/auth/session')
        assert response.status_code == 500
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['content-security-policy']
        assert 'private implementation detail' not in response.text


def test_tunnel_profile_refuses_plain_http_login(system):
    _, store, pool = system
    app = create_gateway(allowed_hosts=['app.example.test'], secure_cookies=True,
                         tunnel_mode=True, store=store, pool=pool, start_workers=False)
    with TestClient(app, base_url='http://app.example.test') as client:
        response = client.post('/api/auth/login', json={'username':'owner','password':'owner-password-123'})
        assert response.status_code == 400
        assert 'HTTPS' in response.json()['error']
        assert not client.cookies.get('offerpath_session')
