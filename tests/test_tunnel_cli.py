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
