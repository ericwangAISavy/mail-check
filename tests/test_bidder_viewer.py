"""Public bidder sessions are tenant-bound viewers, never worker admins."""
from contextlib import closing
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient
from tests.test_workspace_gateway import system, login

@pytest.fixture
def worker_mock():
    real=httpx.AsyncClient
    requests=[]
    def respond(req):
        requests.append(req)
        if req.url.path.startswith('/_internal/bidders/'):
            who=int(req.url.path.rsplit('/',1)[-1])
            return httpx.Response(200,json={'id':who,'name':'Dany'}) if who in (1,2) else httpx.Response(404,json={'error':'Not found'})
        if req.url.path == '/api/payments':
            return httpx.Response(200,json={'bidders':[{'id':1,'name':'Dany'},{'id':2,'name':'Joseph'}]})
        return httpx.Response(200,json={'worker':req.headers.get('x-offerpath-worker'),'viewer':req.headers.get('x-offerpath-viewer')})
    with patch('mailcheck.web.gateway.httpx.AsyncClient',side_effect=lambda **kw:real(transport=httpx.MockTransport(respond),**kw)):
        yield requests

def enable(client,bidder=1):
    result=client.post(f'/api/auth/bidders/{bidder}/password',json={'password':'bidder-password-123','enabled':True})
    assert result.status_code==200,result.text

def bidder_login(client,entry):
    response=client.post('/api/auth/login',json={'role':'bidder','bidder_id':entry['id'],'password':'bidder-password-123'})
    assert response.status_code==200,response.text
    client.headers['x-offerpath-workspace']=response.json()['workspace_id']
    return response.json()

def test_directory_login_read_only_and_tenant_isolation(system,worker_mock):
    app,store,pool=system
    with TestClient(app) as admin, closing(TestClient(app)) as bidder:
        assert bidder.get('/api/auth/bidders').json()=={'bidders':[]}
        login(admin);enable(admin)
        entry=bidder.get('/api/auth/bidders').json()['bidders'][0]
        assert entry['name']=='Dany + owner'
        assert set(entry)=={'id','name'}
        identity=bidder_login(bidder,entry)
        assert identity['role']=='bidder' and identity['workspace_id']=='legacy'
        for path in ['/dashboard','/payments','/api/dashboard','/api/dashboard/accounts','/api/payments','/api/payments/activity','/api/bootstrap','/api/messages/1']:
            assert bidder.get(path).status_code==200,path
        assert bidder.get('/api/dashboard').json()=={'worker':'secret-legacy','viewer':'bidder'}
        assert bidder.get('/api/dashboard',headers={'x-offerpath-workspace':'other'}).status_code==409
        for path in ['/api/accounts','/api/settings','/api/status','/api/sourcing','/api/interviews','/api/admin/users','/api/auth/bidders/manage','/sourcing','/settings']:
            assert bidder.get(path).status_code==403,path
        for path in ['/api/check','/api/payments/refresh','/api/payments/bidders/1/amount','/api/admin/switch','/api/auth/password','/api/auth/bidders/1/password']:
            assert bidder.post(path,json={}).status_code==403,path
        assert bidder.get('/api/payments/refresh').status_code==403
        assert bidder.get('/api/dashboard/../settings').status_code==403
        assert bidder.post('/api/auth/logout').status_code==200
        assert bidder.get('/api/dashboard').status_code==401

def test_same_bidder_id_in_different_workspaces_and_revocation(system,worker_mock):
    app,store,pool=system
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    token=store.login('alice','temporary-pass-123','setup')
    store.change_password(token,'alice-final-pass-123',expected_workspace=wid)
    with TestClient(app) as owner,closing(TestClient(app)) as alice,closing(TestClient(app)) as bidder:
        login(owner);enable(owner)
        login(alice,'alice','alice-final-pass-123');enable(alice)
        entries=bidder.get('/api/auth/bidders').json()['bidders']
        assert {e['name'] for e in entries}=={'Dany + owner','Dany + alice'}
        assert len({e['id'] for e in entries})==2
        entry=next(e for e in entries if e['name'].endswith('alice'))
        bidder_login(bidder,entry)
        assert bidder.get('/api/dashboard').json()['worker']=='secret-'+wid
        own=alice.get('/api/auth/bidders/manage').json()['bidders']
        assert [b['bidder_id'] for b in own]==[1]
        enable(owner) # resetting another workspace must not revoke Alice's bidder
        assert bidder.get('/api/dashboard').status_code==200
        enable(alice)
        assert bidder.get('/api/dashboard').status_code==401
        bidder_login(bidder,entry)
        assert alice.post('/api/auth/bidders/1/password',json={'enabled':False}).status_code==200
        assert bidder.get('/api/dashboard').status_code==401
        assert len(bidder.get('/api/auth/bidders').json()['bidders'])==1
        enable(alice);bidder_login(bidder,entry)
        user=next(u for u in store.list_admins() if u['username']=='alice')
        store.update_admin(store.owner_token,user['id'],enabled=False,expected_workspace='legacy')
        assert bidder.get('/api/dashboard').status_code==401
        assert len(bidder.get('/api/auth/bidders').json()['bidders'])==1

def test_bidder_removed_and_bad_password_and_unknown_id(system,worker_mock):
    app,store,pool=system
    with TestClient(app) as admin,closing(TestClient(app)) as bidder:
        login(admin)
        assert admin.post('/api/auth/bidders/999/password',json={'password':'bidder-password-123'}).status_code==404
        enable(admin)
        entry=bidder.get('/api/auth/bidders').json()['bidders'][0]
        assert bidder.post('/api/auth/login',json={'role':'bidder','bidder_id':entry['id'],'password':'wrong'}).status_code==401
        bidder_login(bidder,entry)
        assert admin.post('/api/payments/bidders/1/remove',json={}).status_code==200
        assert bidder.get('/api/dashboard').status_code==401
        assert bidder.get('/api/auth/bidders').json()=={'bidders':[]}

def test_bruteforce_is_throttled_and_admin_reset_revokes_viewers(system,worker_mock):
    app,store,pool=system
    with TestClient(app) as admin,closing(TestClient(app)) as bidder:
        login(admin);enable(admin)
        entry=bidder.get('/api/auth/bidders').json()['bidders'][0]
        for _ in range(10):
            assert bidder.post('/api/auth/login',json={'role':'bidder','bidder_id':entry['id'],'password':'wrong'}).status_code==401
        assert bidder.post('/api/auth/login',json={'role':'bidder','bidder_id':entry['id'],'password':'wrong'}).status_code==429
        store._attempts.clear()
        bidder_login(bidder,entry)
        assert admin.post('/api/auth/password',json={'password':'owner-updated-password'}).status_code==200
        assert bidder.get('/api/dashboard').status_code==401


def test_client_cannot_forge_viewer_or_internal_headers(system,worker_mock):
    app,store,pool=system
    with TestClient(app) as admin:
        login(admin)
        result=admin.get('/api/dashboard',headers={'x-offerpath-viewer':'bidder','x-offerpath-bidder':'999','x-offerpath-worker':'evil'})
        assert result.json()=={'worker':'secret-legacy','viewer':None}


def test_credential_changes_revalidate_after_worker_lookup(system,worker_mock):
    app,store,pool=system
    original=pool.ensure
    with TestClient(app) as admin:
        login(admin)
        def revoke(workspace):
            store.logout(admin.cookies.get('offerpath_session'))
            return original(workspace)
        with patch.object(pool,'ensure',side_effect=revoke):
            assert admin.post('/api/auth/bidders/1/password',json={'password':'bidder-password-123'}).status_code==401
        assert admin.get('/api/auth/bidders').json()=={'bidders':[]}


def test_successful_bidder_signins_do_not_exhaust_the_failure_budget(system,worker_mock):
    app,store,pool=system
    with TestClient(app) as admin,closing(TestClient(app)) as bidder:
        login(admin);enable(admin)
        entry=bidder.get('/api/auth/bidders').json()['bidders'][0]
        for _ in range(12):
            bidder_login(bidder,entry)
            assert bidder.post('/api/auth/logout').status_code==200
