"""Installation-wide shared writer locks and exclusive offline maintenance."""
from __future__ import annotations

from functools import lru_cache, wraps
import hashlib
import os
from pathlib import Path
import sqlite3


class MaintenanceError(RuntimeError):
    pass


class MaintenanceBusyError(MaintenanceError):
    pass


class RecoveryRequiredError(MaintenanceError):
    pass


def lock_path(config_file: Path | None = None) -> Path:
    override = os.environ.get('OFFERPATH_MAINTENANCE_LOCK')
    if override:
        return Path(override).expanduser().resolve()
    from .workspaces import current_workspace
    context = current_workspace()
    if context is not None:
        config_file = context.shared_config or context.legacy_config
    if config_file is None:
        from .config import config_path
        config_file = Path(os.environ.get('OFFERPATH_SHARED_CONFIG_PATH') or
                           os.environ.get('OFFERPATH_LEGACY_CONFIG_PATH') or config_path())
    config_file = Path(config_file).expanduser().resolve()
    digest = hashlib.sha256(os.fsencode(config_file)).hexdigest()[:24]
    return config_file.parent.parent / f'.offerpath-maintenance-{digest}.lock'


def journal_path(path: Path) -> Path:
    return Path(str(path) + '.restore-journal.json')


@lru_cache(maxsize=1)
def _windows_lock_api():
    import ctypes
    from ctypes import wintypes
    class OVERLAPPED(ctypes.Structure):
        _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                    ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD),
                    ('hEvent', wintypes.HANDLE)]
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    unlock = kernel.UnlockFileEx
    unlock.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                             wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    acquire = kernel.LockFileEx
    acquire.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
                        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(OVERLAPPED)]
    return OVERLAPPED, acquire, unlock


class MaintenanceLock:
    def __init__(self, path: Path, exclusive=False, allow_journal=False):
        self.path = Path(path)
        self.exclusive = exclusive
        self.allow_journal = allow_journal
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open('a+b')
        try:
            if os.name == 'nt':
                import ctypes
                import msvcrt
                overlapped, acquire, self._unlock = _windows_lock_api()
                self._overlapped = overlapped()
                self._handle = msvcrt.get_osfhandle(self.file.fileno())
                if not acquire(self._handle, 1 | (2 if self.exclusive else 0), 0, 1, 0,
                               ctypes.byref(self._overlapped)):
                    raise OSError(ctypes.get_last_error(), 'LockFileEx failed')
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), (fcntl.LOCK_EX if self.exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise MaintenanceBusyError('OfferPath maintenance access is unavailable. Stop the server, CLI writers, and workspace workers before restoring.') from exc
        if not self.allow_journal and journal_path(self.path).exists():
            self.__exit__(None, None, None)
            raise RecoveryRequiredError(f'Interrupted OfferPath restore detected: {journal_path(self.path)}. Run backup recovery before starting OfferPath.')
        return self

    def __exit__(self, exc_type, exc, tb):
        file,self.file=self.file,None
        if file is not None:
            try:
                if not file.closed:
                    if os.name=='nt':
                        import ctypes
                        self._unlock(self._handle,0,1,0,ctypes.byref(self._overlapped))
                    else:
                        import fcntl
                        fcntl.flock(file.fileno(),fcntl.LOCK_UN)
            finally:file.close()


def shared_writer(function):
    """Protect file initialization and mutations, including nested writer calls."""
    @wraps(function)
    def guarded(*args, **kwargs):
        with MaintenanceLock(lock_path()):
            return function(*args, **kwargs)
    return guarded


class MaintenanceCursor(sqlite3.Cursor):
    def execute(self, sql, parameters=()):
        self.connection._validate_statement(sql)
        return super().execute(sql, parameters)

    def executescript(self, sql_script):
        self.connection._validate_commit()
        return super().executescript(sql_script)


class MaintenanceConnection(sqlite3.Connection):
    _maintenance_lock = None
    _commit_check = None

    def _validate_commit(self):
        if self._commit_check is not None:
            try:
                self._commit_check()
            except BaseException:
                super().rollback()
                raise

    def commit(self):
        self._validate_commit()
        return super().commit()

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._validate_commit()
        return super().__exit__(exc_type, exc, tb)

    def _validate_statement(self, sql):
        import re
        # SQLite accepts empty statements, comments, and a BOM before the verb;
        # comments can also follow a verb without intervening whitespace.
        statement = re.sub(r'^(?:[\s;\ufeff]|--[^\n]*(?:\n|$)|/\*.*?\*/)*', '', sql, flags=re.S)
        if re.match(r'(?:COMMIT|END|RELEASE)\b', statement, flags=re.I):
            self._validate_commit()

    def execute(self, sql, parameters=()):
        self._validate_statement(sql)
        return super().execute(sql, parameters)

    def cursor(self, factory=MaintenanceCursor):
        if self._commit_check is not None and not (
                isinstance(factory, type) and issubclass(factory, MaintenanceCursor)):
            if not isinstance(factory, type) or not issubclass(factory, sqlite3.Cursor):
                raise ValueError('Guarded connections require a SQLite cursor class.')
            factory = type('GuardedCursor', (MaintenanceCursor, factory), {})
        return super().cursor(factory)

    def executescript(self, sql_script):
        # sqlite3 executescript implicitly commits any pending transaction.
        self._validate_commit()
        return super().executescript(sql_script)

    def close(self):
        super().close()
        lock,self._maintenance_lock=self._maintenance_lock,None
        if lock is not None:lock.__exit__(None,None,None)

    def __del__(self):
        try:
            self.close()
        except sqlite3.Error:
            # SQLite destroys the native connection after finalization, even
            # when collection occurs on a different thread.
            if self._maintenance_lock is not None:
                self._maintenance_lock.__exit__(None, None, None)
                self._maintenance_lock = None


def connect_database(path, **kwargs):
    lock = MaintenanceLock(lock_path())
    lock.__enter__()
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path, factory=MaintenanceConnection, **kwargs)
        conn._maintenance_lock = lock
        from .workspaces import current_commit_guard
        guard = current_commit_guard()
        if guard is not None:
            from .config import db_path
            if Path(path).resolve() == db_path().resolve():
                conn._commit_check = guard
        return conn
    except BaseException:
        lock.__exit__(None, None, None)
        raise
