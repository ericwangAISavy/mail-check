"""Two real isolated workers, using disposable business databases and no providers."""
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from mailcheck import db, config
from mailcheck.control_store import ControlStore
from mailcheck.web.auth import AuthStore
from mailcheck.web.gateway import create_gateway
from mailcheck.workspace_workers import WorkerPool


def test_real_workers_have_separate_business_data_and_preserve_original_backup(tmp_path):
    config_file=tmp_path/'original'/'config.toml';config_file.parent.mkdir()
    config_file.write_text('[watch]\nauto_check = false\n')
    database=tmp_path/'original'/'mailcheck.db'
    with db.connect(database) as conn:
        conn.execute("INSERT INTO bidders(name,created_at) VALUES('Original bidder','2026-10-27')")
    auth_file=tmp_path/'original'/'web-auth.json'
    auth=AuthStore(lambda:auth_file);auth.change_password('admin','owner-password-123')
    original_auth=auth_file.read_bytes();original_config=config_file.read_bytes()
    store=ControlStore(tmp_path/'control',auth)
    wid=store.create_admin(store.login('owner','owner-password-123','fixture'),'alice','Alice workspace','temporary-pass-123')
    initial=store.login('alice','temporary-pass-123','setup')
    store.change_password(initial,'alice-final-pass-123')
    pool=WorkerPool(store,'http://127.0.0.1:9',(config_file,database,auth_file))
    try:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as executor:
            workers=list(executor.map(pool.ensure,[store.workspace('legacy')]*2))
        assert workers[0] is workers[1] and workers[0].ready
        app=create_gateway(store=store,pool=pool,start_workers=False)
        with TestClient(app) as owner:
            response=owner.post('/api/auth/login',json={'username':'owner','password':'owner-password-123'})
            assert response.status_code==200,response.text
            owner.headers['x-offerpath-workspace']='legacy'
            before=owner.get('/api/payments')
            assert before.status_code==200,before.text
            assert before.json()['bidders'][0]['name']=='Original bidder'
            alice=TestClient(app)
            try:
                result=alice.post('/api/auth/login',json={'username':'alice','password':'alice-final-pass-123'})
                assert result.status_code==200,result.text
                alice.headers['x-offerpath-workspace']=wid
                empty=alice.get('/api/payments')
                assert empty.status_code==200,empty.text
                assert empty.json()['bidders']==[]
                added=alice.post('/api/payments/bidders',json={'name':'Alice bidder'})
                assert added.status_code==200,added.text
                assert owner.get('/api/payments').json()['bidders'][0]['name']=='Original bidder'
                assert alice.get('/api/payments').json()['bidders'][0]['name']=='Alice bidder'
                # A crashed worker does not lose its data or reuse its old secret.
                import time
                previous=pool.workers[wid]
                previous.process.kill();previous.process.wait(timeout=5)
                import pytest
                with pytest.raises(RuntimeError,match='recovery period'):
                    pool.ensure(store.workspace(wid))
                future=time.time()+31
                with patch('mailcheck.workspace_workers.time.time',return_value=future):
                    replacement=pool.ensure(store.workspace(wid))
                assert replacement is not previous and replacement.token!=previous.token
                assert pool.authenticate_worker(previous.token) is None
                assert alice.get('/api/payments').json()['bidders'][0]['name']=='Alice bidder'
                # Localhost is not trusted by itself.
                import httpx
                worker=pool.workers[wid]
                assert httpx.get(f'http://127.0.0.1:{worker.port}/api/payments',trust_env=False).status_code==403
            finally:alice.close()
        assert (store.root/'rollback-original'/'manifest.json').is_file()
        assert auth_file.read_bytes()==original_auth
        assert config_file.read_bytes()==original_config
    finally:pool.close()
