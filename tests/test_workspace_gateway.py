from types import SimpleNamespace
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient
from mailcheck.control_store import ControlStore
from mailcheck.web.auth import AuthStore
from mailcheck.web.gateway import create_gateway

class Pool:
    def __init__(self):self.visited=[];self.suspended=[]
    def status(self):return {}
    def close(self):pass
    def enable(self,wid):pass
    def stop(self,wid):self.suspended.append(wid)
    def authenticate_worker(self,token):return 'legacy' if token=='internal-secret' else None
    def ensure(self,workspace):
        self.visited.append(workspace['id'])
        return SimpleNamespace(port=5000,token='secret-'+workspace['id'])

@pytest.fixture
def system(tmp_path):
    auth=AuthStore(lambda:tmp_path/'original-auth.json');auth.change_password('admin','owner-password-123')
    store=ControlStore(tmp_path/'control',auth)
    store.owner_token=store.login('owner','owner-password-123','fixture')
    pool=Pool()
    app=create_gateway(store=store,pool=pool,start_workers=False)
    return app,store,pool

def login(client,username='owner',password='owner-password-123'):
    response=client.post('/api/auth/login',json={'username':username,'password':password,'role':'admin'})
    assert response.status_code==200,response.text
    session=response.json()
    client.headers['x-offerpath-workspace']=session['workspace_id']
    return session


def test_owner_admin_provisioning_and_no_bidder_auth(system):
    app,store,pool=system
    with TestClient(app) as owner:
        assert owner.get('/api/bootstrap').status_code==401
        assert owner.post('/api/auth/login',json={'role':'bidder','password':'anything'}).status_code==401
        login(owner)
        assert owner.get('/api/auth/bidders').status_code==410
        assert owner.post('/api/auth/bidders/1/password',json={'password':'new'}).status_code==410
        assert owner.post('/api/admin/users',json={'username':'alice','workspace_name':'Alice workspace','password':'temporary-pass-123'}).status_code==200
        alice=TestClient(app)
        try:
            identity=login(alice,'alice','temporary-pass-123')
            assert identity['must_change_password']
            assert alice.get('/api/bootstrap').status_code==403
            changed=alice.post('/api/auth/password',json={'password':'alice-final-pass-123'})
            assert changed.status_code==200,changed.text
            assert alice.get('/api/admin/users').status_code==403
            assert alice.post('/api/admin/switch',json={'workspace_id':'legacy'}).status_code==403
            assert alice.post('/api/admin/users',json={'username':'other','workspace_name':'Other','password':'temporary-pass-123'}).status_code==403
            user=next(u for u in store.list_admins() if u['username']=='alice')
            assert owner.post('/api/admin/users/'+str(user['id']),json={'enabled':False}).status_code==200
            assert alice.get('/api/bootstrap').status_code==401
            assert pool.suspended==[identity['workspace_id']]

        finally:alice.close()


def test_workspace_header_and_proxy_are_session_scoped(system):
    app,store,pool=system
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    real_client=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'worker':request.headers['x-offerpath-worker'],'url':str(request.url)}))
    with TestClient(app) as client, patch('mailcheck.web.gateway.httpx.AsyncClient',side_effect=lambda **kw:real_client(transport=transport,**kw)):
        login(client)
        result=client.get('/api/messages/1',headers={'x-offerpath-worker':'attacker'})
        assert result.json()['worker']=='secret-legacy'
        switched=client.post('/api/admin/switch',json={'workspace_id':wid})
        assert switched.status_code==200
        assert client.get('/api/messages/1').status_code==409
        client.headers['x-offerpath-workspace']=wid
        assert client.get('/api/messages/1').json()['worker']=='secret-'+wid
        assert pool.visited==['legacy',wid]


def test_host_origin_old_cookies_and_internal_tokens_are_not_trusted(system):
    app,store,pool=system
    with TestClient(app) as client:
        client.cookies.set('mailcheck_session','legacy-token')
        assert client.get('/api/bootstrap').status_code==401
        assert client.get('/_internal/ping').status_code==403
        assert client.get('/_internal/ping',headers={'x-offerpath-worker':'internal-secret'}).status_code==200
        assert client.get('/api/auth/session',headers={'host':'evil.test'}).status_code==403
        assert client.post('/api/auth/login',json={'password':'owner-password-123'},headers={'origin':'https://evil.test'}).status_code==403


def test_worker_rejects_direct_requests_and_legacy_login(tmp_path):
    from mailcheck.web.app import create_app
    with TestClient(create_app(worker_secret='private-worker-token')) as client:
        assert client.get('/api/bootstrap').status_code==403
        assert client.post('/api/auth/login',json={'role':'admin','password':'admin'},headers={'x-offerpath-worker':'private-worker-token'}).status_code==403
        assert client.get('/_internal/ready',headers={'x-offerpath-worker':'private-worker-token'}).status_code==200


def test_model_requests_queue_until_the_active_lease_is_released(system):
    from concurrent.futures import ThreadPoolExecutor
    import time
    app,store,pool=system
    headers={'x-offerpath-worker':'internal-secret'}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        first=client.post('/_internal/model/acquire',headers=headers)
        assert first.status_code==200
        waiting=executor.submit(client.post,'/_internal/model/acquire',headers=headers)
        time.sleep(.05)
        assert not waiting.done()
        assert client.post('/_internal/model/release',headers=headers,json=first.json()).status_code==200
        second=waiting.result(timeout=2)
        assert second.status_code==200 and second.json()!=first.json()
        client.post('/_internal/model/release',headers=headers,json=second.json())


@pytest.mark.parametrize('revoke',['reset','suspend','logout'])
def test_held_password_change_cannot_outlive_session_revocation(system,revoke):
    import asyncio
    app,store,pool=system
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    token=store.login('alice','temporary-pass-123','setup')
    with TestClient(app) as owner:
        login(owner)
        async def scenario():
            entered=asyncio.Event();release=asyncio.Event()
            async def delayed():
                yield b'{"password":'
                entered.set();await release.wait()
                yield b'"attacker-chosen-pass-123"}'
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://testserver') as alice:
                task=asyncio.create_task(alice.post('/api/auth/password',headers={'content-type':'application/json','x-offerpath-workspace':wid,'cookie':'offerpath_session='+token},content=delayed()))
                await entered.wait()
                if revoke=='logout':store.logout(token)
                else:
                    body={'password':'owner-reset-pass-123'} if revoke=='reset' else {'enabled':False}
                    response=await asyncio.to_thread(owner.post,'/api/admin/users/'+str(user['id']),json=body)
                    assert response.status_code==200,response.text
                release.set()
                result=await task
                assert result.status_code in (401,403),result.text
                assert store.login('alice','attacker-chosen-pass-123','setup') is None
        asyncio.run(scenario())


def test_held_owner_creation_cannot_outlive_owner_logout(system):
    import asyncio
    app,store,pool=system
    with TestClient(app) as client:
        login(client)
        token=client.cookies.get('offerpath_session')
        async def scenario():
            entered=asyncio.Event();release=asyncio.Event()
            async def delayed():
                yield b'{"username":"late-admin",'
                entered.set();await release.wait()
                yield b'"workspace_name":"Late workspace","password":"temporary-pass-123"}'
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://testserver') as remote:
                task=asyncio.create_task(remote.post('/api/admin/users',headers={'content-type':'application/json','x-offerpath-workspace':'legacy','cookie':'offerpath_session='+token},content=delayed()))
                await entered.wait();store.logout(token);release.set()
                assert (await task).status_code in (401,403)
                assert len(store.list_admins())==1
        asyncio.run(scenario())


def test_held_business_write_cannot_outlive_admin_password_reset(system):
    import asyncio
    app,store,pool=system
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    temporary=store.login('alice','temporary-pass-123','setup')
    token=store.change_password(temporary,'alice-final-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    real_client=httpx.AsyncClient
    dispatched=[]
    transport=httpx.MockTransport(lambda request:(dispatched.append(request) or httpx.Response(200,json={'ok':True})))
    with TestClient(app) as owner:
        login(owner)
        async def scenario():
            entered=asyncio.Event();release=asyncio.Event()
            async def delayed():
                yield b'{"name":'
                entered.set();await release.wait()
                yield b'"Late bidder"}'
            async with real_client(transport=httpx.ASGITransport(app),base_url='http://testserver') as alice:
                with patch('mailcheck.web.gateway.httpx.AsyncClient',side_effect=lambda **kw:real_client(transport=transport,**kw)):
                    task=asyncio.create_task(alice.post('/api/payments/bidders',headers={'content-type':'application/json','x-offerpath-workspace':wid,'cookie':'offerpath_session='+token},content=delayed()))
                    await entered.wait()
                    response=await asyncio.to_thread(owner.post,'/api/admin/users/'+str(user['id']),json={'password':'reset-again-pass-123'})
                    assert response.status_code==200
                    release.set()
                    assert (await task).status_code in (401,403)
                    assert not dispatched
        asyncio.run(scenario())
