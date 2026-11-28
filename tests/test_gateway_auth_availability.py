import asyncio
import sqlite3
import time
from unittest.mock import patch
import httpx
import pytest
from mailcheck.web import gateway
from tests.test_workspace_gateway import system


@pytest.mark.parametrize('method',['GET','POST'])
def test_authentication_timeout_returns_retryable_service_response(system,monkeypatch,method):
    app,store,_=system
    original=store.identity
    def slow(token):time.sleep(.2);return original(token)
    monkeypatch.setattr(store,'identity',slow)
    monkeypatch.setattr(gateway,'AUTH_REQUEST_TIMEOUT',.03,raising=False)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            start=time.monotonic()
            response=await client.request(method,'/api/auth/session',headers={'cookie':f'offerpath_session={store.owner_token}'})
            assert response.status_code==503
            assert response.headers['retry-after']=='1'
            assert time.monotonic()-start<.15
    asyncio.run(scenario())


def test_control_database_error_is_retryable_without_exposing_diagnostics(system,monkeypatch):
    app,store,_=system
    monkeypatch.setattr(store,'identity',lambda _:(_ for _ in ()).throw(sqlite3.OperationalError('private database diagnostic')))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            response=await client.get('/api/auth/session')
            assert response.status_code==503
            assert 'private database diagnostic' not in response.text
            assert response.headers['retry-after']=='1'
    asyncio.run(scenario())


@pytest.mark.parametrize('path',['/login','/static/app.js'])
def test_public_shell_and_static_files_do_not_depend_on_session_storage(system,monkeypatch,path):
    app,store,_=system
    def unavailable(_):raise AssertionError('Public file touched session storage')
    monkeypatch.setattr(store,'identity',unavailable)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            assert (await client.get(path)).status_code==200
    asyncio.run(scenario())


def test_read_deadline_includes_authentication_time(system,monkeypatch):
    app,store,_=system
    original=store.identity
    def slow(token):time.sleep(.06);return original(token)
    monkeypatch.setattr(store,'identity',slow)
    monkeypatch.setattr(gateway,'READ_REQUEST_TIMEOUT',.1)
    client_type=httpx.AsyncClient
    async def worker(request):
        await asyncio.sleep(.07)
        return httpx.Response(200,json={'ok':True})
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                result=await browser.get('/api/bootstrap',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
            assert result.status_code==504
    asyncio.run(scenario())


def test_page_deadline_does_not_interrupt_dispatched_writes(system,monkeypatch):
    app,store,_=system
    monkeypatch.setattr(gateway,'READ_REQUEST_TIMEOUT',.03)
    client_type=httpx.AsyncClient
    writes=[]
    async def worker(request):
        writes.append(request.method)
        await asyncio.sleep(.08)
        return httpx.Response(200,json={'ok':True})
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                result=await browser.post('/api/check',json={},headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
            assert result.status_code==200
            assert writes==['POST']
    asyncio.run(scenario())
