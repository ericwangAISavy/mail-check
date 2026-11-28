"""Singleton locking must distinguish contention, I/O failure and stale files."""
import errno
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mailcheck import workspace_workers as workers


def test_windows_failed_start_does_not_grow_lock_file(tmp_path):
    path = tmp_path / 'gateway.lock'
    path.write_bytes(b' ')
    lock = workers.InstanceLock(path)
    api = SimpleNamespace(LK_NBLCK=1, locking=lambda *args: (_ for _ in ()).throw(PermissionError(errno.EACCES, 'locked')))
    with patch.object(workers, 'os', SimpleNamespace(name='nt', SEEK_END=workers.os.SEEK_END)), patch.dict(sys.modules, msvcrt=api):
        with pytest.raises(RuntimeError, match='already running'):
            lock.__enter__()
    assert path.read_bytes() == b' '
    assert lock.file is None


def test_windows_disk_error_is_not_reported_as_another_running_instance(tmp_path):
    path = tmp_path / 'gateway.lock'
    lock = workers.InstanceLock(path)
    api = SimpleNamespace(LK_NBLCK=1, locking=lambda *args: (_ for _ in ()).throw(OSError(errno.EIO, 'disk error')))
    with patch.object(workers, 'os', SimpleNamespace(name='nt', SEEK_END=workers.os.SEEK_END)), patch.dict(sys.modules, msvcrt=api):
        with pytest.raises(OSError) as failure:
            lock.__enter__()
    assert failure.value.errno == errno.EIO
    assert lock.file is None


def test_existing_unlocked_file_is_reusable_and_live_lock_is_exclusive(tmp_path):
    path = tmp_path / 'gateway.lock'
    path.write_bytes(b' ')
    with workers.InstanceLock(path):
        with pytest.raises(RuntimeError, match='already running'):
            with workers.InstanceLock(path):
                pytest.fail('A duplicate gateway acquired the same lock')
    with workers.InstanceLock(path):
        assert path.exists()
