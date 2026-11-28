"""Successful lower-privilege sign-ins must not replenish guessing budgets."""
import pytest

from mailcheck.bidder_access import BidderAccess
from mailcheck.control_store import ControlStore
from mailcheck.web.auth import AuthFileError, AuthStore


def test_missing_owner_auth_cannot_be_recreated_by_remote_requests(tmp_path):
    path = tmp_path / 'auth.json'
    auth = AuthStore(lambda: path)
    with pytest.raises(AuthFileError):
        auth.identity('invalid-cookie')
    with pytest.raises(AuthFileError):
        auth.login('admin', 'admin', 'attacker')
    assert not path.exists()
    store = ControlStore(tmp_path / 'control', auth)
    with pytest.raises(AuthFileError):
        store.login('owner', 'admin', 'attacker')
    assert not path.exists()
    auth.change_password('admin', 'explicit-owner-password')
    assert auth.login('admin', 'explicit-owner-password', 'setup')[0]


@pytest.mark.parametrize('successful_role', ['admin', 'bidder'])
def test_managed_success_does_not_reset_failed_attempt_budget(tmp_path, successful_role):
    auth = AuthStore(lambda: tmp_path / 'auth.json')
    auth.change_password('admin', 'original-owner-password')
    store = ControlStore(tmp_path / 'control', auth)
    owner = store.login('owner', 'original-owner-password', 'setup')
    wid = store.create_admin(owner, 'alice', 'Alice', 'temporary-password-123')
    admin = store.login('alice', 'temporary-password-123', 'setup-admin')
    admin = store.change_password(admin, 'final-admin-password')
    bidders = BidderAccess(store)
    bidders.configure(admin, wid, 1, 'viewer', password='viewer-password-123')
    for _ in range(8):
        assert store.login('alice', 'wrong-password', 'attacker') is None
    if successful_role == 'bidder':
        assert bidders.login('viewer', 'viewer-password-123', 'attacker')
    else:
        assert store.login('alice', 'final-admin-password', 'attacker')
    assert store.login('alice', 'wrong-password', 'attacker') is None
    assert store.login('alice', 'wrong-password', 'attacker') is None
    with pytest.raises(ValueError, match='Too many'):
        store.login('alice', 'wrong-password', 'attacker')


def test_legacy_bidder_success_does_not_reset_owner_guess_budget(tmp_path):
    auth = AuthStore(lambda: tmp_path / 'auth.json')
    auth.change_password('admin', 'owner-password-123')
    auth.set_bidder_password(1, 'viewer-password-123')
    for _ in range(8):
        assert auth.login('admin', 'wrong-password', 'attacker') == (None, False)
    assert auth.login('bidder', 'viewer-password-123', 'attacker', 1)[0]
    assert auth.login('admin', 'wrong-password', 'attacker') == (None, False)
    assert auth.login('admin', 'wrong-password', 'attacker') == (None, False)
    assert auth.login('admin', 'wrong-password', 'attacker') == (None, True)
