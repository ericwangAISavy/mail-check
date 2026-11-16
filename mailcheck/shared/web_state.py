"""Workspace-local compatibility state for the existing API handlers."""
from collections.abc import MutableMapping
import threading

from ..workspaces import current_workspace
from .state import JobState, OperationLock, runtime_root


class WorkspaceValue(MutableMapping):
    def __init__(self, default, factory, *, name=None):
        self.default, self.factory, self.name = default, factory, name
        self.values = {}
        self.lock = threading.Lock()

    def value(self):
        context = current_workspace()
        if context is None:
            return self.default
        if self.name == 'job':
            return JobState(runtime_root(context) / 'job.json')
        if self.name == 'live-inbox':
            from .live_inbox import SharedLiveInbox
            return SharedLiveInbox(runtime_root(context)/'live-inbox.json')
        if self.name == 'schedule':
            from .state import ScheduleState
            return ScheduleState(runtime_root(context)/'schedule.json')
        key = context
        with self.lock:
            if key not in self.values:
                # Match the application's bounded workspace capacity without
                # evicting an active device-code flow or a held lock.
                if len(self.values) >= 256:
                    raise RuntimeError('Workspace state capacity reached; restart during a drained maintenance window.')
                self.values[key] = (OperationLock(runtime_root(context) / 'job.lock')
                                    if self.name == 'job-lock' else self.factory())
            return self.values[key]

    def __getattr__(self, name):
        return getattr(self.value(), name)

    def __getitem__(self, key):
        return self.value()[key]

    def __setitem__(self, key, value):
        self.value()[key] = value

    def __delitem__(self, key):
        del self.value()[key]

    def __iter__(self):
        return iter(self.value())

    def __len__(self):
        return len(self.value())

    def update(self, *args, **kwargs):
        self.value().update(*args, **kwargs)

    def __enter__(self):
        return self.value().__enter__()

    def __exit__(self, *args):
        return self.value().__exit__(*args)
