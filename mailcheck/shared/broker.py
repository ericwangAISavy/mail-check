"""Confirmed AMQP transport. Connections belong to their creating thread.

A consumer must call ``process_events`` while a separate thread performs long
business operations. Only the connection owner calls claim/ack/fail.
"""
import importlib
import json
import os
from pathlib import Path
import time
import re
import threading
import uuid

JOBS_EXCHANGE = 'offerpath.shared.jobs'
CHANGES_EXCHANGE = 'offerpath.shared.changes'
DEAD_NOTICES_QUEUE = 'offerpath.shared.dead-notices'
MAX_PENDING_PER_WORKSPACE = 16


class PendingCapacityError(RuntimeError):
    """Workspace pending capacity is full; caller must retry later."""


KINDS = frozenset(('mail', 'calendar', 'classify', 'manual-check',
                   'manual-reclassify', 'calendar-analysis', 'scheduled-check', 'live-inbox'))
RETRY_DELAYS_MS = (5000, 30000, 120000, 600000)
MAX_ATTEMPTS = 5
_FIELDS = frozenset(('version', 'id', 'workspace_id', 'account_id', 'kind',
                     'reason', 'attempt', 'payload', 'dispatch_id'))


def _workspace(value):
    if not isinstance(value, str) or not re.fullmatch(r'legacy|[0-9a-f]{32}', value):
        raise ValueError('invalid workspace identity')
    return value


def _uuid(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('invalid job identity')
    return value


def validate_envelope(fields):
    """Reject unknown fields and secret-bearing arbitrary payloads."""
    if not isinstance(fields, dict) or set(fields) != _FIELDS:
        raise ValueError('invalid job envelope fields')
    if type(fields['version']) is not int or fields['version'] != 1:
        raise ValueError('unsupported job envelope version')
    _uuid(fields['id'])
    _workspace(fields['workspace_id'])
    if fields['kind'] not in KINDS:
        raise ValueError('unsupported job kind')
    account = fields['account_id']
    if type(account) is not int or account < 0 or (account == 0 and fields['kind'] in ('mail', 'calendar', 'classify')):
        raise ValueError('invalid account identity')
    if fields['kind'] in ('scheduled-check', 'live-inbox') and (account != 0 or fields['reason'] not in ('reconcile', 'startup')):
        raise ValueError('invalid workspace scheduled job')
    if fields['reason'] not in ('notification', 'reconcile', 'poll', 'manual', 'startup', 'retry'):
        raise ValueError('unsupported job reason')
    manual = fields['kind'] in ('manual-check', 'manual-reclassify')
    if manual and fields['dispatch_id'] is None:
        raise ValueError('manual jobs require dispatch provenance')
    if not manual and (fields['dispatch_id'] is not None or fields['reason'] == 'manual'):
        raise ValueError('automatic jobs cannot carry manual authorization')
    if type(fields['attempt']) is not int or not 0 <= fields['attempt'] < MAX_ATTEMPTS:
        raise ValueError('invalid attempt')
    if fields['payload'] != {} or not isinstance(fields['payload'], dict):
        raise ValueError('job payload must be empty; resolve business data server-side')
    if fields['dispatch_id'] is not None:
        _uuid(fields['dispatch_id'])
    return fields


def queue_name(kind):
    if kind not in KINDS:
        raise ValueError('unsupported job kind')
    return f'offerpath.shared.work.{kind}'


def ensure_topology(channel):
    channel.exchange_declare(exchange=JOBS_EXCHANGE, exchange_type='direct', durable=True)
    channel.exchange_declare(exchange=CHANGES_EXCHANGE, exchange_type='topic', durable=True)
    channel.queue_declare(queue=DEAD_NOTICES_QUEUE, durable=True,
                          arguments={'x-queue-type': 'quorum'})
    for kind in sorted(KINDS):
        channel.queue_bind(queue=DEAD_NOTICES_QUEUE, exchange=JOBS_EXCHANGE,
                           routing_key=f'dead.{kind}')
        dead = f'offerpath.shared.dead.{kind}'
        channel.queue_declare(queue=dead, durable=True, arguments={'x-queue-type': 'quorum'})
        channel.queue_bind(queue=dead, exchange=JOBS_EXCHANGE, routing_key=f'dead.{kind}')
        safety = {'x-queue-type': 'quorum', 'x-overflow': 'reject-publish',
                  'x-dead-letter-strategy': 'at-least-once',
                  'x-dead-letter-exchange': JOBS_EXCHANGE}
        channel.queue_declare(queue=queue_name(kind), durable=True, arguments={
            **safety, 'x-delivery-limit': 5, 'x-dead-letter-routing-key': f'dead.{kind}'})
        channel.queue_bind(queue=queue_name(kind), exchange=JOBS_EXCHANGE, routing_key=kind)
        for tier, delay in enumerate(RETRY_DELAYS_MS):
            retry = f'offerpath.shared.retry.{kind}.{tier}'
            channel.queue_declare(queue=retry, durable=True, arguments={
                **safety, 'x-message-ttl': delay, 'x-dead-letter-routing-key': kind})
            channel.queue_bind(queue=retry, exchange=JOBS_EXCHANGE, routing_key=f'retry.{kind}.{tier}')
    # A bounded durable sink guarantees a route even with no live gateway.
    channel.queue_declare(queue='offerpath.shared.changes.sink', durable=True,
                          arguments={'x-queue-type': 'quorum', 'x-message-ttl': 60000,
                                     'x-max-length': 10000, 'x-overflow': 'drop-head'})
    channel.queue_bind(queue='offerpath.shared.changes.sink', exchange=CHANGES_EXCHANGE,
                       routing_key='changes.#')


class RabbitBroker:
    def __init__(self, url=None, workspace_id=None):
        self.url = url or os.environ.get('AMQP_URL')
        self.workspace_id = _workspace(workspace_id) if workspace_id is not None else None
        self._connection = self._channel = self._owner = self._pika = None

    def _connect(self):
        if self._owner is not None and self._owner != threading.get_ident():
            raise RuntimeError('RabbitBroker connection used from another thread')
        if self._connection is None:
            if not self.url:
                raise RuntimeError('AMQP_URL is required')
            self._pika = importlib.import_module('pika')
            params = self._pika.URLParameters(self.url)
            params.heartbeat = 60
            params.blocked_connection_timeout = 30
            params.socket_timeout = 10
            params.connection_attempts = 1
            self._connection = self._pika.BlockingConnection(params)
            self._owner = threading.get_ident()
            self._channel = self._connection.channel()
            try:
                ensure_topology(self._channel)
                self._channel.confirm_delivery()
                self._channel.basic_qos(prefetch_count=1)
            except Exception:
                self.close()
                raise
        return self._channel

    def _publish(self, exchange, routing_key, body):
        channel = self._connect()
        result = channel.basic_publish(exchange=exchange, routing_key=routing_key,
            body=json.dumps(body, separators=(',', ':'), allow_nan=False).encode(), mandatory=True,
            properties=self._pika.BasicProperties(content_type='application/json', delivery_mode=2,
                                                   message_id=str(body.get('id', body.get('event_id', '')))))
        if result is False:
            raise RuntimeError('broker did not confirm publication')

    def enqueue(self, kind, account_id, reason='notification', *, workspace_id=None,
                payload=None, dispatch_id=None, job_id=None):
        fields = validate_envelope(dict(version=1, id=job_id or str(uuid.uuid4()),
            workspace_id=workspace_id if workspace_id is not None else self.workspace_id,
            account_id=account_id, kind=kind, reason=reason, attempt=0,
            payload={} if payload is None else payload, dispatch_id=dispatch_id))
        self._publish(JOBS_EXCHANGE, kind, fields)
        return fields['id']

    def _unique_path(self, kind, account_id, workspace_id, coordination_root):
        # Validate the complete envelope before using any routing value as a path.
        validate_envelope(dict(version=1, id=str(uuid.uuid4()), workspace_id=workspace_id,
            account_id=account_id, kind=kind, reason='reconcile', attempt=0,
            payload={}, dispatch_id=None))
        return Path(coordination_root) / workspace_id / 'pending' / f'{kind}-{account_id}.json'

    @staticmethod
    def _read_marker(path):
        try:
            marker = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        if (not isinstance(marker, dict) or set(marker) != {'id', 'dirty', 'confirmed', 'timestamp'}
                or type(marker['dirty']) is not bool or type(marker['confirmed']) is not bool):
            raise ValueError('invalid pending job marker')
        _uuid(marker['id'])
        return marker

    def enqueue_unique(self, kind, account_id, reason='notification', *, workspace_id=None,
                       coordination_root, dirty_existing=True):
        from .state import OperationLock, atomic_json
        workspace = workspace_id if workspace_id is not None else self.workspace_id
        path = self._unique_path(kind, account_id, workspace, coordination_root)
        # Reject invalid reasons even when an existing job would avoid publication.
        validate_envelope(dict(version=1, id=str(uuid.uuid4()), workspace_id=workspace,
            account_id=account_id, kind=kind, reason=reason, attempt=0, payload={}, dispatch_id=None))
        with OperationLock(path.parent.parent / 'pending-capacity.lock'), OperationLock(path.with_suffix('.lock')):
            marker = self._read_marker(path)
            if marker is not None:
                marker['dirty'] = marker['dirty'] or dirty_existing
                atomic_json(path, marker)
                if marker['confirmed']:
                    return marker['id']
            else:
                if sum(1 for _ in path.parent.glob('*.json')) >= MAX_PENDING_PER_WORKSPACE:
                    raise PendingCapacityError('workspace pending job capacity reached')
                marker = dict(id=str(uuid.uuid4()), dirty=False, confirmed=False, timestamp=time.time())
                atomic_json(path, marker)
            self.enqueue(kind, account_id, reason, workspace_id=workspace, job_id=marker['id'])
            marker['confirmed'] = True
            atomic_json(path, marker)
            self._record_queued(coordination_root, workspace, kind, marker['id'])
            return marker['id']

    def complete_unique(self, fields, coordination_root):
        from .state import OperationLock, atomic_json
        validate_envelope(fields)
        if fields['kind'] in ('manual-check', 'manual-reclassify'):
            return
        path = self._unique_path(fields['kind'], fields['account_id'],
                                 fields['workspace_id'], coordination_root)
        with OperationLock(path.with_suffix('.lock')):
            marker = self._read_marker(path)
            if marker is None or marker['id'] != fields['id']:
                return
            if marker['dirty']:
                # A lost confirm must retry the same follow-up identity, even if
                # the original is redelivered before we can replace its marker.
                next_id = str(uuid.uuid5(uuid.UUID(fields['id']), 'follow-up'))
                self.enqueue(fields['kind'], fields['account_id'], fields['reason'],
                             workspace_id=fields['workspace_id'], job_id=next_id)
                atomic_json(path, dict(id=next_id, dirty=False, confirmed=True, timestamp=time.time()))
                self._record_queued(coordination_root, fields['workspace_id'], fields['kind'], next_id)
            else:
                path.unlink()

    def abandon_unique(self, fields, coordination_root):
        from .state import OperationLock
        validate_envelope(fields)
        if fields['kind'] in ('manual-check', 'manual-reclassify'):
            return
        path = self._unique_path(fields['kind'], fields['account_id'],
                                 fields['workspace_id'], coordination_root)
        with OperationLock(path.with_suffix('.lock')):
            marker = self._read_marker(path)
            if marker is not None and marker['id'] == fields['id']:
                path.unlink()

    @staticmethod
    def _record_queued(root, workspace, kind, job_id):
        try:
            from .telemetry import record
            record(Path(root), workspace, kind, 'queued', job_id)
        except Exception:
            pass

    def claim_dead_notice(self):
        channel = self._connect()
        method, properties, body = channel.basic_get(queue=DEAD_NOTICES_QUEUE, auto_ack=False)
        if method is None:
            return None
        try:
            fields = validate_envelope(json.loads(body))
        except (ValueError, TypeError, UnicodeError):
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            return None
        return method.delivery_tag, fields

    def claim(self, kind):
        channel = self._connect()
        method, properties, body = channel.basic_get(queue=queue_name(kind), auto_ack=False)
        if method is None:
            return None
        try:
            fields = validate_envelope(json.loads(body))
            if fields['kind'] != kind:
                raise ValueError('wrong job queue')
        except (ValueError, TypeError, UnicodeError):
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            return None
        return method.delivery_tag, fields

    def ack(self, tag):
        self._connect().basic_ack(delivery_tag=tag)

    def fail(self, tag, fields):
        validate_envelope(fields)
        retry = dict(fields)
        if fields['attempt'] + 1 >= MAX_ATTEMPTS:
            route = f"dead.{fields['kind']}"
        else:
            retry['attempt'] += 1
            route = f"retry.{fields['kind']}.{fields['attempt']}"
        self._publish(JOBS_EXCHANGE, route, retry)
        self.ack(tag)

    def publish(self, topics, event_id, workspace_id=None):
        workspace = _workspace(workspace_id if workspace_id is not None else self.workspace_id)
        topics = list(topics)
        if not topics or any(not isinstance(t, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{0,63}', t) for t in topics):
            raise ValueError('invalid change topics')
        if type(event_id) not in (int, str) or not str(event_id) or len(str(event_id)) > 256:
            raise ValueError('invalid event identity')
        self._publish(CHANGES_EXCHANGE, f'changes.{workspace}',
                      dict(workspace_id=workspace, topics=topics, event_id=event_id))

    def process_events(self, time_limit=0):
        self._connect()
        self._connection.process_data_events(time_limit=time_limit)

    def close(self):
        if self._connection is not None:
            if self._owner != threading.get_ident():
                raise RuntimeError('RabbitBroker must close on connection owner thread')
            try:
                self._connection.close()
            finally:
                self._connection = self._channel = self._owner = None
