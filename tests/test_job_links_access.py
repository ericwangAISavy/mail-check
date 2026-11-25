import sqlite3
from contextlib import ExitStack

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_control_store import store
from tests.test_workspace_gateway import system, login


def test_owner_grants_and_revokes_permission_without_revoking_admin_session(store):
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(user for user in store.list_admins() if user['username']=='alice')
    token=store.login('alice','temporary-pass-123','alice')
    assert store.identity(store.owner_token)['job_links_access'] is True
    assert store.identity(token)['job_links_access'] is False
    assert not user['job_links_access']
    with pytest.raises(PermissionError):
        store.update_admin(token,user['id'],job_links_access=True)
    store.update_admin(store.owner_token,user['id'],job_links_access=True)
    assert store.identity(token)['job_links_access'] is True
    store.update_admin(store.owner_token,user['id'],job_links_access=False)
    assert store.identity(token)['job_links_access'] is False
    with pytest.raises(ValueError):
        store.update_admin(store.owner_token,1,job_links_access=False)
    assert store.identity(store.owner_token)['job_links_access'] is True
    with store.connect() as conn:
        actions={row[0] for row in conn.execute('SELECT action FROM audit')}
    assert {'grant-job-links','revoke-job-links'}<=actions
    switched=store.switch(store.owner_token,wid)
    assert store.identity(switched)['job_links_access'] is True


def test_existing_control_registry_is_migrated_to_default_denial(tmp_path):
    from mailcheck.control_store import SCHEMA, ControlStore
    from mailcheck.web.auth import AuthStore, _record
    root=tmp_path/'control'
    root.mkdir()
    auth=AuthStore(lambda:tmp_path/'auth.json')
    auth.change_password('admin','original-owner-pass')
    record=_record('temporary-pass-123')
    with sqlite3.connect(root/'control.db') as conn:
        conn.executescript(SCHEMA)
        conn.execute("INSERT INTO workspaces VALUES('existing','Existing',NULL,1)")
        conn.execute('INSERT INTO users(id,username,workspace_id,salt,hash,version) VALUES(2,?,?,?,?,?)',
                     ('alice','existing',record['salt'],record['hash'],record['version']))
    original=auth.path().read_bytes()
    upgraded=ControlStore(root,auth)
    token=upgraded.login('alice','temporary-pass-123','test')
    assert upgraded.identity(token)['job_links_access'] is False
    owner=upgraded.login('owner','original-owner-pass','owner')
    assert upgraded.identity(owner)['job_links_access'] is True
    assert auth.path().read_bytes()==original


def test_gateway_denies_by_default_and_applies_owner_changes_to_existing_sessions(system,tmp_path,monkeypatch):
    from mailcheck.web.gateway import create_gateway
    _,store,pool=system
    monkeypatch.setattr('mailcheck.web.gateway.config.db_path',lambda:tmp_path/'unused.db')
    app=create_gateway(store=store,pool=pool,start_workers=False)
    store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(user for user in store.list_admins() if user['username']=='alice')
    with ExitStack() as stack:
        owner=stack.enter_context(TestClient(app))
        admin=TestClient(app)
        stack.callback(admin.close)
        login(owner)
        login(admin,'alice','temporary-pass-123')
        assert admin.post('/api/auth/password',json={'password':'alice-final-pass-123'}).status_code==200
        for path in ('/api/job-links','/api/job-links/','/job-links','/job-links/'):
            assert admin.get(path).status_code==403
        assert owner.get('/api/job-links').status_code==200
        assert admin.post(f"/api/admin/users/{user['id']}",json={'job_links_access':True}).status_code==403
        assert owner.post(f"/api/admin/users/{user['id']}",json={'job_links_access':True}).status_code==200
        assert admin.get('/api/auth/session').json()['job_links_access'] is True
        for path in ('/api/job-links','/api/job-links/'):
            assert admin.get(path).status_code==200
        assert owner.post(f"/api/admin/users/{user['id']}",json={'job_links_access':False}).status_code==200
        assert admin.get('/api/job-links').status_code==403
        assert admin.get('/api/auth/session').json()['role']=='admin'
        assert owner.get('/api/job-links').status_code==200
        assert owner.post('/api/admin/switch',json={'workspace_id':user['workspace_id']}).status_code==200
        owner.headers['x-offerpath-workspace']=user['workspace_id']
        assert owner.get('/api/auth/session').json()['job_links_access'] is True
        assert owner.get('/api/job-links').status_code==200
        assert owner.get('/job-links').status_code==200
    assert pool.visited==[]
    assert pool.suspended==[]


def test_gateway_managed_workspace_routes_cannot_bypass_library_permission():
    from mailcheck.web.sourcing_routes import install
    app=FastAPI()
    @app.middleware('http')
    async def worker_identity(request,call_next):
        request.state.role='admin'
        request.state.bidder_id=None
        return await call_next(request)
    install(app,lambda:'shell',False,gateway_managed=True)
    with TestClient(app) as client:
        assert client.get('/api/job-links').status_code==403
        assert client.get('/job-links').status_code==403


@pytest.mark.parametrize('change,status',[('revoke',403),('logout',401)])
def test_search_rechecks_access_before_returning_results(system,monkeypatch,change,status):
    from mailcheck.web.gateway import COOKIE
    app,store,_=system
    store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(user for user in store.list_admins() if user['username']=='alice')
    store.update_admin(store.owner_token,user['id'],job_links_access=True)
    with TestClient(app) as client:
        login(client,'alice','temporary-pass-123')
        assert client.post('/api/auth/password',json={'password':'alice-final-pass-123'}).status_code==200
        def search(*args,**kwargs):
            if change=='revoke':
                store.update_admin(store.owner_token,user['id'],job_links_access=False)
            else:
                store.logout(client.cookies.get(COOKIE))
            return dict(items=[dict(company='private-result-marker',role='Engineer',link='https://jobs.test/private')],next_cursor=None,incomplete=False)
        monkeypatch.setattr('mailcheck.job_links.search',search)
        response=client.get('/api/job-links')
        assert response.status_code==status
        assert 'private-result-marker' not in response.text


@pytest.mark.parametrize('shared',[False,True])
def test_managed_app_wiring_denies_worker_library_routes(tmp_path,monkeypatch,shared):
    from mailcheck.web.app import create_app
    monkeypatch.setattr('mailcheck.config.db_path',lambda:tmp_path/'unused.db')
    monkeypatch.setattr('mailcheck.config.config_path',lambda:tmp_path/'config.toml')
    monkeypatch.setattr('mailcheck.config.control_dir',lambda:tmp_path/'control')
    client=TestClient(create_app(worker_secret='test-worker-token',shared=shared))
    try:
        for path in ('/api/job-links','/job-links'):
            response=client.get(path,headers={'x-offerpath-worker':'test-worker-token'})
            assert response.status_code==403
            assert 'permission-checked gateway endpoint' in response.text
    finally:
        client.close()
