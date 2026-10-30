from pathlib import Path
import json
import sqlite3
import zipfile
import pytest
from mailcheck.backups import BackupLayout, create_archive, inspect_archive, BackupError
from mailcheck.backup_restore import restore_archive


def database(path, marker):
    path.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute('CREATE TABLE marker(value TEXT)')
        conn.execute('INSERT INTO marker VALUES(?)',(marker,))


@pytest.fixture
def installation(tmp_path,monkeypatch):
    root=tmp_path/'source'
    config=root/'config'/'config.toml';config.parent.mkdir(parents=True)
    config.write_text('privacy_ack = true\n')
    (config.parent/'web-auth.json').write_text(json.dumps({'secret':'a'*64,'users':{'admin':{'salt':'b'*32,'hash':'c'*64,'version':'one'}},'bidders':{}}))
    layout=BackupLayout(config,root/'data'/'mailcheck.db',config.parent/'offerpath-control')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'source.lock'))
    database(layout.database,'owner-done-and-paid')
    layout.control.mkdir()
    wid='a'*32
    workspace=layout.control/'workspaces'/wid
    (workspace/'config').mkdir(parents=True);(workspace/'data').mkdir()
    (workspace/'workspace.id').write_text(wid)
    (workspace/'config'/'config.toml').write_text('privacy_ack = true\n')
    database(workspace/'data'/'mailcheck.db','alice-checked')
    with sqlite3.connect(layout.control/'control.db') as conn:
        conn.executescript('CREATE TABLE workspaces(id TEXT PRIMARY KEY,name TEXT,root TEXT,enabled INTEGER); CREATE TABLE sessions(token_hash TEXT); CREATE TABLE bidder_sessions(token_hash TEXT);')
        conn.execute("INSERT INTO workspaces VALUES('legacy','Owner',NULL,1)")
        conn.execute('INSERT INTO workspaces VALUES(?,?,?,0)',(wid,'Alice',str(workspace)))
        conn.execute("INSERT INTO sessions VALUES('old-browser')")
    return layout


def test_portable_backup_round_trip_rebases_all_workspaces(installation,tmp_path,monkeypatch):
    archive=tmp_path/'move.zip'
    create_archive(installation,archive)
    manifest=inspect_archive(archive)
    assert manifest['format']==1
    assert manifest['workspaces'][0]['id']=='a'*32
    destination=BackupLayout(tmp_path/'new'/'config'/'config.toml',tmp_path/'new'/'data'/'mailcheck.db',tmp_path/'new'/'config'/'offerpath-control')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'new.lock'))
    restore_archive(archive,destination)
    with sqlite3.connect(destination.database) as conn:assert conn.execute('SELECT value FROM marker').fetchone()[0]=='owner-done-and-paid'
    with sqlite3.connect(destination.control/'control.db') as conn:
        assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==0
        path=Path(conn.execute("SELECT root FROM workspaces WHERE id=?",('a'*32,)).fetchone()[0])
        assert path==destination.control/'workspaces'/('a'*32)
        assert conn.execute('SELECT enabled FROM workspaces WHERE id=?',('a'*32,)).fetchone()[0]==0
    with sqlite3.connect(path/'data'/'mailcheck.db') as conn:assert conn.execute('SELECT value FROM marker').fetchone()[0]=='alice-checked'
    assert (destination.config.parent/'credential-namespace').is_file()
    assert json.loads((destination.config.parent/'web-auth.json').read_text())['secret']!='a'*64
    with sqlite3.connect(installation.control/'control.db') as conn:assert conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]==1


def test_archive_tampering_is_rejected_before_destination_changes(installation,tmp_path):
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    with zipfile.ZipFile(archive,'a') as z:z.writestr('../escape','bad')
    with pytest.raises(BackupError):inspect_archive(archive)
    assert not (tmp_path/'escape').exists()


def test_replace_requires_explicit_flag_and_keeps_rollback(installation,tmp_path):
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    with pytest.raises(BackupError,match='replace'):restore_archive(archive,installation)
    result=restore_archive(archive,installation,replace=True)
    assert Path(result['rollback']).is_file()


def test_corrupt_sqlite_is_rejected(installation,tmp_path):
    installation.database.write_bytes(b'not sqlite')
    with pytest.raises(BackupError):create_archive(installation,tmp_path/'bad.zip')
    assert not (tmp_path/'bad.zip').exists()


def test_restore_refuses_active_writer_and_does_not_touch_data(installation,tmp_path):
    from mailcheck.maintenance import MaintenanceLock,MaintenanceBusyError
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    with MaintenanceLock(installation.lock):
        with pytest.raises(MaintenanceBusyError):restore_archive(archive,installation,replace=True)
    with sqlite3.connect(installation.database) as conn:assert conn.execute('SELECT value FROM marker').fetchone()[0]=='owner-done-and-paid'


def test_replace_failure_rolls_back_all_files_and_namespace(installation,tmp_path,monkeypatch):
    from mailcheck import backup_restore as restore
    from mailcheck.maintenance import journal_path
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    installation.config.write_text('privacy_ack = false\n')
    (installation.config.parent/'credential-namespace').write_text('b'*32)
    original=restore.os.replace
    failed=[False]
    def fail_once(source,target):
        if str(source).endswith('.new') and Path(target)==installation.database and not failed[0]:
            failed[0]=True;raise OSError('interrupted disk write')
        return original(source,target)
    monkeypatch.setattr(restore.os,'replace',fail_once)
    with pytest.raises(OSError):restore_archive(archive,installation,replace=True)
    assert installation.config.read_text()=='privacy_ack = false\n'
    assert (installation.config.parent/'credential-namespace').read_text()=='b'*32
    assert not journal_path(installation.lock).exists()
    assert list((installation.config.parent/'offerpath-restore-rollbacks').glob('*.zip'))


def test_unsafe_duplicate_and_invalid_manifest_archives_are_rejected(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('manifest.json','[]')
    with pytest.raises(BackupError):inspect_archive(archive)
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('manifest.json','{}');z.writestr('MANIFEST.JSON','{}')
    with pytest.raises(BackupError):inspect_archive(archive)


def test_destination_credentials_are_not_reused(installation,tmp_path,monkeypatch):
    from mailcheck import workspaces,config
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    destination=BackupLayout(tmp_path/'new/config/config.toml',tmp_path/'new/data/mailcheck.db',tmp_path/'new/config/offerpath-control')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'new.lock'))
    restore_archive(archive,destination)
    monkeypatch.setattr(config,'config_dir',lambda:destination.config.parent)
    monkeypatch.delenv('OFFERPATH_WORKSPACE_ID',raising=False);monkeypatch.delenv('OFFERPATH_WORKSPACE_ROOT',raising=False)
    assert workspaces.credential_namespace().startswith('restored:')


def test_interrupted_restore_blocks_startup_until_recovered(installation,tmp_path,monkeypatch):
    from mailcheck import backup_restore as restore
    from mailcheck.maintenance import MaintenanceLock,RecoveryRequiredError,journal_path
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    installation.config.write_text('privacy_ack = false\n')
    original_replace=restore.os.replace
    def interrupt(source,target):
        if str(source).endswith('.new') and Path(target)==installation.database:raise OSError('process interrupted')
        return original_replace(source,target)
    with monkeypatch.context() as changes:
        changes.setattr(restore.os,'replace',interrupt)
        changes.setattr(restore,'_recover_locked',lambda layout:(_ for _ in ()).throw(RuntimeError('power loss')))
        with pytest.raises(RuntimeError,match='power loss'):restore_archive(archive,installation,replace=True)
    assert journal_path(installation.lock).exists()
    with pytest.raises(RecoveryRequiredError):
        with MaintenanceLock(installation.lock):pass
    result=restore.recover_restore(installation)
    assert result['recovered']=='previous installation'
    assert installation.config.read_text()=='privacy_ack = false\n'
    assert not journal_path(installation.lock).exists()


def test_online_backup_includes_committed_wal_data(installation,tmp_path):
    conn=sqlite3.connect(installation.database)
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute("UPDATE marker SET value='committed-in-wal'");conn.commit()
        archive=tmp_path/'wal.zip';create_archive(installation,archive)
        with zipfile.ZipFile(archive) as z:(tmp_path/'snapshot.db').write_bytes(z.read('owner/mailcheck.db'))
        with sqlite3.connect(tmp_path/'snapshot.db') as snapshot:assert snapshot.execute('SELECT value FROM marker').fetchone()[0]=='committed-in-wal'
    finally:conn.close()


def test_automatic_rotation_only_removes_old_successful_archives(installation,tmp_path):
    from mailcheck.backup_manager import BackupManager
    import threading
    manager=BackupManager(installation,threading.RLock())
    manager.configure(True,1)
    first=manager.create(automatic=True)['name']
    manual=manager.create()['name']
    latest=manager.create(automatic=True)['name']
    assert not (manager.folder/first).exists()
    assert (manager.folder/manual).is_file()
    assert (manager.folder/latest).is_file()
    installation.database.write_bytes(b'corrupt')
    with pytest.raises(BackupError):manager.create(automatic=True)
    assert (manager.folder/latest).is_file()
    assert manager.status()['last_error']


def test_semantically_invalid_settings_are_rejected(installation,tmp_path):
    installation.config.write_text('[llm]\nbatch_size = -1\n')
    with pytest.raises(BackupError):create_archive(installation,tmp_path/'invalid-settings.zip')
    assert not (tmp_path/'invalid-settings.zip').exists()


def test_nested_workspace_directories_are_flushed_before_commit(installation,tmp_path,monkeypatch):
    from mailcheck import backup_restore as restore
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    destination=BackupLayout(tmp_path/'new/config/config.toml',tmp_path/'new/data/mailcheck.db',tmp_path/'new/config/offerpath-control')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'new.lock'))
    synced=[]
    original=restore._sync_directory
    def track(path):synced.append(str(path));return original(path)
    monkeypatch.setattr(restore,'_sync_directory',track)
    restore_archive(archive,destination)
    assert any('.new/' in path and path.endswith('/config') for path in synced)
    assert any('.new/' in path and path.endswith('/data') for path in synced)


def test_daily_schedule_runs_only_when_due_and_honors_disable(installation,monkeypatch):
    from datetime import datetime,timedelta,timezone
    from unittest.mock import Mock
    import threading
    from mailcheck import backup_manager
    now=datetime(2026,10,29,12,tzinfo=timezone.utc)
    monkeypatch.setattr(backup_manager,'utcnow',lambda:now)
    manager=backup_manager.BackupManager(installation,threading.RLock())
    assert manager.status()['next_due']==(now+timedelta(days=1)).isoformat()
    create=Mock();monkeypatch.setattr(manager,'create',create)
    manager.run_due();create.assert_not_called()
    monkeypatch.setattr(backup_manager,'utcnow',lambda:now+timedelta(days=1))
    manager.run_due();create.assert_called_once_with(automatic=True)
    manager.configure(False,7);create.reset_mock();manager.run_due();create.assert_not_called()


def test_cli_inspect_and_restore_to_new_paths(installation,tmp_path,monkeypatch):
    from typer.testing import CliRunner
    from mailcheck.cli import app
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    runner=CliRunner()
    result=runner.invoke(app,['backup','inspect',str(archive)])
    assert result.exit_code==0,result.output
    assert 'app_version' in result.output
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'cli.lock'))
    result=runner.invoke(app,['backup','restore',str(archive),'--config-path',str(tmp_path/'cli/config/config.toml'),'--db-path',str(tmp_path/'cli/data/mailcheck.db'),'--control-dir',str(tmp_path/'cli/config/offerpath-control')])
    assert result.exit_code==0,(result.output,result.exception)
    assert (tmp_path/'cli/data/mailcheck.db').is_file()


def test_real_admin_passwords_and_done_state_survive_migration(tmp_path,monkeypatch):
    from mailcheck import db
    from mailcheck.models import NormalizedMessage
    from mailcheck.control_store import ControlStore
    from mailcheck.web.auth import AuthStore
    source=BackupLayout(tmp_path/'source/config/config.toml',tmp_path/'source/data/mailcheck.db',tmp_path/'source/config/offerpath-control')
    source.config.parent.mkdir(parents=True);source.config.write_text('privacy_ack = true\n')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'source.lock'))
    auth=AuthStore(lambda:source.auth);auth.change_password('admin','owner-password-123')
    store=ControlStore(source.control,auth)
    token=store.login('owner','owner-password-123','test')
    store.create_admin(token,'alice','Alice workspace','temporary-password-123')
    conn=db.connect(source.database)
    try:
        account=db.add_account(conn,label='personal',email='personal@example.test')
        message=NormalizedMessage(account_id=account,account_label='personal',message_id='<done>',uid='1',folder='INBOX',from_addr='sender@example.test',from_name='Sender',subject='Saved',date_utc=None,body='Keep me')
        pk=db.upsert_message(conn,message);db.set_handled(conn,pk,True)
    finally:conn.close()
    archive=tmp_path/'move.zip';create_archive(source,archive)
    destination=BackupLayout(tmp_path/'new/config/config.toml',tmp_path/'new/data/mailcheck.db',tmp_path/'new/config/offerpath-control')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'new.lock'))
    restore_archive(archive,destination)
    restored=ControlStore(destination.control,AuthStore(lambda:destination.auth))
    assert restored.identity(token) is None
    assert restored.login('owner','owner-password-123','new-pc')
    assert restored.login('alice','temporary-password-123','new-pc')
    conn=db.connect(destination.database)
    try:
        row=db.get_message(conn,pk)
        assert row['handled_at'] is not None and row['message_id']=='<done>'
    finally:conn.close()


def test_download_tickets_expire_without_exposing_the_archive(installation,monkeypatch):
    import threading
    from mailcheck import backup_manager
    manager=backup_manager.BackupManager(installation,threading.RLock())
    name=manager.create()['name']
    monkeypatch.setattr(backup_manager.time,'monotonic',lambda:100)
    token=manager.issue_ticket(name,'owner-session','legacy')
    monkeypatch.setattr(backup_manager.time,'monotonic',lambda:161)
    with pytest.raises(BackupError,match='expired'):manager.consume_ticket(name,token,'owner-session','legacy')


@pytest.mark.skipif(__import__('os').name=='nt',reason='POSIX descriptor inspection verifies the Windows-compatible writable flush contract')
def test_backup_and_restore_flush_regular_files_through_writable_handles(installation,tmp_path,monkeypatch):
    import os,stat,fcntl
    original=os.fsync
    def checked(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            assert fcntl.fcntl(fd,fcntl.F_GETFL)&os.O_ACCMODE!=os.O_RDONLY
        return original(fd)
    monkeypatch.setattr(os,'fsync',checked)
    archive=tmp_path/'move.zip';create_archive(installation,archive)
    destination=BackupLayout(tmp_path/'new/config/config.toml',tmp_path/'new/data/mailcheck.db',tmp_path/'new/config/offerpath-control')
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK',str(tmp_path/'new.lock'))
    restore_archive(archive,destination)
