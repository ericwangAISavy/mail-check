from pathlib import Path
from unittest.mock import patch
import pytest
from mailcheck import config, secrets


def test_legacy_paths_and_secret_namespace_remain_unchanged(tmp_path):
    with patch.dict('os.environ',{},clear=True):
        assert config.db_path().name == 'mailcheck.db'
        assert secrets._key_for_account('same') == 'account:same'


def test_explicit_workspace_paths_are_separate_and_fail_closed(tmp_path):
    wid='a'*32
    root=tmp_path/wid
    root.mkdir()
    (root/'workspace.id').write_text(wid)
    with patch.dict('os.environ',{'OFFERPATH_WORKSPACE_ROOT':str(root),'OFFERPATH_WORKSPACE_ID':wid}):
        assert config.config_path() == root/'config'/'config.toml'
        assert config.db_path() == root/'data'/'mailcheck.db'
        assert wid in secrets._key_for_account('same')
        from mailcheck import outlook_auth, google_oauth
        assert wid in outlook_auth._cache_key('same')
        with patch('mailcheck.google_oauth.keyring.get_password',return_value=None) as lookup:
            assert google_oauth.read_secret('tokens') is None
            assert wid in lookup.call_args.args[1]
    with patch.dict('os.environ',{'OFFERPATH_WORKSPACE_ROOT':str(tmp_path/'missing'),'OFFERPATH_WORKSPACE_ID':wid}):
        with pytest.raises(ValueError): config.db_path()


def test_online_backup_does_not_change_original_files(tmp_path):
    import sqlite3
    from mailcheck.workspaces import backup_legacy
    database=tmp_path/'original.db';config_file=tmp_path/'config.toml';auth_file=tmp_path/'web-auth.json'
    config_file.write_text('original config');auth_file.write_text('original credentials')
    with sqlite3.connect(database) as conn:
        conn.execute('CREATE TABLE sample(value TEXT)');conn.execute("INSERT INTO sample VALUES('kept')")
    before={p:p.read_bytes() for p in (database,config_file,auth_file)}
    folder=backup_legacy(tmp_path/'backup',config_file,database,auth_file)
    assert all(p.read_bytes()==contents for p,contents in before.items())
    with sqlite3.connect(folder/'mailcheck.db') as conn:assert conn.execute('SELECT value FROM sample').fetchone()[0]=='kept'


def test_invalid_workspace_cannot_fall_back_to_explicit_legacy_paths(tmp_path):
    env={'OFFERPATH_WORKSPACE_ID':'a'*32,'OFFERPATH_WORKSPACE_ROOT':'','OFFERPATH_LEGACY_DB_PATH':str(tmp_path/'original.db'),'OFFERPATH_LEGACY_CONFIG_PATH':str(tmp_path/'original.toml')}
    with patch.dict('os.environ',env):
        with pytest.raises(ValueError):config.db_path()
        with pytest.raises(ValueError):config.config_path()


def test_incomplete_backup_marker_blocks_original_worker_start(tmp_path):
    from types import SimpleNamespace
    from mailcheck.workspace_workers import WorkerPool
    control=tmp_path/'control';backup=control/'rollback-original';backup.mkdir(parents=True)
    (backup/'manifest.json').write_text('{')
    pool=WorkerPool(SimpleNamespace(root=control),'http://127.0.0.1:1',(tmp_path/'config.toml',tmp_path/'db.sqlite',tmp_path/'auth.json'))
    with pytest.raises(RuntimeError,match='backup'):
        pool._backup()
