import json
import sqlite3
from unittest.mock import patch
from fastapi.testclient import TestClient
from mailcheck import config
from mailcheck.control_store import ControlStore
from mailcheck.web.auth import AuthStore
from mailcheck.web.gateway import create_gateway
from tests.test_workspace_gateway import Pool, login


def test_backup_routes_require_owner_and_download_a_valid_archive(tmp_path,monkeypatch):
    root=tmp_path/'config';root.mkdir()
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'maintenance.lock'))
    monkeypatch.setattr(config,'config_dir',lambda:root)
    monkeypatch.setattr(config,'config_path',lambda:root/'config.toml')
    monkeypatch.setattr(config,'db_path',lambda:tmp_path/'data/mailcheck.db')
    (root/'config.toml').write_text('privacy_ack = true\n')
    auth=AuthStore(lambda:root/'web-auth.json');auth.change_password('admin','owner-password-123')
    store=ControlStore(root/'offerpath-control',auth)
    app=create_gateway(store=store,pool=Pool(),start_workers=False)
    with TestClient(app) as owner:
        assert owner.get('/api/admin/backups').status_code==401
        login(owner)
        status=owner.get('/api/admin/backups').json()
        assert status['enabled'] is True and status['retain']==7
        assert owner.post('/api/admin/backups/settings',json={'enabled':False,'retain':3}).status_code==200
        assert owner.post('/api/admin/backups/settings',json={'enabled':True,'retain':0}).status_code==422
        created=owner.post('/api/admin/backups/create',json={})
        assert created.status_code==200,created.text
        name=created.json()['name']
        response=owner.get('/api/admin/backups/download/'+name)
        assert response.status_code==200 and response.content.startswith(b'PK')
        assert response.headers['cache-control']=='no-store'
        assert owner.get('/api/admin/backups/download/missing.zip').status_code==404
        owner.post('/api/admin/users',json={'username':'alice','workspace_name':'Alice','password':'temporary-pass-123'})
        alice=TestClient(app)
        login(alice,'alice','temporary-pass-123')
        alice.post('/api/auth/password',json={'password':'alice-final-pass-123'})
        for path in ('/api/admin/backups','/api/admin/backups/download/'+name):assert alice.get(path).status_code==403
        assert alice.post('/api/admin/backups/create',json={}).status_code==403
        assert alice.post('/api/admin/backups/settings',json={'enabled':True,'retain':7}).status_code==403
        alice.close()


def test_native_download_tickets_are_single_use_and_bound_to_owner_session(tmp_path,monkeypatch):
    root=tmp_path/'config';root.mkdir()
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'maintenance.lock'))
    monkeypatch.setattr(config,'config_dir',lambda:root)
    monkeypatch.setattr(config,'config_path',lambda:root/'config.toml')
    monkeypatch.setattr(config,'db_path',lambda:tmp_path/'data/mailcheck.db')
    (root/'config.toml').write_text('privacy_ack = true\n')
    auth=AuthStore(lambda:root/'web-auth.json');auth.change_password('admin','owner-password-123')
    store=ControlStore(root/'offerpath-control',auth)
    app=create_gateway(store=store,pool=Pool(),start_workers=False)
    with TestClient(app) as owner:
        login(owner)
        name=owner.post('/api/admin/backups/create',json={}).json()['name']
        url=owner.post('/api/admin/backups/download-ticket/'+name,json={}).json()['url']
        other=TestClient(app);login(other)
        assert other.get(url).status_code==403
        other.close()
        owner.headers.pop('x-offerpath-workspace')
        response=owner.get(url)
        assert response.status_code==200 and response.content.startswith(b'PK')
        assert owner.get(url).status_code==403
        assert owner.get(url.replace('workspace=legacy','workspace=wrong')).status_code==409
