"""Bounded device sign-in threads owned and drained by one shared API app."""
from contextlib import contextmanager
from contextvars import copy_context
import threading

from ..workspaces import current_workspace, current_commit_guard


class SharedAuthFlows:
    def __init__(self, abort, capacity=64):
        self.abort = abort
        self.capacity = capacity
        self._lock = threading.RLock()
        self._starts = threading.Lock()
        self._entries = {}
        self._closing = False

    def start(self, pending, target):
        context = current_workspace()
        if context is None:
            raise RuntimeError('Shared sign-in requires a workspace.')
        key = context.workspace_id
        # Serialize replacement admission without holding the persistence lock
        # while an old thread exits.
        with self._starts:
            with self._lock:
                if self._closing:
                    raise RuntimeError('Sign-in is shutting down.')
                old = self._entries.get(key)
                if old:
                    old[2].set()
                    self.abort(old[0])
            if old:
                old[1].join()
            captured = copy_context()
            thread = threading.Thread(target=lambda: captured.run(target), daemon=True,
                                      name='offerpath-device-signin')
            with self._lock:
                if self._closing:
                    self.abort(pending)
                    raise RuntimeError('Sign-in is shutting down.')
                self._entries = {wid: entry for wid, entry in self._entries.items() if entry[1].is_alive()}
                if len(self._entries) >= self.capacity:
                    self.abort(pending)
                    raise RuntimeError('Too many pending sign-ins. Retry later.')
                self._entries[key] = pending, thread, threading.Event()
                thread.start()
            return thread

    @contextmanager
    def persistence(self, pending):
        with self._lock:
            context = current_workspace()
            entry = self._entries.get(context.workspace_id) if context else None
            if self._closing or entry is None or entry[0] is not pending or entry[2].is_set():
                raise RuntimeError('Sign-in was cancelled.')
            guard = current_commit_guard()
            if guard is not None:
                guard()
            yield

    def stop(self):
        with self._lock:
            self._closing = True
            entries = list(self._entries.values())
            self._entries.clear()
            for pending, _, cancelled in entries:
                cancelled.set()
                self.abort(pending)
        for _, thread, _ in entries:
            thread.join()
