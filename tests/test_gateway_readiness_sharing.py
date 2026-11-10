"""Concurrent page loads share readiness without coupling their cancellation."""
import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
from starlette.requests import Request

from tests.test_workspace_gateway import system


@pytest.mark.parametrize('cancel_first', [False, True])
def test_same_workspace_loads_share_readiness(system, cancel_first):
    app, store, pool = system
    endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', None) == '/{path:path}')
    entered, release = threading.Event(), threading.Event()
    calls = []
    def ensure(workspace):
        calls.append(workspace['id'])
        entered.set()
        assert release.wait(5)
        return SimpleNamespace(port=5000, token='worker-token')
    identity = store.identity(store.owner_token)
    def request():
        async def receive(): return {'type':'http.request','body':b'','more_body':False}
        return Request({'type':'http', 'method':'GET', 'scheme':'http', 'path':'/api/payments',
                        'query_string':b'', 'headers':[(b'cookie', f'offerpath_session={store.owner_token}'.encode())],
                        'state':{'identity':identity}}, receive)
    client_type = httpx.AsyncClient
    def worker_client(**kwargs):
        return client_type(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'ok':True})), **kwargs)
    async def scenario():
        first = asyncio.create_task(endpoint('api/payments', request()))
        while not entered.is_set(): await asyncio.sleep(.001)
        second = asyncio.create_task(endpoint('api/payments', request()))
        third = asyncio.create_task(endpoint('api/payments', request()))
        await asyncio.sleep(0)  # Both callers reach their readiness await.
        if cancel_first:
            first.cancel()
            with pytest.raises(asyncio.CancelledError): await first
        release.set()
        responses = await asyncio.gather(second, third)
        if not cancel_first: responses.append(await first)
        assert all(r.status_code == 200 for r in responses)
    try:
        with patch.object(pool, 'ensure', side_effect=ensure), patch('mailcheck.web.gateway.httpx.AsyncClient', side_effect=worker_client):
            asyncio.run(scenario())
        assert calls == ['legacy']
    finally:
        release.set()


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_gateway_bounds_reads_without_timing_out_mutations(system, monkeypatch, method):
    from fastapi import HTTPException
    from mailcheck.web import gateway
    app, store, _ = system
    endpoint = next(r.endpoint for r in app.routes if getattr(r, 'path', None) == '/{path:path}')
    monkeypatch.setattr(gateway, 'READ_REQUEST_TIMEOUT', .1, raising=False)
    identity = store.identity(store.owner_token)
    async def receive(): return {'type':'http.request','body':b'','more_body':False}
    request = Request({'type':'http', 'method':method, 'scheme':'http', 'path':'/api/slow',
                       'query_string':b'', 'headers':[(b'cookie', f'offerpath_session={store.owner_token}'.encode())],
                       'state':{'identity':identity}}, receive)
    client_type = httpx.AsyncClient
    async def scenario():
        entered, release = asyncio.Event(), asyncio.Event()
        async def slow_worker(request):
            entered.set()
            await release.wait()
            return httpx.Response(200, json={'ok':True})
        def client(**kwargs):
            return client_type(transport=httpx.MockTransport(slow_worker), **kwargs)
        with patch('mailcheck.web.gateway.httpx.AsyncClient', side_effect=client):
            task = asyncio.create_task(endpoint('api/slow', request))
            try:
                if method == 'GET':
                    with pytest.raises(HTTPException) as error:
                        await asyncio.wait_for(task, timeout=.5)
                    assert error.value.status_code == 504
                    assert error.value.headers['Retry-After'] == '1'
                else:
                    await asyncio.wait_for(entered.wait(), timeout=.5)
                    await asyncio.sleep(.15)
                    assert not task.done()
                    release.set()
                    assert (await task).status_code == 200
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(scenario())
