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


def test_owner_admin_provisioning_and_opt_in_bidder_auth(system):
    app,store,pool=system
    with TestClient(app) as owner:
        assert owner.get('/api/bootstrap').status_code==401
        assert owner.post('/api/auth/login',json={'role':'bidder','password':'anything'}).status_code==401
        login(owner)
        assert owner.get('/api/auth/bidders').json()=={'bidders':[]}
        assert owner.post('/api/auth/bidders/1/password',json={'password':'new'}).status_code==422
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


def test_signing_into_another_admin_revokes_the_previous_browser_session(system):
    app,store,pool=system
    store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    with TestClient(app) as browser:
        login(browser)
        previous=browser.cookies.get('offerpath_session')
        login(browser,'alice','temporary-pass-123')
        assert store.identity(previous) is None
        assert store.identity(browser.cookies.get('offerpath_session'))['username']=='alice'


@pytest.mark.parametrize('path',['/settings','/api/settings','/api/settings/model','/api/settings/test','/api/rules','/api/autocheck'])
def test_added_admin_cannot_access_settings_or_setting_mutations(system,path):
    app,store,pool=system
    store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    temporary=store.login('alice','temporary-pass-123','setup');store.change_password(temporary,'alice-final-pass-123')
    with TestClient(app) as client:
        login(client,'alice','alice-final-pass-123')
        result=client.get(path) if path in ('/settings','/api/settings','/api/settings/model') else client.post(path,json={})
        assert result.status_code==403,result.text
        assert not pool.visited


def test_owner_settings_use_original_workspace_even_when_viewing_another_admin(system):
    app,store,pool=system
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    real_client=httpx.AsyncClient
    transport=httpx.MockTransport(lambda request:httpx.Response(200,json={'worker':request.headers['x-offerpath-worker']}))
    with TestClient(app) as client,patch('mailcheck.web.gateway.httpx.AsyncClient',side_effect=lambda **kw:real_client(transport=transport,**kw)):
        login(client)
        assert client.post('/api/admin/switch',json={'workspace_id':wid}).status_code==200
        client.headers['x-offerpath-workspace']=wid
        assert client.get('/api/settings').json()['worker']=='secret-legacy'
        assert pool.visited==['legacy']

@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_disconnected_request_is_not_forwarded_or_reported_as_server_error(system, method):
    import asyncio
    app, store, pool = system
    sent = []
    messages = iter([
        {'type': 'http.request', 'body': b'{', 'more_body': True},
        {'type': 'http.disconnect'},
    ])
    async def receive():
        try:
            return next(messages)
        except StopIteration:
            await asyncio.Event().wait()
    async def send(message):
        sent.append(message)
    scope = {'type': 'http', 'asgi': {'version': '3.0', 'spec_version': '2.4'},
        'http_version': '1.1', 'method': method, 'scheme': 'http',
        'path': '/api/messages/1', 'raw_path': b'/api/messages/1', 'query_string': b'',
        'root_path': '', 'server': ('testserver', 80), 'client': ('127.0.0.1', 12345),
        'headers': [(b'host', b'testserver'), (b'x-offerpath-workspace', b'legacy'),
                    (b'cookie', ('offerpath_session=' + store.owner_token).encode()),
                    (b'content-length', b'100')]}
    asyncio.run(app(scope, receive, send))
    assert pool.visited == []
    assert [message['status'] for message in sent if message['type'] == 'http.response.start'] == [499]


def test_worker_client_reuses_connections_without_retaining_cookies(system):
    app, store, pool = system
    wid = store.create_admin(store.owner_token, 'alice', 'Alice', 'temporary-pass-123')
    original_client = httpx.AsyncClient
    created = []
    observed = []
    def respond(request):
        observed.append((request.headers.get('cookie'), request.headers['x-offerpath-worker']))
        return httpx.Response(200, json={'ok':True}, headers={'set-cookie':'worker_secret=private; Path=/'})
    def factory(**kwargs):
        client = original_client(transport=httpx.MockTransport(respond), **kwargs)
        created.append(client)
        return client
    with TestClient(app) as client, patch('mailcheck.web.gateway.httpx.AsyncClient', side_effect=factory):
        login(client)
        assert client.get('/api/messages/1').status_code == 200
        assert client.get('/api/messages/2').status_code == 200
        assert client.post('/api/admin/switch', json={'workspace_id':wid}).status_code == 200
        client.headers['x-offerpath-workspace'] = wid
        assert client.get('/api/messages/3').status_code == 200
        assert observed == [(None,'secret-legacy'), (None,'secret-legacy'), (None,'secret-'+wid)]
        assert len(created) == 1
        assert len(created[0].cookies) == 0
    assert created[0].is_closed


def test_public_hashed_assets_are_cacheable_without_private_identity_queries(system):
    from mailcheck.web.gateway import HERE
    app, store, pool = system
    asset = next((HERE/'frontend_dist'/'assets').glob('index-*.js'))
    with TestClient(app) as client, patch.object(store, 'identity', wraps=store.identity) as identity:
        client.cookies.set('offerpath_session', store.owner_token)
        response = client.get('/assets/'+asset.name)
        assert response.status_code == 200
        assert response.headers['cache-control'] == 'public, max-age=31536000, immutable'
        assert identity.call_count == 0
        assert client.get('/').headers['cache-control'] == 'no-store'
        assert client.get('/api/auth/session').headers['cache-control'] == 'no-store'


def test_slow_workspace_lookup_does_not_run_on_gateway_event_loop(system):
    import asyncio
    import threading
    app, store, pool = system
    original_client = httpx.AsyncClient
    original_workspace = store.workspace
    lookup_threads = []
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={'ok':True}))
    def lookup(wid):
        lookup_threads.append(threading.get_ident())
        return original_workspace(wid)
    async def scenario():
        loop_thread = threading.get_ident()
        async with original_client(transport=httpx.ASGITransport(app), base_url='http://testserver') as client:
            with patch.object(store, 'workspace', side_effect=lookup), patch('mailcheck.web.gateway.httpx.AsyncClient', side_effect=lambda **kw: original_client(transport=transport, **kw)):
                response = await client.get('/api/bootstrap', headers={'cookie':'offerpath_session='+store.owner_token, 'x-offerpath-workspace':'legacy'})
                assert response.status_code == 200
        assert lookup_threads and all(thread != loop_thread for thread in lookup_threads)
    asyncio.run(scenario())


def test_suspend_and_reenable_keep_registry_and_runtime_consistent(system):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    app,store,pool=system
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    stop_entered=threading.Event();release_stop=threading.Event();enabled=threading.Event()
    stopped=set()
    def stop(workspace):
        stop_entered.set()
        if not release_stop.wait(5):raise RuntimeError('Test stop barrier timed out')
        stopped.add(workspace)
    def enable(workspace):
        stopped.discard(workspace);enabled.set()
    with TestClient(app) as owner,patch.object(pool,'stop',side_effect=stop),patch.object(pool,'enable',side_effect=enable),ThreadPoolExecutor(max_workers=2) as executor:
        login(owner)
        path='/api/admin/users/'+str(user['id'])
        disable=executor.submit(owner.post,path,json={'enabled':False})
        assert stop_entered.wait(5)
        reenable=executor.submit(owner.post,path,json={'enabled':True})
        try:
            enabled.wait(.5) # Before the fix, re-enable overtakes the paused stop.
        finally:release_stop.set()
        assert disable.result(timeout=5).status_code==200
        assert reenable.result(timeout=5).status_code==200
        assert store.workspace(wid)['enabled']==1
        assert wid not in stopped


def test_public_admin_selector_only_exposes_enabled_usernames(system):
    app,store,pool=system
    with TestClient(app) as client:
        assert client.get('/api/auth/admins').json()=={'admins':[{'username':'owner'}]}
        login(client)
        created=client.post('/api/admin/users',json={'username':'alice','workspace_name':'Private team','password':'temporary-pass-123'})
        assert created.status_code==200
        directory=client.get('/api/auth/admins').json()
        assert directory=={'admins':[{'username':'owner'},{'username':'alice'}]}
        user_id=next(u['id'] for u in store.list_admins() if u['username']=='alice')
        assert client.post(f'/api/admin/users/{user_id}',json={'enabled':False}).status_code==200
        client.post('/api/auth/logout')
        assert client.get('/api/auth/admins').json()=={'admins':[{'username':'owner'}]}
