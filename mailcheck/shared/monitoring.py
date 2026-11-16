"""Read-only operational evidence for the shared-process architecture."""
from contextlib import nullcontext
from pathlib import Path
import time
import json
import re
import math
import os

from .broker import KINDS, RETRY_DELAYS_MS, queue_name


def read_rabbit(url):
    """Passive queue probes only; pending is ready messages, not in-flight work."""
    import pika
    parameters = pika.URLParameters(url)
    parameters.socket_timeout = 2
    parameters.stack_timeout = 3
    parameters.blocked_connection_timeout = 2
    parameters.connection_attempts = 1
    connection = pika.BlockingConnection(parameters)
    try:
        channel = connection.channel()
        def count(name):
            return channel.queue_declare(queue=name, passive=True).method.message_count
        return [dict(kind=kind, pending=count(queue_name(kind)),
                     retry=sum(count(f'offerpath.shared.retry.{kind}.{tier}') for tier in range(len(RETRY_DELAYS_MS))),
                     dead=count(f'offerpath.shared.dead.{kind}')) for kind in sorted(KINDS)]
    finally:
        connection.close()


def read_events(root, workspace):
    from .telemetry import ACTIONS, KINDS as EVENT_KINDS
    path = Path(root)/'shared-runtime'/workspace/'events.json'
    try:
        # A monitoring request must not read arbitrary-sized or malformed history.
        with path.open('rb') as stream:
            raw = stream.read(1024*1024+1)
        if len(raw)>1024*1024:
            return []
        rows = json.loads(raw)
        if not isinstance(rows,list):
            return []
    except (OSError,ValueError):
        return []
    events = []
    uuid_pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
    for row in rows[-1000:]:
        if not isinstance(row,dict) or row.get('workspace')!=workspace:
            continue
        if not isinstance(row.get('component'),str) or not isinstance(row.get('action'),str):
            continue
        if row['component'] not in EVENT_KINDS or row['action'] not in ACTIONS:
            continue
        identity = row.get('id')
        at = row.get('at')
        if not isinstance(identity,str) or not re.fullmatch(uuid_pattern,identity):
            continue
        if type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<=time.time()+60:
            continue
        job = row.get('job_id','')
        safe_job = job if isinstance(job,str) and (re.fullmatch(uuid_pattern,job) or re.fullmatch(r'[0-9]{1,20}',job)) else ''
        events.append(dict(id=workspace+':'+identity,at=at,workspace=workspace,component=row['component'],
                           action=row['action'],job_id=safe_job,status='degraded' if row['action']=='retry_or_failed' else 'healthy'))
    return events


def model_activity_snapshot(root):
    """Read the shared file coordinator; never acquire its operation lock."""
    path = Path(root)/'shared-runtime'/'model-state.json'
    try:
        with path.open('rb') as stream:
            raw = stream.read(4097)
        if len(raw)>4096:
            return None
        state = json.loads(raw)
        if not isinstance(state,dict) or type(state.get('pid')) is not int or state['pid']<=0:
            return None
        workspace = state.get('workspace')
        if not isinstance(workspace,str) or not re.fullmatch(r'legacy|[0-9a-f]{32}',workspace):
            return None
        os.kill(state['pid'],0)
        return 1
    except FileNotFoundError:
        return 0
    except (OSError,ValueError,OverflowError):
        return None


def shared_snapshot(store, pool, model_activity=None):
    from ..web.system_monitoring import component, database_snapshot
    components = [component('gateway','Gateway','healthy','Owner monitoring request served successfully.')]
    control = database_snapshot(store.path)
    components.append(component('control-db','Control database',control['status'],control['detail']))
    active = model_activity_snapshot(store.root)
    components.append(component('model-scheduler','Shared model scheduler','healthy' if active is not None else 'unknown',
        f'{active} active model operation(s). Coordinated by the same-host file lock.' if active is not None else 'Shared file-lock coordinator activity is unknown; state is stale or unavailable.'))
    counts = dict(api=0, collection=0, model=0)
    with getattr(pool, '_lock', nullcontext()):
        workers = dict(pool.workers)
        slots = set(getattr(pool,'_slots',())) | set(workers)
        for slot in sorted(slots):
            worker = workers.get(slot)
            lane = 'api' if slot.startswith('shared-api-') else 'model' if slot.startswith('shared-job-model-') else 'collection'
            counts[lane] += 1
            running = worker is not None and worker.process.poll() is None
            ready = running and worker.ready
            components.append(component(slot, f'Shared {lane} process · {slot.rsplit("-",1)[-1]}',
                'healthy' if ready else 'unknown' if running else 'unavailable',
                'Process running and ready.' if ready else 'Process running; readiness pending.' if running else 'Process is stopped or unavailable.'))
    queues = []
    try:
        queues = read_rabbit(pool.amqp_url)
        broker_status, detail = 'healthy', 'Passive queue counts available. Counts include ready messages; in-flight messages are not measured.'
    except Exception:
        broker_status, detail = 'unavailable', 'RabbitMQ queue metrics are unavailable. No queue counts were inferred.'
    components.append(component('rabbitmq','RabbitMQ / shared queues',broker_status,detail))
    workspaces, events = [], []
    for admin in store.list_admins():
        wid, enabled = admin['workspace_id'], bool(admin['enabled'])
        events.extend(read_events(store.root,wid))
        database = dict(status='disabled', detail='Workspace suspended.', accounts=[], outbox=None)
        if enabled:
            try:
                workspace = store.workspace(wid)
                root = workspace.get('root') if workspace else None
                path = Path(root)/'data'/'mailcheck.db' if root else Path(pool.legacy_paths[1])
                database = database_snapshot(path)
            except (ValueError, OSError, TypeError, AttributeError):
                database = dict(status='unavailable',detail='Workspace database location unavailable.',accounts=[],outbox=None)
        components.append(component(wid+':database','Workspace database',database['status'],database['detail'],wid))
        components.append(component(wid+':delivery','Event publication',
            'disabled' if not enabled else 'degraded' if database['outbox'] else 'unknown',
            f"{database['outbox']} committed changes awaiting publication." if database['outbox'] is not None else 'Publication backlog is unavailable.',wid))
        # Markers are opaque coordination identities. Count names only; do not read job payloads.
        pending = None
        if enabled:
            directory = Path(store.root)/'shared-runtime'/wid/'pending'
            try:
                pending = sum(1 for path in directory.glob('*.json') if path.is_file()) if directory.is_dir() else 0
            except OSError:
                pass
        workspaces.append(dict(id=wid,name=admin['workspace_name'],enabled=enabled,accounts=database['accounts'],
                               queues=[],outbox=database['outbox'],pending_jobs=pending))
    return dict(checked_at=time.time(),architecture='shared',components=components,workspaces=workspaces,
                process_counts=counts,global_queues=queues,
                events=sorted(events,key=lambda event:(event['at'],event['id']),reverse=True)[:200],event_retention=1000)
