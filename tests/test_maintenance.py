import sqlite3
import pytest
from mailcheck.maintenance import MaintenanceLock, MaintenanceBusyError, RecoveryRequiredError, journal_path, connect_database


def test_shared_and_exclusive(tmp_path):
    path = tmp_path / 'maintenance.lock'
    with MaintenanceLock(path):
        with MaintenanceLock(path):
            pass
        with pytest.raises(MaintenanceBusyError):
            with MaintenanceLock(path, exclusive=True):
                pass
    with MaintenanceLock(path, exclusive=True):
        with pytest.raises(MaintenanceBusyError):
            with MaintenanceLock(path):
                pass


def test_journal_blocks_startup(tmp_path):
    path = tmp_path / 'maintenance.lock'
    journal_path(path).write_text('{}')
    with pytest.raises(RecoveryRequiredError):
        with MaintenanceLock(path):
            pass
    with MaintenanceLock(path, exclusive=True, allow_journal=True):
        pass


def test_connection_holds_lock_until_close(tmp_path, monkeypatch):
    path = tmp_path / 'maintenance.lock'
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(path))
    conn = connect_database(tmp_path / 'test.db')
    with pytest.raises(MaintenanceBusyError):
        with MaintenanceLock(path, exclusive=True):
            pass
    conn.close()
    conn.close()
    with MaintenanceLock(path, exclusive=True):
        pass


def test_lock_path_external_and_override(tmp_path, monkeypatch):
    from mailcheck.maintenance import lock_path
    monkeypatch.delenv('OFFERPATH_MAINTENANCE_LOCK', raising=False)
    config = tmp_path / 'config' / 'config.toml'
    assert lock_path(config).parent == tmp_path
    assert lock_path(config) == lock_path(config)
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(tmp_path / 'explicit.lock'))
    assert lock_path(config) == tmp_path / 'explicit.lock'


def test_exclusive_blocks_all_writer_initialization(tmp_path, monkeypatch):
    from mailcheck import config, db
    from mailcheck.control_store import ControlStore
    from mailcheck.web.auth import AuthStore
    path = tmp_path / 'maintenance.lock'
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(path))
    monkeypatch.setattr(config, 'config_path', lambda: tmp_path / 'settings' / 'config.toml')
    auth = AuthStore(lambda: tmp_path / 'auth' / 'web-auth.json')
    with MaintenanceLock(path, exclusive=True):
        for writer in (lambda: db.connect(tmp_path / 'business' / 'data.db'),
                       lambda: config.save(config.Config()),
                       lambda: auth._load(),
                       lambda: ControlStore(tmp_path / 'control', auth)):
            with pytest.raises(MaintenanceBusyError):
                writer()
    assert not (tmp_path / 'settings').exists()
    assert not (tmp_path / 'auth').exists()
    assert not (tmp_path / 'business').exists()
    assert not (tmp_path / 'control').exists()


def test_subprocess_exclusive_refused(tmp_path):
    import subprocess
    import sys
    path = tmp_path / 'maintenance.lock'
    script = ('from pathlib import Path; from mailcheck.maintenance import MaintenanceLock; '
              f'MaintenanceLock(Path({str(path)!r}), exclusive=True).__enter__()')
    with MaintenanceLock(path):
        result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'MaintenanceBusyError' in result.stderr


def test_failed_cross_thread_close_keeps_lock(tmp_path, monkeypatch):
    import threading
    path = tmp_path / 'maintenance.lock'
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(path))
    conn = connect_database(tmp_path / 'test.db')
    errors = []
    def close_elsewhere():
        try:
            conn.close()
        except sqlite3.ProgrammingError as exc:
            errors.append(exc)
    worker = threading.Thread(target=close_elsewhere)
    worker.start()
    worker.join()
    assert errors
    with pytest.raises(MaintenanceBusyError):
        with MaintenanceLock(path, exclusive=True):
            pass
    conn.close()


def test_cleanup_is_safe_if_file_finalizer_already_closed_handle(tmp_path):
    lock=MaintenanceLock(tmp_path/'maintenance.lock')
    lock.__enter__()
    lock.file.close()
    lock.__exit__(None,None,None)
    lock.__exit__(None,None,None)
