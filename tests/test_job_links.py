import json
import sqlite3

import pytest

from mailcheck.job_links import search
from tests.test_workspace_gateway import system, login


def seed(path, jobs):
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE native_rows(id TEXT PRIMARY KEY,tab_id INTEGER,work_date TEXT);
            CREATE TABLE native_columns(id TEXT PRIMARY KEY,tab_id INTEGER,kind TEXT);
            CREATE TABLE native_cells(row_id TEXT,column_id TEXT,value TEXT);
            INSERT INTO native_columns VALUES('company',1,'company'),('role',1,'role'),('link',1,'link');
            CREATE TABLE messages(body TEXT);
            INSERT INTO messages VALUES('private mail body');
        """)
        for index,(company,role,link,day) in enumerate(jobs):
            key = f'row-{index}'
            conn.execute('INSERT INTO native_rows VALUES(?,1,?)',(key,day))
            conn.executemany('INSERT INTO native_cells VALUES(?,?,?)',
                             [(key,'company',company),(key,'role',role),(key,'link',link)])


def test_search_combines_workspaces_and_paginates_without_exposing_sources(tmp_path):
    first,second=tmp_path/'first.db',tmp_path/'second.db'
    seed(first,[('Acme','Engineer','https://jobs.test/1','2026-11-23'),('Beta','Designer','https://jobs.test/2','2026-11-20')])
    seed(second,[('Straße','Senior Engineer','https://jobs.test/3','2026-11-24'),('Gamma','Engineer','https://jobs.test/4',None)])
    sources=[('private-owner-one',first),('private-owner-two',second)]
    result=search(sources,limit=2)
    following=search(sources,cursor=result['next_cursor'],limit=2)
    rows=result['items']+following['items']
    assert [row['company'] for row in rows]==['Straße','Acme','Beta','Gamma']
    assert len({row['id'] for row in rows})==4
    assert following['next_cursor'] is None
    assert all(set(row)=={'id','company','role','link'} for row in rows)
    assert 'private' not in json.dumps(result)
    assert search(sources,q='STRASSE engineer')['items'][0]['company']=='Straße'
    assert search(sources,q='private mail body')['items']==[]
    with pytest.raises(ValueError):
        search(sources,cursor='broken')


def test_busy_workspace_reports_incomplete_and_keeps_other_results(tmp_path):
    first,second=tmp_path/'locked.db',tmp_path/'available.db'
    seed(first,[('Locked','Engineer','https://jobs.test/1',None)])
    seed(second,[('Available','Engineer','https://jobs.test/2',None)])
    with sqlite3.connect(first) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        result=search([('one',first),('two',second)])
    assert result['incomplete']
    assert result['items'][0]['company']=='Available'
    assert result['next_cursor'] is None


def test_day_filter_is_applied_across_workspaces_before_pagination(tmp_path):
    first,second=tmp_path/'first.db',tmp_path/'second.db'
    seed(first,[('Acme','Engineer','https://jobs.test/1','2026-11-23'),('Other day','Engineer','https://jobs.test/2','2026-11-24')])
    seed(second,[('Beta','Engineer','https://jobs.test/3','2026-11-23'),('Undated','Engineer','https://jobs.test/4',None)])
    sources=[('first',first),('second',second)]
    page=search(sources,q='engineer',day='2026-11-23',limit=1)
    following=search(sources,q='engineer',day='2026-11-23',limit=1,cursor=page['next_cursor'])
    assert {row['company'] for row in page['items']+following['items']}=={'Acme','Beta'}
    assert following['next_cursor'] is None
    assert len(search(sources)['items'])==4
    for invalid in ('2026-02-30','20261123','invalid','2026-11-23x'):
        with pytest.raises(ValueError,match='date'):
            search(sources,day=invalid)


def test_admin_search_reads_all_registered_workspaces(system,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from mailcheck.web.gateway import create_gateway
    _,store,pool=system
    legacy=tmp_path/'legacy.db'
    seed(legacy,[('Original company','Engineer','https://jobs.test/original','2026-11-23')])
    wid=store.create_admin(store.owner_token,'alice','Private workspace','temporary-pass-123')
    with store.connect() as conn:
        root=conn.execute('SELECT root FROM workspaces WHERE id=?',(wid,)).fetchone()[0]
    from pathlib import Path
    seed(Path(root)/'data'/'mailcheck.db',[('Other company','Designer','https://jobs.test/other','2026-11-24')])
    monkeypatch.setattr('mailcheck.web.gateway.config.db_path',lambda:legacy)
    app=create_gateway(store=store,pool=pool,start_workers=False)
    with TestClient(app) as client:
        assert client.get('/api/job-links').status_code==401
        identity=login(client,'alice','temporary-pass-123')
        assert client.post('/api/auth/password',json={'password':'alice-final-password'}).status_code==200
        response=client.get('/api/job-links')
        assert response.status_code==200,response.text
        assert {row['company'] for row in response.json()['items']}=={'Original company','Other company'}
        assert 'Private workspace' not in response.text
        assert pool.visited==[]
        assert client.get('/api/job-links?q='+'x'*201).status_code==422
        assert [row['company'] for row in client.get('/api/job-links?day=2026-11-24').json()['items']]==['Other company']
        assert client.get('/api/job-links?day=2026-02-30').status_code==422


def test_bidder_cannot_access_cross_workspace_job_library(system,monkeypatch):
    from fastapi.testclient import TestClient
    app,store,_=system
    monkeypatch.setattr(store,'identity',lambda token:{'role':'bidder','workspace_id':'legacy','bidder_id':1,'must_change_password':False,'is_owner':False})
    with TestClient(app) as client:
        response=client.get('/api/job-links',headers={'x-offerpath-workspace':'legacy'})
        assert response.status_code==403
