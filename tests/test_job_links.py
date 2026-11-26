import json
import sqlite3

import pytest

from mailcheck.job_links import search
from tests.test_workspace_gateway import system, login


def seed(path, jobs):
    path.parent.mkdir(parents=True,exist_ok=True)
    # Replace the empty provisioned database with this test's minimal fixture.
    path.unlink(missing_ok=True)
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


def test_exclude_own_links_hides_workspace_and_shared_copies_before_pagination(tmp_path):
    mine,other=tmp_path/'mine.db',tmp_path/'other.db'
    seed(mine,[('Mine','Engineer','https://jobs.test/shared?utm_source=mine','2026-11-20')])
    seed(other,[('Copy','Engineer','https://jobs.test/shared?jr_id=copy','2026-11-24'),
                ('New one','Engineer','https://jobs.test/one','2026-11-23'),
                ('New two','Engineer','https://jobs.test/two','2026-11-22')])
    sources=[('mine',mine),('other',other)]
    page=search(sources,exclude_source='mine',limit=1)
    following=search(sources,exclude_source='mine',limit=1,cursor=page['next_cursor'])
    assert [r['company'] for r in page['items']+following['items']]==['New one','New two']
    assert following['next_cursor'] is None
    assert len(search(sources)['items'])==4


def test_one_page_filter_uses_provider_hosts_before_pagination(tmp_path):
    path=tmp_path/'jobs.db'
    seed(path,[('Greenhouse','Engineer','https://job-boards.greenhouse.io/acme/jobs/123456','2026-11-24'),
               ('Ashby','Engineer','https://jobs.ashbyhq.com/acme/efc949ef-22ce-401c-8161-091e387e776d','2026-11-24'),
               ('Other','Engineer','https://jobs.test/acme','2026-11-23'),
               ('Lookalike','Engineer','https://jobs.ashbyhq.com.example.test/acme','2026-11-22')])
    sources=[('other',path)]
    assert len(search(sources)['items'])==4
    first=search(sources,exclude_one_page=True,limit=1)
    second=search(sources,exclude_one_page=True,limit=1,cursor=first['next_cursor'])
    assert [r['company'] for r in first['items']+second['items']]==['Other','Lookalike']
    assert second['next_cursor'] is None


def test_only_one_page_links_filters_before_pagination_and_preserves_own_exclusion(tmp_path):
    mine,other=tmp_path/'mine.db',tmp_path/'other.db'
    seed(mine,[('Owned','Engineer','https://jobs.ashbyhq.com/acme/owned','2026-11-24')])
    seed(other,[('Not one-page','Engineer','https://jobs.test/regular','2026-11-25'),
                ('Copy','Engineer','https://jobs.ashbyhq.com/acme/owned','2026-11-24'),
                ('Greenhouse','Engineer','https://job-boards.greenhouse.io/acme/jobs/123','2026-11-23'),
                ('Ashby','Engineer','https://jobs.ashbyhq.com/acme/new','2026-11-22'),
                ('Lookalike','Engineer','https://jobs.ashbyhq.com.example.test/acme','2026-11-21')])
    sources=[('mine',mine),('other',other)]
    first=search(sources,only_one_page=True,exclude_source='mine',limit=1)
    second=search(sources,only_one_page=True,exclude_source='mine',limit=1,cursor=first['next_cursor'])
    assert [r['company'] for r in first['items']+second['items']]==['Greenhouse','Ashby']
    assert not second['next_cursor']
    assert not first['incomplete']
    assert search(sources,only_one_page=True,exclude_one_page=True,exclude_source='mine')['items']==search(sources,only_one_page=True,exclude_source='mine')['items']


def test_unreadable_own_workspace_does_not_leak_owned_links(tmp_path):
    mine,other=tmp_path/'mine.db',tmp_path/'other.db'
    seed(mine,[('Mine','Engineer','https://jobs.test/shared',None)])
    seed(other,[('Copy','Engineer','https://jobs.test/shared',None)])
    with sqlite3.connect(mine) as writer:
        writer.execute('BEGIN EXCLUSIVE')
        result=search([('mine',mine),('other',other)],exclude_source='mine')
    assert result['incomplete']
    assert result['items']==[]
    assert result['incomplete_reason']=='own_links_unavailable'


@pytest.mark.parametrize('own',[False,True])
def test_path_access_errors_are_reported_as_incomplete_instead_of_crashing(tmp_path,monkeypatch,own):
    from pathlib import Path
    blocked,healthy=tmp_path/'blocked.db',tmp_path/'healthy.db'
    seed(blocked,[('Blocked','Engineer','https://jobs.test/blocked',None)])
    seed(healthy,[('Healthy','Engineer','https://jobs.test/healthy',None)])
    real_is_file=Path.is_file
    def is_file(path):
        if path==blocked:
            raise PermissionError('Workspace path is temporarily inaccessible')
        return real_is_file(path)
    monkeypatch.setattr(Path,'is_file',is_file)
    result=search([('blocked',blocked),('healthy',healthy)],exclude_source='blocked' if own else None)
    assert result['incomplete']
    assert [r['company'] for r in result['items']]==([] if own else ['Healthy'])


def test_whitespace_padded_links_are_searchable_and_filters_still_apply(tmp_path):
    path=tmp_path/'jobs.db'
    seed(path,[('Pasted','Engineer','\t\r\nhttps://jobs.test/pasted\t\r\n','2026-11-24'),
               ('Ashby','Engineer','\thttps://jobs.ashbyhq.com/acme/position\n','2026-11-23')])
    all_rows=search([('workspace',path)])['items']
    assert len(all_rows)==2
    assert all_rows[0]['link']=='https://jobs.test/pasted'
    filtered=search([('workspace',path)],exclude_one_page=True)['items']
    assert [r['company'] for r in filtered]==['Pasted']


def test_owned_link_normalization_uses_request_budget_not_sql_read_budget(tmp_path,monkeypatch):
    from mailcheck import job_links
    path=tmp_path/'own.db'
    seed(path,[('Own','Engineer',f'https://jobs.test/{n}',None) for n in range(160)])
    clock=[0.0]
    monkeypatch.setattr(job_links.time,'monotonic',lambda:clock[0])
    def normalize(value):
        clock[0]+=.01
        return value
    monkeypatch.setattr(job_links,'link_key',normalize)
    owned=job_links._owned_links(path,deadline=5)
    assert owned is not None and len(owned)==160
    assert .5<clock[0]<5


def test_owned_link_normalization_still_respects_total_request_deadline(tmp_path,monkeypatch):
    from mailcheck import job_links
    path=tmp_path/'own.db'
    seed(path,[('Own','Engineer',f'https://jobs.test/{n}',None) for n in range(160)])
    clock=[0.0]
    monkeypatch.setattr(job_links.time,'monotonic',lambda:clock[0])
    def normalize(value):
        clock[0]+=.1
        return value
    monkeypatch.setattr(job_links,'link_key',normalize)
    assert job_links._owned_links(path,deadline=5) is None


@pytest.mark.parametrize('mode',['owned','one_page'])
def test_foreign_url_filter_cpu_does_not_exhaust_the_database_read_budget(tmp_path,monkeypatch,mode):
    from mailcheck import job_links
    mine,other=tmp_path/'mine.db',tmp_path/'other.db'
    seed(mine,[('Own','Engineer','https://jobs.test/mine',None)])
    seed(other,[('Other','Engineer',f'https://jobs.test/{n}','2026-11-24') for n in range(160)])
    clock=[0.0]
    monkeypatch.setattr(job_links.time,'monotonic',lambda:clock[0])
    def normalize(value):
        clock[0]+=.01
        return value
    monkeypatch.setattr(job_links,'link_key',normalize)
    def one_page(value):
        clock[0]+=.01
        return False
    if mode=='one_page':monkeypatch.setattr(job_links,'_one_page_link',one_page)
    sources=[('mine',mine),('other',other)] if mode=='owned' else [('other',other)]
    options={'exclude_source':'mine'} if mode=='owned' else {'exclude_one_page':True}
    result=search(sources,limit=100,**options)
    assert not result['incomplete']
    assert len(result['items'])==100
    assert result['next_cursor'] is not None
    following=search(sources,limit=100,cursor=result['next_cursor'],**options)
    assert not following['incomplete']
    assert len(following['items'])==60 and following['next_cursor'] is None
    assert len({r['id'] for r in result['items']+following['items']})==160


def test_short_foreign_query_still_reports_a_total_deadline_overrun(tmp_path,monkeypatch):
    from mailcheck import job_links
    mine,other=tmp_path/'mine.db',tmp_path/'other.db'
    seed(mine,[('Own','Engineer','https://jobs.test/mine',None)])
    seed(other,[('Other','Engineer','https://jobs.test/new',None)])
    clock=[0.0]
    monkeypatch.setattr(job_links.time,'monotonic',lambda:clock[0])
    def normalize(value):
        if value.endswith('/new'):clock[0]+=6
        return value
    monkeypatch.setattr(job_links,'link_key',normalize)
    result=search([('mine',mine),('other',other)],exclude_source='mine')
    assert result['incomplete']
    assert result['next_cursor'] is None


def test_larger_page_sizes_preserve_pagination_and_reject_oversized_requests(tmp_path):
    path=tmp_path/'jobs.db'
    seed(path,[(f'Company {index}','Engineer',f'https://jobs.test/{index}','2026-11-23') for index in range(501)])
    sources=[('workspace',path)]
    assert len(search(sources)['items'])==100
    page=search(sources,limit=500)
    assert len(page['items'])==500
    following=search(sources,limit=500,cursor=page['next_cursor'])
    assert len(following['items'])==1
    assert not {row['id'] for row in page['items']} & {row['id'] for row in following['items']}
    assert following['next_cursor'] is None
    for limit in (0,-1,501):
        with pytest.raises(ValueError,match='page size'):
            search(sources,limit=limit)


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
    user=next(user for user in store.list_admins() if user['username']=='alice')
    store.update_admin(store.owner_token,user['id'],job_links_access=True)
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
        assert {row['company'] for row in response.json()['items']}=={'Original company'}
        assert {row['company'] for row in client.get('/api/job-links?exclude_my_links=false').json()['items']}=={'Original company','Other company'}
        assert 'Private workspace' not in response.text
        assert pool.visited==[]
        assert client.get('/api/job-links?q='+'x'*201).status_code==422
        assert [row['company'] for row in client.get('/api/job-links?day=2026-11-24&exclude_my_links=false').json()['items']]==['Other company']
        assert client.get('/api/job-links?day=2026-02-30').status_code==422
        assert len(client.get('/api/job-links?start_date=2026-11-23&end_date=2026-11-24&exclude_my_links=false').json()['items'])==2
        assert [row['company'] for row in client.get('/api/job-links?start_date=2026-11-24&exclude_my_links=false').json()['items']]==['Other company']
        assert [row['company'] for row in client.get('/api/job-links?end_date=2026-11-23').json()['items']]==['Original company']
        assert client.get('/api/job-links?start_date=2026-11-24&end_date=2026-11-23').status_code==422
        assert client.get('/api/job-links?start_date=2026-02-30').status_code==422
        for limit in (0,99,501,'invalid'):
            assert client.get(f'/api/job-links?limit={limit}').status_code==422
        assert client.get('/api/job-links?limit=500').status_code==200


def test_bidder_cannot_access_cross_workspace_job_library(system,monkeypatch):
    from fastapi.testclient import TestClient
    app,store,_=system
    monkeypatch.setattr(store,'identity',lambda token:{'role':'bidder','workspace_id':'legacy','bidder_id':1,'must_change_password':False,'is_owner':False})
    with TestClient(app) as client:
        response=client.get('/api/job-links',headers={'x-offerpath-workspace':'legacy'})
        assert response.status_code==403


def test_gateway_honors_requested_page_size_with_real_saved_rows(system,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from mailcheck.web.gateway import create_gateway
    _,store,pool=system
    path=tmp_path/'many-jobs.db'
    seed(path,[(f'Company {index}','Engineer',f'https://jobs.test/{index}','2026-11-23') for index in range(501)])
    monkeypatch.setattr('mailcheck.web.gateway.config.db_path',lambda:path)
    app=create_gateway(store=store,pool=pool,start_workers=False)
    with TestClient(app) as client:
        login(client)
        for size in (100,200,500):
            result=client.get(f'/api/job-links?limit={size}&exclude_my_links=false').json()
            assert len(result['items'])==size
        remaining=client.get('/api/job-links',params={'limit':500,'cursor':result['next_cursor'],'exclude_my_links':'false'}).json()
        assert len(remaining['items'])==1
        assert remaining['next_cursor'] is None


def test_gateway_applies_only_one_page_links(system,tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from mailcheck.web.gateway import create_gateway
    _,store,pool=system
    path=tmp_path/'filtered.db'
    seed(path,[('Greenhouse','Engineer','https://job-boards.greenhouse.io/acme/jobs/123','2026-11-23'),
               ('Other','Engineer','https://jobs.test/123','2026-11-23')])
    monkeypatch.setattr('mailcheck.web.gateway.config.db_path',lambda:path)
    app=create_gateway(store=store,pool=pool,start_workers=False)
    with TestClient(app) as client:
        login(client)
        result=client.get('/api/job-links?exclude_my_links=false&only_one_page=true')
        assert result.status_code==200
        assert [row['company'] for row in result.json()['items']]==['Greenhouse']


def test_range_includes_both_endpoints_across_workspaces_before_pagination(tmp_path):
    first,second=tmp_path/'first.db',tmp_path/'second.db'
    seed(first,[('Start','Engineer','https://jobs.test/1','2026-11-20'),('Before','Engineer','https://jobs.test/2','2026-11-19')])
    seed(second,[('End','Engineer','https://jobs.test/3','2026-11-23'),('After','Engineer','https://jobs.test/4','2026-11-24'),('Undated','Engineer','https://jobs.test/5',None)])
    sources=[('first',first),('second',second)]
    page=search(sources,q='engineer',start_date='2026-11-20',end_date='2026-11-23',limit=1)
    following=search(sources,q='engineer',start_date='2026-11-20',end_date='2026-11-23',limit=1,cursor=page['next_cursor'])
    assert [row['company'] for row in page['items']+following['items']]==['End','Start']
    assert following['next_cursor'] is None
    assert len(search(sources,start_date='2026-11-20')['items'])==3
    assert len(search(sources,end_date='2026-11-23')['items'])==3
    for args in ({'start_date':'2026-02-30'},{'end_date':'invalid'},{'start_date':'2026-11-24','end_date':'2026-11-23'},{'day':'2026-11-20','start_date':'2026-11-20'}):
        with pytest.raises(ValueError,match='date'):
            search(sources,**args)
