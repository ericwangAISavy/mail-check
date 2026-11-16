"""Same-host runtime coordination, deliberately outside application databases."""
from collections.abc import MutableMapping
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from ..workspace_workers import InstanceLock, InstanceAlreadyRunningError


class OperationLock:
    """Crash-released OS lock; never expire a live owner's write permission."""
    def __init__(self, path):
        self.path = Path(path)
        self._guard = None
        self._local = threading.Lock()

    def acquire(self, blocking=True, timeout=-1):
        deadline = None if timeout < 0 else time.monotonic() + timeout
        while True:
            if self._local.acquire(False):
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    guard = InstanceLock(self.path)
                    guard.__enter__()
                    self._guard = guard
                    return True
                except InstanceAlreadyRunningError:
                    self._local.release()
                except BaseException:
                    self._local.release()
                    raise
            if not blocking or (deadline is not None and time.monotonic() >= deadline):
                return False
            time.sleep(0.02)

    def release(self):
        guard, self._guard = self._guard, None
        if guard is None:
            raise RuntimeError('Operation lock is not owned')
        try:
            guard.__exit__(None, None, None)
        finally:
            self._local.release()

    def locked(self):
        return self._guard is not None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()

    def ensure_owned(self):
        if self._guard is None:
            raise RuntimeError('Operation lock ownership lost')


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.runtime-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class JobState(MutableMapping):
    DEFAULT = dict(running=False, message='', detail='', at=None, ok=True,
                   stage_started=None, completion_id=0)

    def __init__(self, path):
        self.path = Path(path)
        self.lock = OperationLock(self.path.with_suffix('.status.lock'))

    def snapshot(self):
        try:
            return {**self.DEFAULT, **json.loads(self.path.read_text())}
        except FileNotFoundError:
            return dict(self.DEFAULT)

    def update(self, *args, **kwargs):
        with self.lock:
            atomic_json(self.path, {**self.snapshot(), **dict(*args, **kwargs)})

    def __getitem__(self, key):
        return self.snapshot()[key]

    def __setitem__(self, key, value):
        self.update({key: value})

    def __delitem__(self, key):
        with self.lock:
            value = self.snapshot()
            del value[key]
            atomic_json(self.path, value)

    def __iter__(self):
        return iter(self.snapshot())

    def __len__(self):
        return len(self.snapshot())


class ScheduleState(JobState):
    DEFAULT = {'next_due':None}


def runtime_root(context):
    return context.control_root / 'shared-runtime' / context.workspace_id


@contextmanager
def account_lease(context, account_id, lane):
    lock = OperationLock(runtime_root(context) / f'{lane}-{int(account_id)}.lock')
    acquired = lock.acquire(False)
    try:
        yield lock if acquired else None
    finally:
        if acquired:
            lock.release()
