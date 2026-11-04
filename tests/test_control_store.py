from pathlib import Path
import pytest
from mailcheck.control_store import ControlStore
from mailcheck.web.auth import AuthStore

@pytest.fixture
def store(tmp_path):
    auth=AuthStore(lambda:tmp_path/'original-auth.json')
    auth.change_password('admin','original-owner-pass')
    store=ControlStore(tmp_path/'control',auth)
    store.owner_token=store.login("owner","original-owner-pass","fixture")
    return store


def test_owner_keeps_original_password_and_new_admin_is_isolated(store):
    before=store.legacy_auth.path().read_bytes()
    owner=store.login('owner','original-owner-pass','local')
    identity=store.identity(owner)
    assert identity['is_owner'] and identity['workspace_id']=='legacy'
    wid=store.create_admin(store.owner_token,'alice','Alice workspace','temporary-pass-123')
    assert store.legacy_auth.path().read_bytes()==before
    token=store.login('alice','temporary-pass-123','local')
    alice=store.identity(token)
    assert alice['workspace_id']==wid and not alice['is_owner'] and alice['must_change_password']
    with pytest.raises(PermissionError):store.switch(token,'legacy')
    assert Path(store.workspace(wid)['root']).name==wid
    changed=store.change_password(token,'alice-final-pass-123')
    assert store.identity(token) is None
    assert not store.identity(changed)['must_change_password']


def test_reset_disable_and_owner_switch_revoke_sessions(store):
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    admin=next(u for u in store.list_admins() if u['username']=='alice')
    token=store.login('alice','temporary-pass-123','local')
    owner=store.login('owner','original-owner-pass','local')
    switched=store.switch(owner,wid)
    assert store.identity(owner) is None
    assert store.identity(switched)['workspace_id']==wid
    store.update_admin(store.owner_token,admin['id'],enabled=False)
    assert store.identity(token) is None and store.identity(switched) is None
    assert store.login('alice','temporary-pass-123','local') is None
    with pytest.raises(ValueError):store.update_admin(store.owner_token,1,enabled=False)
    store.update_admin(store.owner_token,admin['id'],enabled=True,password='new-temporary-pass')
    assert store.login('alice','temporary-pass-123','local') is None
    assert store.login('alice','new-temporary-pass','local')


def test_unknown_login_no_default_owner_and_workspace_capacity(store):
    assert store.login('admin','admin','local') is None
    assert store.login('nobody','temporary-pass-123','local') is None
    store.max_workspaces=1
    with pytest.raises(ValueError,match='capacity'):store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    assert len(store.list_admins())==1


def test_owner_password_change_invalidates_old_control_sessions(store):
    token=store.login('owner','original-owner-pass','local')
    store.legacy_auth.change_password('admin','updated-owner-pass')
    assert store.identity(token) is None


def test_failed_provisioning_does_not_register_or_activate_an_admin(store):
    from unittest.mock import patch
    with patch('mailcheck.control_store.provision',side_effect=OSError('disk unavailable')):
        with pytest.raises(OSError):store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    assert len(store.list_admins())==1
    assert len(store.enabled_workspaces())==1
    assert store.login('alice','temporary-pass-123','setup') is None


def test_remove_admin_revokes_access_preserves_data_and_allows_fresh_username(store):
    wid=store.create_admin(store.owner_token,'alice','Alice workspace','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    path=Path(store.workspace(wid)['root']);marker=path/'data'/'keep.txt';marker.write_text('private data')
    token=store.login('alice','temporary-pass-123','admin')
    owner=store.switch(store.login('owner','original-owner-pass','other-browser'),wid)
    assert store.remove_admin(store.owner_token,user['id'],'alice',expected_workspace='legacy')==wid
    assert marker.read_text()=='private data'
    assert store.identity(token) is None and store.identity(owner) is None
    assert store.login('alice','temporary-pass-123','admin') is None
    assert not any(u['id']==user['id'] for u in store.list_admins())
    with pytest.raises(ValueError):store.workspace(wid)
    with pytest.raises(ValueError):store.update_admin(store.owner_token,user['id'],enabled=True)
    replacement=store.create_admin(store.owner_token,'alice','New workspace','replacement-pass-123')
    assert replacement!=wid
    assert not (Path(store.workspace(replacement)['root'])/'data'/'keep.txt').exists()


def test_removal_rejects_owner_nonowner_stale_session_and_wrong_confirmation(store):
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    token=store.login('alice','temporary-pass-123','admin')
    for actor,who,username in [(store.owner_token,1,'owner'),(token,user['id'],'alice'),(None,user['id'],'alice'),(store.owner_token,user['id'],'wrong')]:
        with pytest.raises((ValueError,PermissionError)):store.remove_admin(actor,who,username)
    assert store.identity(token) is not None
    selected=store.switch(store.login('owner','original-owner-pass','other'),wid)
    with pytest.raises(ValueError,match='Switch'):store.remove_admin(selected,user['id'],'alice')


def test_removal_revokes_bidder_credentials_and_sessions(store):
    from mailcheck.bidder_access import BidderAccess
    access=BidderAccess(store)
    wid=store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    temporary=store.login('alice','temporary-pass-123','admin')
    token=store.change_password(temporary,'alice-final-pass-123')
    access.configure(token,wid,1,'Bidder',password='bidder-password-123')
    bidder=access.login('Bidder','bidder-password-123','bidder')
    assert access.identity(bidder)['workspace_id']==wid
    store.remove_admin(store.owner_token,user['id'],'alice')
    assert access.identity(bidder) is None
    assert access.login('Bidder','bidder-password-123','bidder') is None
    assert access.directory()==[]
    with store.connect() as conn:
        assert conn.execute('SELECT COUNT(*) FROM bidder_sessions').fetchone()[0]==0
        assert conn.execute('SELECT hash FROM bidder_logins WHERE workspace_id=?',(wid,)).fetchone()[0] is None


def test_existing_control_database_migrates_without_changing_access(store):
    with store.connect() as conn:conn.execute('ALTER TABLE users DROP COLUMN removed_at')
    reopened=ControlStore(store.root,store.legacy_auth)
    assert reopened.identity(store.owner_token)['is_owner']
    assert reopened.list_admins()==store.list_admins()


def test_suspended_admin_workspace_can_be_removed(store):
    store.create_admin(store.owner_token,'alice','Alice','temporary-pass-123')
    user=next(u for u in store.list_admins() if u['username']=='alice')
    store.update_admin(store.owner_token,user['id'],enabled=False)
    assert store.remove_admin(store.owner_token,user['id'],'alice')==user['workspace_id']
    assert [u['username'] for u in store.list_admins()]==['owner']
