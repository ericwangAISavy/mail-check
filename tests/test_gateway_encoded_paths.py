"""Use ASGI wire semantics: TestClient decodes URL paths an extra time."""
import asyncio
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from tests.test_workspace_gateway import system


@pytest.mark.parametrize('method', ['GET', 'POST'])
@pytest.mark.parametrize('path', [
    '/api/%2573ettings', '/api/%2572ules', '/api/%2561utocheck',
])
def test_encoded_owner_settings_cannot_be_dispatched_by_added_admin(system, method, path):
    app, store, pool = system
    workspace = store.create_admin(store.owner_token, 'alice', 'Alice', 'temporary-pass-123')
    temporary = store.login('alice', 'temporary-pass-123', 'setup')
    token = store.change_password(temporary, 'alice-final-pass-123')
    client_type = httpx.AsyncClient
    worker_app = FastAPI()
    accessed_settings = []

    @worker_app.api_route('/api/{section}', methods=['GET', 'POST'])
    def settings(section: str):
        if section in ('settings', 'rules', 'autocheck'):
            accessed_settings.append(section)
            return {'ok': True}
        from fastapi import HTTPException
        raise HTTPException(404)

    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as browser:
            with patch('mailcheck.web.gateway.httpx.AsyncClient', side_effect=lambda **kwargs:
                       client_type(transport=httpx.ASGITransport(app=worker_app), **kwargs)):
                response = await browser.request(method, path, headers={
                    'cookie': f'offerpath_session={token}',
                    'x-offerpath-workspace': workspace,
                })
        assert response.status_code == 404, response.text
        assert accessed_settings == []

    asyncio.run(scenario())


@pytest.mark.parametrize(('path', 'label'), [
    ('/api/accounts/100%2520%20Inbox/outgoing', '100%20 Inbox'),
    ('/api/accounts/Inbox%3Fprimary%23one/outgoing', 'Inbox?primary#one'),
])
def test_proxy_preserves_encoded_account_labels(system, path, label):
    app, store, _ = system
    client_type = httpx.AsyncClient
    worker_app = FastAPI()

    @worker_app.get('/api/accounts/{label}/outgoing')
    def outgoing(label: str):
        return {'label': label}

    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as browser:
            with patch('mailcheck.web.gateway.httpx.AsyncClient', side_effect=lambda **kwargs:
                       client_type(transport=httpx.ASGITransport(app=worker_app), **kwargs)):
                response = await browser.get(path, headers={
                    'cookie': f'offerpath_session={store.owner_token}',
                    'x-offerpath-workspace': 'legacy',
                })
        assert response.status_code == 200, response.text
        assert response.json() == {'label': label}

    asyncio.run(scenario())
