"""Safe diagnostic categories and process-local progress evidence."""
import errno
import math
import re
import sqlite3
import threading
import time


def failure(exc):
    """Keep error identity and OS/SQLite codes, never exception messages or URLs."""
    code = getattr(exc, 'sqlite_errorcode', None)
    reason = ('sqlite_busy' if isinstance(code, int) and code & 255 in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
              else 'sqlite_error' if isinstance(exc, sqlite3.Error)
              else 'permission_denied' if isinstance(exc, PermissionError)
              else 'connection_refused' if isinstance(exc, ConnectionRefusedError)
              else 'timeout' if isinstance(exc, TimeoutError)
              else 'dns_error' if type(exc).__name__ == 'gaierror'
              else 'connection_error' if isinstance(exc, ConnectionError)
              else 'os_error' if isinstance(exc, OSError) else 'runtime_error')
    result = dict(reason=reason, error_type=type(exc).__name__[:80])
    for key in ('errno', 'winerror', 'sqlite_errorcode'):
        value = getattr(exc, key, None)
        if type(value) is int:
            result[key] = value
    if isinstance(exc, OSError) and exc.errno in (errno.EACCES, errno.EPERM):
        result['reason'] = 'permission_denied'
    result.update(safe_evidence(getattr(exc,'health_evidence',None)))
    return result


def safe_evidence(value):
    """Validate evidence read from worker-owned files before displaying it."""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key in ('reason','error_type','scope','probe_stage','first_failure_reason','first_failure_stage','job_id','workspace','kind','operation','source_location','worker','telemetry_status','telemetry_reason'):
        item = value.get(key)
        if isinstance(item, str) and re.fullmatch(r'[a-zA-Z0-9_.:/ -]{1,180}', item):
            result[key] = item
    for key in ('pid','attempt','attempts','account_id','failure_count','errno','winerror','sqlite_errorcode','http_status','shell_http_status','asset_http_status','checked_at','duration_ms',
                'operation_age_seconds','poll_age_seconds','telemetry_checked_at','telemetry_dropped_events','telemetry_publication_errors'):
        item = value.get(key)
        if type(item) in (int,float) and math.isfinite(item):
            result[key] = item
    return result


class WorkerProgress:
    def __init__(self, *, clock=time.monotonic, slow_seconds=900, poll_timeout=30):
        self.clock, self.slow_seconds, self.poll_timeout = clock, slow_seconds, poll_timeout
        self.lock = threading.Lock()
        self.last_poll = None
        self.operation = None
        self.error = None

    def poll(self):
        with self.lock:
            self.last_poll, self.error = self.clock(), None

    def start(self, fields):
        with self.lock:
            self.operation = dict(job_id=fields['id'], workspace=fields['workspace_id'],
                                  kind=fields['kind'], attempt=fields['attempt']+1, began=self.clock())

    def finish(self):
        with self.lock:
            self.operation = None

    def failed(self, exc):
        with self.lock:
            self.error = failure(exc)

    def snapshot(self):
        with self.lock:
            now = self.clock()
            result = dict(status='healthy', reason='consumer_polling', scope='consumer_progress')
            if self.last_poll is not None:
                result['poll_age_seconds'] = round(max(0, now-self.last_poll), 1)
            if self.operation:
                result.update({key:value for key,value in self.operation.items() if key != 'began'})
                result['operation_age_seconds'] = round(max(0, now-self.operation['began']), 1)
            if self.error:
                result.update(status='degraded', **self.error)
            elif self.last_poll is None:
                result.update(status='unknown', reason='consumer_starting')
            elif now-self.last_poll > self.poll_timeout:
                result.update(status='degraded', reason='consumer_stalled')
            elif self.operation and now-self.operation['began'] > self.slow_seconds:
                result.update(status='degraded', reason='operation_slow')
            return result
