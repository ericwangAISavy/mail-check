import json
import sqlite3
from contextlib import ExitStack
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from mailcheck import db
from mailcheck import interview_feedback as feedback
from tests.test_workspace_gateway import system,login


def test_fixed_choices_share_by_company_and_only_replace_the_authors_choices():
    conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;conn.executescript(feedback.SCHEMA)
    feedback.save(conn,'one','1','Acme, Inc.',['linkedin','in-person'])
    feedback.save(conn,'two','2','ACME LLC',['normal','fuck'])
    result=feedback.summary(conn,['Acme','Acme Research'],'one','1')
    assert result['Acme']['tags']==list(feedback.OPTIONS)
    assert result['Acme']['mine']==['in-person','linkedin']
    assert result['Acme Research']['tags']==[]
    assert 'workspace' not in json.dumps(result)
    feedback.save(conn,'one','1','Acme',[])
    assert feedback.summary(conn,['Acme'],'two','2')['Acme']['tags']==['fuck','normal']
    with pytest.raises(ValueError):feedback.save(conn,'one','1','Acme',['unapproved'])
    with pytest.raises(ValueError):feedback.save(conn,'one','1','Unknown company',['normal'])


def seed_event(path,company='Acme',event_id=1):
    conn=db.connect(path)
    conn.execute('INSERT INTO interview_events(id,company,extraction_rank,start_at,created_at,updated_at) VALUES(?,?,3,?,?,?)',
                 (event_id,company,'2026-11-24T12:00:00+00:00','2026','2026'))
    conn.commit();conn.close()


def test_gateway_shares_badges_without_sharing_events_or_allowing_cross_workspace_edits(system,tmp_path,monkeypatch):
    from mailcheck.web.gateway import create_gateway
    _,store,pool=system
    original=tmp_path/'original.db';seed_event(original)
    monkeypatch.setattr('mailcheck.web.gateway.config.db_path',lambda:original)
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    seed_event(Path(store.workspace(wid)['root'])/'data'/'mailcheck.db','ACME LLC')
    app=create_gateway(store=store,pool=pool,start_workers=False)
    with ExitStack() as stack:
        owner=stack.enter_context(TestClient(app));admin=TestClient(app);stack.callback(admin.close)
        assert owner.get('/api/interview-feedback',params={'companies':'["Acme"]'}).status_code==401
        login(owner);login(admin,'alice','temporary-pass-123')
        assert admin.post('/api/auth/password',json={'password':'alice-final-pass-123'}).status_code==200
        response=owner.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':['linkedin','fuck']})
        assert response.status_code==200,response.text
        response=admin.get('/api/interview-feedback',params={'companies':'["ACME LLC"]'})
        assert response.status_code==200,response.text
        entry=response.json()['companies']['ACME LLC']
        assert entry=={'tags':['linkedin','fuck'],'mine':[]}
        assert admin.post('/api/interview-feedback',json={'event_id':1,'company':'ACME LLC','tags':['normal']}).status_code==200
        assert owner.post('/api/interview-feedback',json={'event_id':1,'company':'Different Company','tags':['normal']}).status_code==409
        assert owner.post('/api/interview-feedback',json={'event_id':999,'company':'Acme','tags':['normal']}).status_code==404
        assert owner.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':['other']}).status_code==422
        assert owner.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':[]}).status_code==200
        assert owner.get('/api/interview-feedback',params={'companies':'["Acme"]'}).json()['companies']['Acme']=={'tags':['normal'],'mine':[]}
    assert pool.visited==[]


def test_managed_worker_cannot_bypass_gateway_feedback_auth():
    from fastapi import FastAPI
    from mailcheck.web.feedback_routes import install
    app=FastAPI()
    @app.middleware('http')
    async def admin(request,call_next):
        request.state.role='admin'
        return await call_next(request)
    install(app,gateway_managed=True)
    with TestClient(app) as client:
        assert client.get('/api/interview-feedback',params={'companies':'["Acme"]'}).status_code==403
        assert client.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':['normal']}).status_code==403


def test_standalone_store_permissions_validation_and_removed_events(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from mailcheck.web.feedback_routes import install
    original=tmp_path/'mailcheck.db';seed_event(original)
    monkeypatch.setattr('mailcheck.web.feedback_routes.config.db_path',lambda:original)
    role='admin'
    app=FastAPI()
    @app.middleware('http')
    async def identity(request,call_next):
        request.state.role=role
        return await call_next(request)
    install(app)
    with TestClient(app) as client:
        assert client.get('/api/interview-feedback',params={'companies':'["Acme"]'}).json()['companies']['Acme']['tags']==[]
        assert not (tmp_path/'interview-feedback.db').exists()
        assert client.get('/api/interview-feedback',params={'companies':json.dumps(['Acme']*41)}).status_code==422
        assert client.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':['in-person','linkedin']}).status_code==200
        assert client.get('/api/interview-feedback',params={'companies':'["Acme"]'}).json()['companies']['Acme']['mine']==['in-person','linkedin']
        response=client.get('/api/interview-feedback',params={'companies':json.dumps(['Acme','Unknown, Inc.','Meeting LLC','---'])})
        assert response.status_code==200
        assert response.json()['companies']['Acme']['tags']==['in-person','linkedin']
        assert response.json()['companies']['Unknown, Inc.']=={'tags':[],'mine':[]}
        role='bidder'
        assert client.get('/api/interview-feedback').status_code==403
        assert client.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':[]}).status_code==403
        role='admin'
        conn=db.connect(original)
        conn.execute("INSERT INTO interview_event_removals VALUES(1,'2026-11-25')");conn.commit();conn.close()
        assert client.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':['normal']}).status_code==404


def test_session_revoked_during_event_lookup_cannot_save(system,tmp_path,monkeypatch):
    from mailcheck.web.gateway import create_gateway
    from mailcheck.web import feedback_routes
    _,store,pool=system
    original=tmp_path/'original.db';seed_event(original)
    monkeypatch.setattr('mailcheck.web.gateway.config.db_path',lambda:original)
    lookup=feedback_routes.event_company
    app=create_gateway(store=store,pool=pool,start_workers=False)
    with TestClient(app) as client:
        login(client)
        def revoke(*args):
            result=lookup(*args)
            store.logout(client.cookies.get('offerpath_session'))
            return result
        monkeypatch.setattr(feedback_routes,'event_company',revoke)
        assert client.post('/api/interview-feedback',json={'event_id':1,'company':'Acme','tags':['normal']}).status_code==401
    with store.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM interview_company_feedback').fetchone()[0]==0
