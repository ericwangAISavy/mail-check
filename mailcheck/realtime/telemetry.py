"""Bounded, best-effort operational hints, isolated from business Redis calls."""
from __future__ import annotations

import atexit
import queue
import threading
from collections import OrderedDict


class Recorder:
    def __init__(self, capacity=256):
        self._queue = queue.Queue(maxsize=capacity)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._clients = OrderedDict()

    def record(self, redis_url, prefix, kind, action, job_id):
        if self._stop.is_set():
            return
        try:
            self._queue.put_nowait((redis_url, prefix, kind, action, job_id))
        except queue.Full:
            return
        with self._lock:
            if self._thread is None:
                self._thread = threading.Thread(target=self._run, name='monitor-telemetry', daemon=True)
                self._thread.start()

    def _send(self, redis_url, prefix, kind, action, job_id):
        from redis import Redis
        from redis.backoff import NoBackoff
        from redis.retry import Retry
        if redis_url not in self._clients:
            self._clients[redis_url] = Redis.from_url(redis_url, decode_responses=True,
                socket_connect_timeout=0.1, socket_timeout=0.1, retry=Retry(NoBackoff(), 0))
        client = self._clients.pop(redis_url)
        self._clients[redis_url] = client
        while len(self._clients)>16:
            _, old = self._clients.popitem(last=False)
            old.close()
        client.xadd(prefix+'monitor', {'kind':kind, 'action':action, 'job_id':job_id},
                    maxlen=1000, approximate=False)

    def _run(self):
        try:
            while not self._stop.is_set():
                try:
                    item = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    self._send(*item)
                except Exception:
                    # No raw errors: they can contain URLs and credentials.
                    pass
                finally:
                    self._queue.task_done()
        finally:
            for client in self._clients.values():
                client.close()
            self._clients.clear()

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=0.5)


_recorder = Recorder()
record = _recorder.record
atexit.register(_recorder.close)
