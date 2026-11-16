import asyncio
import os
from pathlib import Path
import sqlite3

import pytest
from mailcheck import config, workspaces
from mailcheck.maintenance import connect_database, lock_path


def context(tmp_path, wid='a' * 32):
    root = workspaces.provision(tmp_path / 'workspaces', wid)
    return workspaces.WorkspaceContext.from_record(
        {'id': wid, 'root': str(root)},
        (tmp_path / 'owner/config.toml', tmp_path / 'owner/mailcheck.db', tmp_path / 'owner/auth.json'),
        tmp_path / 'control')


def test_context_paths_namespace_reset_and_environment(tmp_path):
    before = dict(os.environ)
    a, b = context(tmp_path), context(tmp_path, 'b' * 32)
    for ctx in (a, b):
        with workspaces.bind_workspace(ctx):
            assert config.config_path() == ctx.root / 'config/config.toml'
            assert config.db_path() == ctx.root / 'data/mailcheck.db'
            assert config.control_dir() == tmp_path / 'control'
            assert workspaces.credential_namespace() == f'workspace:{ctx.workspace_id}:'
            assert lock_path() == lock_path(ctx.legacy_config)
            with pytest.raises(ValueError, match='owner'):
                config.save(config.Config())
    assert workspaces.current_workspace() is None
    assert dict(os.environ) == before


def test_context_async_threads_isolated(tmp_path):
    a, b = context(tmp_path), context(tmp_path, 'b' * 32)
    async def run(ctx):
        with workspaces.bind_workspace(ctx):
            await asyncio.sleep(0)
            assert await asyncio.to_thread(config.db_path) == ctx.root / 'data/mailcheck.db'
            results = []
            worker = workspaces.start_workspace_thread(target=lambda: results.append(config.db_path()))
            worker.join()
            assert results == [ctx.root / 'data/mailcheck.db']
    async def both():
        await asyncio.gather(run(a), run(b))
    asyncio.run(both())
    assert workspaces.current_workspace() is None


def test_legacy_and_invalid_environment(tmp_path, monkeypatch):
    ctx = workspaces.WorkspaceContext.from_record({'id': 'legacy', 'root': None},
        (tmp_path/'original.toml', tmp_path/'original.db', tmp_path/'auth'), tmp_path/'control')
    monkeypatch.setenv('OFFERPATH_WORKSPACE_ID', 'invalid')
    with pytest.raises(ValueError):
        config.db_path()
    with workspaces.bind_workspace(ctx):
        assert config.config_path() == tmp_path/'original.toml'
        assert config.db_path() == tmp_path/'original.db'
        assert workspaces.credential_namespace() == ''
    with pytest.raises(ValueError):
        config.config_path()


@pytest.mark.parametrize('finish', ['commit', 'context', 'sql', 'release'])
def test_commit_guard_rollback_and_control_exclusion(tmp_path, finish):
    ctx = context(tmp_path)
    checks = []
    def reject():
        with connect_database(tmp_path/'control/control.db') as control:
            control.execute('CREATE TABLE IF NOT EXISTS harmless(x)')
        checks.append(True)
        raise PermissionError('revoked')
    with workspaces.bind_workspace(ctx), workspaces.bind_commit_guard(reject):
        conn = connect_database(config.db_path())
        conn.execute('CREATE TABLE example(x)')
        if finish == 'release':
            conn.execute('SAVEPOINT change')
        conn.execute('INSERT INTO example VALUES(1)')
    with pytest.raises(PermissionError, match='revoked'):
        if finish == 'commit': conn.commit()
        elif finish == 'context':
            with conn: pass
        elif finish == 'sql': conn.execute('COMMIT')
        else: conn.execute('RELEASE change')
    assert len(checks) == 1
    assert conn.execute('SELECT count(*) FROM example').fetchone()[0] == 0
    conn.close()

@pytest.mark.parametrize('finish', ['cursor', 'script'])
def test_commit_guard_sql_bypasses(tmp_path, finish):
    ctx = context(tmp_path)
    def reject():
        raise PermissionError('revoked')
    with workspaces.bind_workspace(ctx), workspaces.bind_commit_guard(reject):
        conn = connect_database(config.db_path())
        conn.execute('CREATE TABLE example(x)')
        conn.execute('INSERT INTO example VALUES(1)')
        with pytest.raises(PermissionError):
            if finish == 'cursor': conn.cursor().execute('/* transaction */ END;')
            else: conn.executescript('SELECT 1;')
        assert conn.execute('SELECT count(*) FROM example').fetchone()[0] == 0
        conn.close()


def test_same_account_credential_key_is_workspace_scoped(tmp_path):
    from mailcheck.secrets import _key_for_account
    keys = []
    for ctx in (context(tmp_path), context(tmp_path, 'b' * 32)):
        with workspaces.bind_workspace(ctx):
            keys.append(_key_for_account('same@example.com'))
    assert keys[0] != keys[1]
    assert all(key.endswith('account:same@example.com') for key in keys)


def test_shared_settings_and_owner_save(tmp_path):
    from dataclasses import replace
    ctx = context(tmp_path)
    ctx.legacy_config.parent.mkdir()
    ctx.legacy_config.write_text('[watch]\ninterval_minutes=2\nother_interval_minutes=9\n')
    with workspaces.bind_workspace(ctx):
        assert config.load().watch.interval_minutes == 9
    with workspaces.bind_workspace(replace(ctx, shared_config=None)):
        cfg = config.Config()
        cfg.watch.interval_minutes = 4
        path = config.save(cfg)
        assert path == ctx.root/'config/config.toml'
        assert config.load().watch.interval_minutes == 4
    assert 'other_interval_minutes=9' in ctx.legacy_config.read_text()


def test_bound_context_revalidates_missing_root(tmp_path):
    ctx = context(tmp_path)
    (ctx.root/'workspace.id').unlink()
    with workspaces.bind_workspace(ctx), pytest.raises((ValueError, OSError)):
        config.db_path()


def test_custom_cursor_cannot_bypass_guard(tmp_path):
    ctx = context(tmp_path)
    class CustomCursor(sqlite3.Cursor):
        pass
    def reject():
        raise PermissionError('revoked')
    with workspaces.bind_workspace(ctx), workspaces.bind_commit_guard(reject):
        conn = connect_database(config.db_path())
        conn.execute('CREATE TABLE example(x)')
        conn.execute('INSERT INTO example VALUES(1)')
        cursor = conn.cursor(factory=CustomCursor)
        assert isinstance(cursor, CustomCursor)
        with pytest.raises(PermissionError):
            cursor.execute('COMMIT')
        assert conn.execute('SELECT count(*) FROM example').fetchone()[0] == 0
        conn.close()


@pytest.mark.parametrize('sql', ['COMMIT/*comment*/', 'END--comment\n', ';COMMIT',
                                  '; /* first */ ; -- second\n COMMIT;', '\ufeffCOMMIT'])
@pytest.mark.parametrize('use_cursor', [False, True])
def test_transaction_sql_comments_and_empty_statements_cannot_bypass_guard(tmp_path, sql, use_cursor):
    ctx = context(tmp_path)
    def reject():
        raise PermissionError('revoked')
    with workspaces.bind_workspace(ctx), workspaces.bind_commit_guard(reject):
        conn = connect_database(config.db_path())
        conn.execute('CREATE TABLE example(x)')
        conn.execute('INSERT INTO example VALUES(1)')
        executor = conn.cursor() if use_cursor else conn
        with pytest.raises(PermissionError, match='revoked'):
            executor.execute(sql)
        assert conn.execute('SELECT count(*) FROM example').fetchone()[0] == 0
        conn.close()


def test_execute_rejects_multiple_nonempty_statements(tmp_path):
    ctx = context(tmp_path)
    with workspaces.bind_workspace(ctx):
        conn = connect_database(config.db_path())
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute('SELECT 1; COMMIT')
        conn.close()
