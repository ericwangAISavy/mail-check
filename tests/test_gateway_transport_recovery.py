"""A dropped local worker socket must not strand a page or replay a write."""
import asyncio
from unittest.mock import patch

import httpx
import pytest
from mailcheck.web import gateway
from tests.test_workspace_gateway import system


@pytest.mark.parametrize('method,path',[('GET','/api/triage'),('HEAD','/api/triage')])
def test_safe_read_recovers_once_after_worker_disconnect(system,method,path):
    app,store,_=system
    client_type=httpx.AsyncClient
    seen=[]
    async def worker(request):
        seen.append(request)
        if len(seen)==1:raise httpx.RemoteProtocolError('Server disconnected without sending a response.',request=request)
        return httpx.Response(200,json={'ok':True})
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                response=await browser.request(method,path,headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
        assert response.status_code==200
        assert len(seen)==2
        assert all(request.headers['x-offerpath-worker']=='secret-legacy' for request in seen)
    asyncio.run(scenario())


def test_local_worker_connection_timeout_is_shorter_than_page_deadline(system):
    app,store,_=system
    client_type=httpx.AsyncClient
    timeouts=[]
    async def worker(request):
        timeouts.append(request.extensions['timeout'])
        return httpx.Response(200,json={'ok':True})
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                response=await browser.get('/api/triage',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
        assert response.status_code==200
        assert timeouts[0]['connect']<=2
        assert timeouts[0]['read']==660
    asyncio.run(scenario())


@pytest.mark.parametrize('method,path',[('POST','/api/check'),('DELETE','/api/accounts/1'),('PATCH','/api/anything')])
def test_failed_mutation_is_never_replayed(system,method,path):
    app,store,_=system
    client_type=httpx.AsyncClient
    seen=[]
    async def worker(request):
        seen.append(request)
        raise httpx.RemoteProtocolError('Connection ended after request',request=request)
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                response=await browser.request(method,path,headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'},json={})
        assert response.status_code==503
        assert len(seen)==1
    asyncio.run(scenario())


def test_retry_revalidates_a_session_revoked_after_the_first_attempt(system):
    app,store,_=system
    client_type=httpx.AsyncClient
    seen=[]
    async def worker(request):
        seen.append(request)
        store.logout(store.owner_token)
        raise httpx.RemoteProtocolError('Peer closed',request=request)
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                response=await browser.get('/api/triage',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
        assert response.status_code==401
        assert len(seen)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('failure',['disconnect','timeout','overload'])
def test_read_retry_is_bounded_and_does_not_amplify_slow_or_overloaded_workers(system,failure,caplog):
    app,store,_=system
    client_type=httpx.AsyncClient
    seen=[]
    async def worker(request):
        seen.append(request)
        if failure=='overload':return httpx.Response(503,json={'error':'Busy'})
        error=httpx.ReadTimeout if failure=='timeout' else httpx.RemoteProtocolError
        raise error('private worker diagnostic',request=request)
    def client(**kwargs):return client_type(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with client_type(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch.object(gateway.httpx,'AsyncClient',side_effect=client):
                response=await browser.get('/api/triage',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy','cf-ray':'abcdef123-ORD'})
        assert response.status_code==503
        assert len(seen)==(2 if failure=='disconnect' else 1)
        assert 'private worker diagnostic' not in response.text
        if failure!='overload':
            assert response.headers['retry-after']=='1'
            assert 'abcdef123-ORD' in caplog.text
            assert 'secret-legacy' not in caplog.text
    asyncio.run(scenario())


@pytest.mark.parametrize('method,expected_status,expected_calls',[('GET',200,2),('POST',503,1)])
def test_real_worker_socket_closure_recovers_reads_but_never_replays_writes(system,method,expected_status,expected_calls):
    from types import SimpleNamespace
    app,store,pool=system
    async def scenario():
        calls=[]
        async def worker(reader,writer):
            try:
                calls.append(await reader.readuntil(b'\r\n\r\n'))
                if len(calls)>1:
                    payload=b'{"ok":true}'
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(payload)).encode()+b'\r\nConnection: close\r\n\r\n'+payload)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server=await asyncio.start_server(worker,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        pool.ensure=lambda _:SimpleNamespace(port=port,token='secret-legacy')
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
                response=await browser.request(method,'/api/check',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
            assert response.status_code==expected_status
            assert len(calls)==expected_calls
            assert all(b'offerpath_session' not in request for request in calls)
        finally:
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())


def test_concurrent_page_loads_recover_from_independent_worker_socket_closures(system):
    import socket
    import uvicorn
    from collections import Counter
    from types import SimpleNamespace
    from mailcheck.web.admission import RequestAdmission
    from mailcheck.web.server import LocalOriginHealth
    app,store,pool=system
    async def scenario():
        counts=Counter()
        async def worker(reader,writer):
            try:
                headers=await reader.readuntil(b'\r\n\r\n')
                key=headers.split(b'\r\n',1)[0]
                counts[key]+=1
                if counts[key]>1:
                    payload=b'{"ok":true}'
                    writer.write(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: '+str(len(payload)).encode()+b'\r\nConnection: close\r\n\r\n'+payload)
                    await writer.drain()
            finally:
                writer.close()
                await writer.wait_closed()
        server=await asyncio.start_server(worker,'127.0.0.1',0)
        port=server.sockets[0].getsockname()[1]
        pool.ensure=lambda _:SimpleNamespace(port=port,token='secret-legacy')
        origin_socket=socket.socket()
        origin_socket.bind(('127.0.0.1',0));origin_socket.listen();origin_socket.setblocking(False)
        origin_port=origin_socket.getsockname()[1]
        origin=uvicorn.Server(uvicorn.Config(LocalOriginHealth(RequestAdmission(app)),lifespan='off',limit_concurrency=256,log_level='error'))
        serving=asyncio.create_task(origin.serve(sockets=[origin_socket]))
        async def wait_started():
            while not origin.started:
                if serving.done():await serving
                await asyncio.sleep(.001)
        try:
            await asyncio.wait_for(wait_started(),5)
            async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{origin_port}',trust_env=False,timeout=15) as browser:
                responses=await asyncio.wait_for(asyncio.gather(*(browser.get(f'/api/triage?page={i}',headers={
                    'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'}) for i in range(40))),15)
                assert (await browser.get('/_internal/origin-health')).status_code==204
            assert all(response.status_code==200 for response in responses)
            assert len(counts)==40
            assert all(count==2 for count in counts.values())
        finally:
            origin.should_exit=True
            await asyncio.wait_for(serving,5)
            server.close()
            await server.wait_closed()
    asyncio.run(scenario())
