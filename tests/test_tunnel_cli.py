from unittest.mock import patch
from typer.testing import CliRunner
import pytest
from mailcheck.cli import app
from mailcheck.web.auth import AuthStore


@pytest.fixture
def local_auth(tmp_path, monkeypatch):
    from mailcheck import config
    monkeypatch.setattr(config, 'config_dir', lambda: tmp_path)
    monkeypatch.setattr(config, 'config_path', lambda: tmp_path/'config.toml')
    monkeypatch.setattr(config, 'db_path', lambda: tmp_path/'mail.db')
    return AuthStore(lambda: tmp_path/'web-auth.json')


def test_fresh_web_start_requires_local_provisioning(local_auth):
    with patch('mailcheck.web.server.run') as serve:
        result = CliRunner().invoke(app, ['web','--no-open'])
    assert result.exit_code != 0
    assert not serve.called
    assert not local_auth.path().exists()
    assert 'web-password' in result.output


def test_default_owner_password_cannot_start_server(local_auth):
    local_auth.change_password('admin', 'admin')
    with patch('mailcheck.web.server.run') as serve:
        result = CliRunner().invoke(app, ['web','--no-open'])
    assert result.exit_code != 0
    assert not serve.called


def test_password_provisioning_uses_hidden_confirmed_local_prompt(local_auth):
    result = CliRunner().invoke(app, ['web-password'], input='strong-local-password\nstrong-local-password\n')
    assert result.exit_code == 0, result.output
    assert 'strong-local-password' not in result.output
    assert local_auth.login('admin', 'strong-local-password', 'local')[0]


def test_tunnel_start_keeps_loopback_and_secure_cookies(local_auth):
    local_auth.change_password('admin', 'strong-local-password')
    with patch('mailcheck.web.server.run') as serve:
        result = CliRunner().invoke(app, ['web','--no-open','--tunnel','--allow-host','app.example.test'])
    assert result.exit_code == 0, result.output
    assert serve.call_args.kwargs['host'] == '127.0.0.1'
    middleware = serve.call_args.args[0].user_middleware[0]
    assert middleware.kwargs['secure_cookies'] is True
    assert middleware.kwargs['public_hosts'] == {'app.example.test'}


@pytest.mark.parametrize('extra', [[], ['--host','0.0.0.0','--allow-host','app.example.test'],
                                  ['--allow-host','127.0.0.1'], ['--single-admin','--allow-host','app.example.test']])
def test_tunnel_rejects_unsafe_combinations(local_auth, extra):
    local_auth.change_password('admin', 'strong-local-password')
    with patch('mailcheck.web.server.run') as serve:
        result = CliRunner().invoke(app, ['web','--no-open','--tunnel',*extra])
    assert result.exit_code != 0
    assert not serve.called


def test_duplicate_gateway_is_reported_before_dashboard_or_browser_launch(local_auth):
    from mailcheck import config
    from mailcheck.workspace_workers import InstanceLock
    local_auth.change_password('admin', 'strong-local-password')
    with InstanceLock(config.control_dir()/'gateway.lock'), \
            patch('mailcheck.web.server.run') as serve, \
            patch('webbrowser.open') as browser, patch('threading.Timer') as timer:
        result = CliRunner().invoke(app, ['web'])
    assert result.exit_code == 1
    assert 'already running' in result.output
    assert 'Ctrl+C' in result.output
    assert 'Dashboard:' not in result.output
    assert not serve.called
    assert not browser.called
    assert not timer.called


def test_inaccessible_gateway_lock_is_not_reported_as_duplicate(local_auth):
    local_auth.change_password('admin', 'strong-local-password')
    with patch('mailcheck.workspace_workers.InstanceLock.__enter__', side_effect=PermissionError('denied')), \
            patch('mailcheck.web.server.run') as serve:
        result = CliRunner().invoke(app, ['web','--no-open'])
    assert result.exit_code == 1
    assert 'Cannot access the gateway lock' in result.output
    assert 'already running' not in result.output
    assert 'Dashboard:' not in result.output
    assert not serve.called
