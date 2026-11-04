"""Bidder usernames are private, normalized and unique across all workspaces."""
from pathlib import Path
import sqlite3
import pytest
from mailcheck.bidder_access import BidderAccess
from tests.test_control_store import store


def test_plain_username_authentication_without_admin_suffix(store):
    access=BidderAccess(store)
    access.configure(store.owner_token,'legacy',1,'Dany',password='bidder-password-123')
    token=access.login(' dAnY ','bidder-password-123','browser')
    assert access.identity(token)['bidder_name']=='Dany'
    assert access.login('Dany + owner','bidder-password-123','browser') is None


def test_registration_checks_all_bidders_not_only_enabled_logins(store,tmp_path):
    access=BidderAccess(store)
    legacy=tmp_path/'legacy.db'
    with sqlite3.connect(legacy) as conn:
        conn.execute('CREATE TABLE bidders(id INTEGER PRIMARY KEY,name TEXT,removed_at TEXT)')
        conn.execute("INSERT INTO bidders VALUES(1,'Existing',NULL)")
    with pytest.raises(ValueError,match='already in use'):
        access.check_username(' EXISTING ','other',None,legacy)
    access.check_username('Existing','legacy',1,legacy)
    access.check_username('Different','legacy',None,legacy)
    with sqlite3.connect(legacy) as conn:conn.execute("UPDATE bidders SET removed_at='removed'")
    access.check_username('Existing','other',None,legacy)


def test_configure_rejects_duplicate_username_without_resetting_other_credentials(store):
    access=BidderAccess(store)
    access.configure(store.owner_token,'legacy',1,'Dany',password='bidder-password-123')
    with pytest.raises(ValueError,match='already in use'):
        access.configure(store.owner_token,'legacy',2,'dany',password='another-password-123')
    assert access.identity(access.login('Dany','bidder-password-123','browser'))['bidder_id']==1


def test_legacy_duplicate_login_names_fail_closed(store):
    access=BidderAccess(store)
    access.configure(store.owner_token,'legacy',1,'Dany',password='bidder-password-123')
    with store.connect() as conn:
        conn.execute('''INSERT INTO bidder_logins(workspace_id,bidder_id,name,enabled,salt,hash,version,username_key)
          SELECT workspace_id,2,'dany',enabled,salt,hash,version,username_key FROM bidder_logins WHERE bidder_id=1''')
    assert access.login('Dany','bidder-password-123','browser') is None


def test_suspended_workspaces_still_reserve_existing_bidder_names(store,tmp_path):
    access=BidderAccess(store)
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    root=Path(store.workspace(wid)['root'])
    with sqlite3.connect(root/'data'/'mailcheck.db') as conn:
        conn.execute('CREATE TABLE bidders(id INTEGER PRIMARY KEY,name TEXT,removed_at TEXT)')
        conn.execute("INSERT INTO bidders VALUES(1,'Straße',NULL)")
    store.update_admin(store.owner_token,user['id'],enabled=False)
    with pytest.raises(ValueError,match='already in use'):
        access.check_username('STRASSE','legacy',None,tmp_path/'absent.db')
    store.remove_admin(store.owner_token,user['id'],'alice')
    access.check_username('STRASSE','legacy',None,tmp_path/'absent.db')


def test_concurrent_cross_workspace_registration_and_rename_are_checked_before_mutation(store,tmp_path):
    import asyncio,json
    import httpx
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from mailcheck.web.gateway import create_gateway
    from mailcheck import config
    from tests.test_workspace_gateway import Pool
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    token=store.change_password(store.login('alice','temporary-pass-123','setup'),'alice-final-pass-123')
    databases={'legacy':tmp_path/'legacy.db',wid:Path(store.workspace(wid)['root'])/'data'/'mailcheck.db'}
    for database in databases.values():
        with sqlite3.connect(database) as conn:conn.execute('CREATE TABLE bidders(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT,removed_at TEXT)')
    dispatched=[]
    async def worker(request):
        dispatched.append(request)
        await asyncio.sleep(.05)
        selected=request.headers['x-offerpath-worker'].removeprefix('secret-')
        with sqlite3.connect(databases[selected]) as conn:
            conn.execute('INSERT INTO bidders(name) VALUES(?)',(json.loads(request.content)['name'],))
        return httpx.Response(200,json={'ok':True})
    real=httpx.AsyncClient
    with patch.object(config,'db_path',return_value=databases['legacy']):
        app=create_gateway(store=store,pool=Pool(),start_workers=False)
    async def scenario():
        with patch('mailcheck.web.gateway.httpx.AsyncClient',side_effect=lambda **kw:real(transport=httpx.MockTransport(worker),**kw)):
            async with real(transport=httpx.ASGITransport(app),base_url='http://testserver') as browser:
                async def register(cookie,workspace,name):
                    return await browser.post('/api/payments/bidders',json={'name':name},headers={'cookie':'offerpath_session='+cookie,'x-offerpath-workspace':workspace})
                results=await asyncio.gather(register(store.owner_token,'legacy','Dany'),register(token,wid,'dany'))
                assert sorted(r.status_code for r in results)==[200,400]
                assert len(dispatched)==1
                # URL encoding must not bypass registration checks either.
                result=await browser.post('/api/payments/%2562idders',json={'name':'DANY'},headers={'cookie':'offerpath_session='+store.owner_token,'x-offerpath-workspace':'legacy'})
                assert result.status_code==400
                assert len(dispatched)==1
                # Rename must check the target name before calling a worker.
                result=await browser.post('/api/payments/bidders/999',json={'name':'Dany'},headers={'cookie':'offerpath_session='+token,'x-offerpath-workspace':wid})
                assert result.status_code==400
                assert len(dispatched)==1
    asyncio.run(scenario())


def test_removed_bidder_does_not_reserve_a_real_username(store):
    access=BidderAccess(store)
    access.configure(store.owner_token,'legacy',1,'Former',password='bidder-password-123')
    access.configure(store.owner_token,'legacy',1,'Removed bidder',enabled=False)
    access.configure(store.owner_token,'legacy',2,'Removed bidder',password='new-bidder-password-123')
    token=access.login('Removed bidder','new-bidder-password-123','browser')
    assert access.identity(token)['bidder_id']==2


def test_existing_credentials_migrate_to_plain_username(store):
    access=BidderAccess(store)
    access.configure(store.owner_token,'legacy',1,'Dany',password='bidder-password-123')
    with store.connect() as conn:
        conn.execute('DROP INDEX idx_bidder_login_username')
        conn.execute('ALTER TABLE bidder_logins DROP COLUMN username_key')
    migrated=BidderAccess(store)
    token=migrated.login('DANY','bidder-password-123','browser')
    assert migrated.identity(token)['bidder_id']==1
