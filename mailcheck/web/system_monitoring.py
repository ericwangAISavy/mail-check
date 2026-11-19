"""Owner-only, bounded operational snapshots. No mailbox content or raw errors."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path

from fastapi import Request

from .. import config
from ..realtime.queue import Broker
from ..realtime.settings import Settings


def component(key, name, status, detail, workspace=None):
    return dict(id=key, name=name, status=status, detail=detail, workspace=workspace)


def database_snapshot(path):
    """Read existing databases only; never migrate or create application data."""
    result = dict(status='unknown', detail='Database has not been initialized.', accounts=[], outbox=None)
    if not path.is_file():
        return result
    try:
        with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=0.1)) as conn:
            conn.row_factory = sqlite3.Row
            deadline = time.monotonic()+0.2
            conn.set_progress_handler(lambda: int(time.monotonic()>deadline), 1000)
            conn.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone()
            tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            result.update(status='healthy', detail='Read-only database query succeeded.')
            if {'accounts', 'realtime_accounts'} <= tables:
                result['accounts'] = [dict(account_id=r['account_id'], enabled=bool(r['enabled']),
                    last_sync=r['last_sync'], status='degraded' if r['last_error'] else 'unknown' if r['last_sync'] is None else 'healthy' if 0 <= time.time()-r['last_sync']<600 else 'unknown')
                    for r in conn.execute('SELECT account_id,enabled,last_sync,last_error FROM realtime_accounts ORDER BY account_id LIMIT 100')]
            if 'realtime_outbox' in tables:
                result['outbox'] = conn.execute('SELECT COUNT(*) FROM realtime_outbox').fetchone()[0]
    except (sqlite3.Error, OSError, ValueError):
        result.update(status='unavailable', detail='Database could not be read. Check file access or database contention.')
    return result


def read_redis(settings, workspace_ids):
    """One bounded pipeline; never consume jobs, acknowledge, or create groups."""
    from redis import Redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry
    with Redis.from_url(settings.redis_url, decode_responses=True,
                        socket_connect_timeout=0.4, socket_timeout=0.8, retry=Retry(NoBackoff(), 0)) as client:
        pipe = client.pipeline(transaction=False)
        pipe.ping()
        for wid in workspace_ids:
            naming = Broker(settings.redis_url, wid)
            for kind in sorted(Broker.kinds):
                pipe.xlen(naming.stream_name(kind))
                pipe.zcard(naming.prefix+'retry:'+kind)
                pipe.xlen(naming.deadletter_stream(kind))
            pipe.xrevrange(naming.prefix+'monitor', count=200)
        values = pipe.execute()
    if values[0] is not True:
        raise RuntimeError('Redis unavailable')
    result = {}
    offset = 1
    for wid in workspace_ids:
        queues = []
        for kind in sorted(Broker.kinds):
            pending, retry, dead = values[offset:offset+3]
            queues.append(dict(kind=kind, pending=pending, retry=retry, dead=dead))
            offset += 3
        events = []
        for eid, fields in values[offset]:
            # All Redis data is untrusted: only fixed vocabulary is displayed.
            if fields.get('action') not in {'queued', 'started', 'completed', 'retry_or_failed', 'published'}:
                continue
            if fields.get('kind') not in Broker.kinds | {'events'}:
                continue
            try:
                if not re.fullmatch(r'[0-9]{1,16}-[0-9]{1,16}', eid):
                    continue
                at = int(eid.split('-')[0])/1000
                if not 0 <= at <= time.time()+60:
                    continue
            except (ValueError, AttributeError):
                continue
            events.append(dict(id=wid+':'+eid, at=at, workspace=wid,
                               component=fields['kind'], action=fields['action'],
                               job_id=fields.get('job_id','') if re.fullmatch(r'[0-9]{1,16}-[0-9]{1,16}', fields.get('job_id','')) else '',
                               status='degraded' if fields['action']=='retry_or_failed' else 'healthy'))
        result[wid] = dict(queues=queues, events=events)
        offset += 1
    return result


def queue_totals(snapshot):
    """Queue depth per stage across workspaces, as the page shows it."""
    if snapshot.get('architecture') == 'shared':
        return snapshot.get('global_queues') or []
    totals = {}
    for workspace in snapshot.get('workspaces', []):
        for queue in workspace.get('queues', []):
            row = totals.setdefault(queue['kind'], dict(kind=queue['kind'], pending=0, retry=0, dead=0))
            for key in ('pending', 'retry', 'dead'):
                row[key] += queue[key]
    return list(totals.values())


class Monitor:
    def __init__(self, store, pool, model_activity=None):
        from .monitoring_metrics import QueueHistory
        self.store, self.pool = store, pool
        self.model_activity = model_activity
        self._lock = threading.Lock()
        self._cached = None
        self._expires = 0
        self.queue_history = QueueHistory()

    def snapshot(self):
        # Multiple tabs share probe work without spawning unbounded jobs.
        with self._lock:
            if self._cached is not None and time.monotonic()<self._expires:
                return self._cached
            result = self._collect()
            self._cached, self._expires = result, time.monotonic()+2
            queues = queue_totals(result)
            if queues:
                self.queue_history.record(queues)
            return result

    def job_minutes(self, since_minute):
        from .monitoring_metrics import read_job_minutes
        if not getattr(self.pool, 'amqp_url', None):
            return {}
        return read_job_minutes(Path(self.store.root)/'shared-runtime'/'metrics.json', since_minute)

    def _collect(self):
        if getattr(self.pool,'amqp_url',None):
            from ..shared.monitoring import shared_snapshot
            return shared_snapshot(self.store,self.pool,self.model_activity)
        checked_at = time.time()
        admins = self.store.list_admins()
        states = self.pool.status()
        components = [component('gateway', 'Gateway', 'healthy', 'Owner monitoring request served successfully.')]
        # A SELECT, not integrity_check: health polling must not scan the database.
        control = database_snapshot(self.store.path)
        components.append(component('control-db', 'Control database', control['status'], control['detail']))
        active = self.model_activity() if self.model_activity else None
        components.append(component('model-scheduler', 'Shared model scheduler', 'healthy' if active is not None else 'unknown',
            f'{active} active model lease(s). External model health is not probed.' if active is not None else 'Model scheduler activity is unavailable; external model health is not probed.'))
        workspaces, events = [], []
        try:
            settings = Settings.from_env()
            redis_status = 'disabled' if not settings.enabled else 'healthy'
        except ValueError:
            settings, redis_status = Settings(), 'unavailable'
        redis_data = {}
        if settings.enabled:
            try:
                redis_data = read_redis(settings, [a['workspace_id'] for a in admins if a['enabled']])
            except Exception:
                redis_status = 'unavailable'
        components.append(component('redis', 'Redis / event broker', redis_status,
            {'healthy':'Redis responded; queue counts and recent events were read.',
             'disabled':'Automatic real-time processing is not configured.',
             'unavailable':'Real-time configuration or broker connection is unavailable.'}[redis_status]))
        for admin in admins:
            wid = admin['workspace_id']
            enabled = bool(admin['enabled'])
            worker_status = 'disabled' if not enabled else 'healthy' if states.get(wid)=='running' else 'unavailable'
            components.append(component(wid+':worker', 'Workspace worker', worker_status,
                'Worker supervisor reports running.' if worker_status=='healthy' else 'Workspace suspended.' if not enabled else 'Worker is starting, stopped, or unavailable.', wid))
            database = dict(status='disabled', detail='Workspace suspended.', accounts=[], outbox=None)
            if enabled:
                try:
                    workspace = self.store.workspace(wid)
                except ValueError:
                    workspace = None
                if workspace and workspace.get('root'):
                    path = Path(workspace['root'])/'data'/'mailcheck.db'
                else:
                    paths = getattr(self.pool, 'legacy_paths', None)
                    path = Path(paths[1]) if paths else config.db_path()
                database = database_snapshot(path) if workspace else dict(status='unavailable', detail='Workspace changed during health check.', accounts=[], outbox=None)
            components.append(component(wid+':database', 'Workspace database', database['status'], database['detail'], wid))
            opted_in = [a for a in database['accounts'] if a['enabled']]
            realtime_status = 'disabled' if not enabled or redis_status=='disabled' else 'unknown'
            if enabled and (redis_status=='unavailable' or (redis_status!='disabled' and (worker_status=='unavailable' or database['status']=='unavailable'))):
                realtime_status = 'unavailable'
            elif opted_in and redis_status=='healthy' and worker_status=='healthy':
                realtime_status = 'degraded' if any(a['status']=='degraded' for a in opted_in) else 'unknown'
            queues = redis_data.get(wid, {}).get('queues', [])
            for kind, name in [('mail','Mail collection'), ('calendar','Calendar collection'), ('classify','Classification')]:
                queue = next((q for q in queues if q['kind']==kind), None)
                status = 'degraded' if realtime_status not in {'unavailable','disabled'} and queue and (queue['dead'] or queue['retry']) else realtime_status
                components.append(component(wid+':'+kind, name, status,
                    'Queue metrics are available below. Provider/model health and collector thread liveness are not directly probed.' if queue else 'No current queue or collector health evidence.', wid))
            components.append(component(wid+':delivery', 'Event publication',
                'disabled' if realtime_status=='disabled' else 'unavailable' if realtime_status=='unavailable' else 'degraded' if database['outbox'] else 'unknown',
                f"{database['outbox']} committed changes awaiting publication." if database['outbox'] is not None else 'Publication backlog is unavailable.', wid))
            workspaces.append(dict(id=wid, name=admin['workspace_name'], enabled=enabled,
                                   accounts=database['accounts'], queues=queues, outbox=database['outbox']))
            events.extend(redis_data.get(wid, {}).get('events', []))
        return dict(checked_at=checked_at, components=components, workspaces=workspaces,
                    events=sorted(events, key=lambda e: (e['at'], e['id']), reverse=True)[:200],
                    event_retention=1000)


def _sample_queues(reference, stop):
    """Keep queue-depth history while nobody is watching the page."""
    from .monitoring_metrics import QUEUE_SAMPLE_SECONDS
    while not stop.wait(QUEUE_SAMPLE_SECONDS):
        monitor = reference()
        if monitor is None:
            return
        try:
            monitor.snapshot()
        except Exception:
            pass
        del monitor


def install(app, store, pool, owner, model_activity=None, sample_queues=None):
    import weakref
    from fastapi import HTTPException
    from .monitoring_metrics import RANGES, build_series
    from .traffic_metrics import TrafficMetrics, TrafficMiddleware
    monitor = Monitor(store, pool, model_activity)
    traffic = TrafficMetrics()
    app.add_middleware(TrafficMiddleware, metrics=traffic)
    app.state.traffic_metrics = traffic
    app.state.system_monitor = monitor
    if sample_queues is None:
        sample_queues = bool(getattr(pool, 'amqp_url', None))
    if sample_queues:
        stop = threading.Event()
        app.state.monitoring_stop = stop
        threading.Thread(target=_sample_queues, args=(weakref.ref(monitor), stop),
                         daemon=True, name='monitor-queue-sampler').start()
    series_cache, series_lock = {}, threading.Lock()

    @app.get('/api/admin/system-monitoring')
    def snapshot(request: Request):
        owner(request)
        return monitor.snapshot()

    @app.get('/api/admin/system-monitoring/metrics')
    def metrics(request: Request, range: str = '1h'):
        owner(request)
        if range not in RANGES:
            raise HTTPException(422, 'Choose a range of 1h, 6h or 24h.')
        with series_lock:
            cached = series_cache.get(range)
            if cached and time.monotonic() < cached[0]:
                return cached[1]
            step, count = RANGES[range]
            since = int((time.time() - step * (count + 1)) // 60)
            jobs_tracked = bool(getattr(pool, 'amqp_url', None))
            result = build_series(range, traffic.rows(since), monitor.job_minutes(since),
                                  monitor.queue_history.rows(since), jobs_tracked=jobs_tracked)
            series_cache[range] = (time.monotonic() + 5, result)
            return result
