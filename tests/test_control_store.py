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
