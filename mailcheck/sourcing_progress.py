"""Ephemeral, worker-local progress; never stored in the application database."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock
from time import monotonic

_callback = ContextVar('sourcing_progress', default=None)


def report(processed, total):
    callback = _callback.get()
    if callback:
        callback(processed, total)


class ProgressStore:
    def __init__(self):
        self._lock = RLock()
        self._items = {}

    def get(self, tab, operation):
        with self._lock:
            item = self._items.get((tab, operation))
            return dict(item[1]) if item else None

    @contextmanager
    def track(self, tab, operation):
        key = (tab, operation)
        with self._lock:
            now = monotonic()
            self._items = {k:v for k,v in self._items.items()
                           if now-v[0] < 600 or v[1]['stage'] not in ('complete','error')}
            if len(self._items) >= 256:
                completed = [k for k,v in self._items.items() if v[1]['stage'] in ('complete','error')]
                for old in completed[:max(1,len(self._items)-255)]:
                    self._items.pop(old, None)
            if len(self._items) >= 256 and key not in self._items:
                raise ValueError('Too many active sourcing operations. Try again shortly.')
            self._items[key] = (now, {'stage':'preparing','processed':0,'total':None})
        def update(processed,total):
            with self._lock:
                self._items[key] = (monotonic(), {'stage':'filtering','processed':processed,'total':total})
        token = _callback.set(update)
        try:
            yield
        except BaseException:
            with self._lock:
                self._items[key][1]['stage'] = 'error'
            raise
        else:
            with self._lock:
                self._items[key][1]['stage'] = 'complete'
        finally:
            _callback.reset(token)
