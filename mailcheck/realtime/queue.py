"""Workspace-scoped Redis Streams jobs and independently replayable changes.

Only account identifiers and fixed operational hints enter Redis. Pending jobs
are never trimmed: successful jobs are deleted after ACK, failed jobs move
atomically into a delayed retry set or bounded dead-letter stream.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from contextlib import contextmanager


_RETRY_DUE = '''
local due=redis.call('ZRANGEBYSCORE',KEYS[1],'-inf',ARGV[1],'LIMIT',0,100)
for _,payload in ipairs(due) do
    local item=cjson.decode(payload)
    redis.call('XADD',KEYS[2],'*','account_id',item.account_id,'kind',item.kind,
        'reason',item.reason,'attempt',item.attempt)
    redis.call('ZREM',KEYS[1],payload)
end
return #due
'''
_FAIL = '''
local pending=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #pending==0 then return 0 end
if ARGV[6]~='' and pending[1][2]~=ARGV[6] then return 0 end
local rows=redis.call('XRANGE',KEYS[1],ARGV[2],ARGV[2])
if #rows==0 then return 0 end
local item={}
for i=1,#rows[1][2],2 do item[rows[1][2][i]]=rows[1][2][i+1] end
local attempt=tonumber(item.attempt or '1')
if attempt>=tonumber(ARGV[3]) then
    redis.call('XADD',KEYS[3],'MAXLEN','~',1000,'*','account_id',item.account_id,
        'kind',item.kind,'reason',item.reason,'attempt',tostring(attempt))
else
    local delay=math.min(60000,tonumber(ARGV[5])*2^(attempt-1))
    item.attempt=tostring(attempt+1)
    item.retry_id=ARGV[2]
    redis.call('ZADD',KEYS[2],tonumber(ARGV[4])+delay,cjson.encode(item))
end
redis.call('XACK',KEYS[1],ARGV[1],ARGV[2])
redis.call('XDEL',KEYS[1],ARGV[2])
return 1
'''
_ACK = '''
local pending=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #pending==0 then return 0 end
if ARGV[3]~='' and pending[1][2]~=ARGV[3] then return 0 end
redis.call('XACK',KEYS[1],ARGV[1],ARGV[2])
redis.call('XDEL',KEYS[1],ARGV[2])
return 1
'''
_HEARTBEAT = '''
local pending=redis.call('XPENDING',KEYS[1],ARGV[1],ARGV[2],ARGV[2],1)
if #pending==0 or pending[1][2]~=ARGV[3] then return 0 end
redis.call('XCLAIM',KEYS[1],ARGV[1],ARGV[3],0,ARGV[2],'IDLE',0,'JUSTID')
return 1
'''
_PUBLISH = '''
local existing=redis.call('GET',KEYS[2])
if existing then return existing end
local id=redis.call('XADD',KEYS[1],'MAXLEN','~',10000,'*','topics',ARGV[1],'event_id',ARGV[2])
redis.call('SET',KEYS[2],id,'EX',604800)
return id
'''
_RENEW = '''
if redis.call('GET',KEYS[1])==ARGV[1] then
    return redis.call('PEXPIRE',KEYS[1],ARGV[2])
end
return 0
'''
_RELEASE = '''
if redis.call('GET',KEYS[1])==ARGV[1] then return redis.call('DEL',KEYS[1]) end
return 0
'''


class Lease:
    """Renewable account exclusion; callers can check ownership before writes."""
    def __init__(self, client, key: str, ttl_ms: int):
        if ttl_ms < 30:
            raise ValueError('Lease lifetime must be at least 30 milliseconds')
        self.client, self.key, self.ttl_ms = client, key, ttl_ms
        self.token = uuid.uuid4().hex
        self.acquired = bool(client.set(key, self.token, nx=True, px=ttl_ms))
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        if self.acquired:
            self._thread = threading.Thread(target=self._renew, name='realtime-lease', daemon=True)
            self._thread.start()

    def __bool__(self):
        return self.acquired and not self.lost.is_set()

    def _renew(self):
        while not self._stop.wait(self.ttl_ms / 3000):
            try:
                if not self.client.eval(_RENEW, 1, self.key, self.token, self.ttl_ms):
                    self.lost.set()
                    return
            except Exception:
                self.lost.set()
                return

    def ensure_owned(self):
        if not self or self.client.get(self.key) != self.token:
            self.lost.set()
            raise RuntimeError('Realtime account lease lost')

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self.acquired:
            self.client.eval(_RELEASE, 1, self.key, self.token)


class Processing:
    """Refresh a pending entry only while this consumer still owns it."""
    def __init__(self, broker, kind: str, message_id: str, consumer: str):
        self.broker, self.kind = broker, kind
        self.message_id, self.consumer = message_id, consumer
        self.lost = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self.acquired = self._heartbeat()
        if self.acquired:
            self._thread = threading.Thread(target=self._renew, name='realtime-pending', daemon=True)
            self._thread.start()
        else:
            self.lost.set()

    def __bool__(self):
        return self.acquired and not self.lost.is_set()

    def _heartbeat(self):
        return bool(self.broker.redis.eval(_HEARTBEAT, 1, self.broker.stream_name(self.kind),
                                          self.broker.group, self.message_id, self.consumer))

    def _renew(self):
        while not self._stop.wait(self.broker.reclaim_idle_ms / 3000):
            try:
                if not self._heartbeat():
                    self.lost.set()
                    return
            except Exception:
                self.lost.set()
                return

    def ensure_owned(self):
        if not self or not self._heartbeat():
            self.lost.set()
            raise RuntimeError('Realtime job ownership lost')

    def close(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)


class Broker:
    group = 'workers'
    kinds = frozenset({'mail', 'calendar', 'classify'})
    reasons = frozenset({'notification', 'reconcile', 'poll', 'manual', 'startup', 'retry'})
    topics = frozenset({'messages', 'classifications', 'interviews', 'accounts', 'sourcing', 'payments'})

    def __init__(self, redis_url: str, workspace_id: str, *, reclaim_idle_ms: int = 60000,
                 max_attempts: int = 5, retry_base_ms: int = 1000):
        self.redis_url = redis_url
        self.workspace_id = str(workspace_id)
        # A hash avoids untrusted workspace names changing key structure/hash slots.
        namespace = hashlib.sha256(self.workspace_id.encode()).hexdigest()
        self.prefix = 'offerpath:realtime:{' + namespace + '}:'
        self.reclaim_idle_ms = max(1, reclaim_idle_ms)
        self.max_attempts = max(1, max_attempts)
        self.retry_base_ms = max(1, retry_base_ms)
        self._redis = None
        self._reclaim_cursors: dict[str, str] = {}

    @property
    def redis(self):
        if self._redis is None:
            import redis
            self._redis = redis.Redis.from_url(self.redis_url, decode_responses=True,
                                               socket_connect_timeout=3, socket_timeout=3)
        return self._redis

    def stream_name(self, kind: str) -> str:
        if kind not in self.kinds:
            raise ValueError('Unknown realtime job kind')
        return self.prefix + 'jobs:' + kind

    def deadletter_stream(self, kind: str) -> str:
        self.stream_name(kind)
        return self.prefix + 'dead:' + kind

    @property
    def changes_stream(self) -> str:
        return self.prefix + 'changes'

    def _group(self, kind: str):
        from redis.exceptions import ResponseError
        try:
            self.redis.xgroup_create(self.stream_name(kind), self.group, id='0-0', mkstream=True)
        except ResponseError as exc:
            if 'BUSYGROUP' not in str(exc):
                raise

    def enqueue(self, kind: str, account_id: int, reason: str = 'notification') -> str:
        if reason not in self.reasons:
            raise ValueError('Unknown realtime reason')
        if not isinstance(account_id, int) or isinstance(account_id, bool) or account_id < 1:
            raise ValueError('Account ID must be a positive integer')
        return self.redis.xadd(self.stream_name(kind), {'account_id': str(account_id),
                              'kind': kind, 'reason': reason, 'attempt': '1'})

    def claim(self, kind: str, consumer: str, block_ms: int = 0) -> list[tuple[str, dict]]:
        self._group(kind)
        stream = self.stream_name(kind)
        self.redis.eval(_RETRY_DUE, 2, self.prefix+'retry:'+kind, stream, int(time.time()*1000))
        # Redis 7 atomically transfers stale pending jobs, including deleted-entry cleanup.
        claim_result = self.redis.xautoclaim(stream, self.group, consumer,
                                             self.reclaim_idle_ms,
                                             self._reclaim_cursors.get(kind, '0-0'), count=1)
        self._reclaim_cursors[kind] = claim_result[0]
        reclaimed = claim_result[1]
        jobs = []
        for message_id, fields in reclaimed:
            pending = self.redis.xpending_range(stream, self.group, message_id, message_id, 1)
            if pending and pending[0]['times_delivered'] > self.max_attempts:
                # A crashing consumer also has a finite delivery budget.
                self._deadletter(kind, message_id, fields, consumer)
            else:
                jobs.append((message_id, fields))
        if jobs:
            return jobs
        results = self.redis.xreadgroup(self.group, consumer, {stream: '>'}, count=1,
                                       block=min(block_ms, 1000) if block_ms > 0 else None)
        return [(message_id, fields) for _, entries in results for message_id, fields in entries]

    def ack(self, kind: str, message_id: str, consumer: str | None = None) -> bool:
        return bool(self.redis.eval(_ACK, 1, self.stream_name(kind), self.group,
                                    message_id, consumer or ''))

    def fail(self, kind: str, message_id: str, fields: dict,
             consumer: str | None = None) -> bool:
        # Read the durable original in Lua, never trust callback-supplied fields.
        return bool(self.redis.eval(_FAIL, 3, self.stream_name(kind), self.prefix+'retry:'+kind,
                        self.deadletter_stream(kind), self.group, message_id,
                        self.max_attempts, int(time.time()*1000), self.retry_base_ms, consumer or ''))

    def _deadletter(self, kind: str, message_id: str, fields: dict, consumer: str):
        # The same atomic transition with a zero budget forces dead-lettering.
        self.redis.eval(_FAIL, 3, self.stream_name(kind), self.prefix+'retry:'+kind,
                        self.deadletter_stream(kind), self.group, message_id,
                        0, int(time.time()*1000), self.retry_base_ms, consumer)

    def publish(self, topics: list[str], event_id: int) -> str:
        if not topics or not set(topics) <= self.topics:
            raise ValueError('Unknown realtime change topic')
        return self.redis.eval(_PUBLISH, 2, self.changes_stream,
                               self.prefix+'published:'+str(int(event_id)),
                               json.dumps(sorted(set(topics))), str(int(event_id)))

    def latest_change_id(self) -> str:
        rows = self.redis.xrevrange(self.changes_stream, count=1)
        return rows[0][0] if rows else '0-0'

    def read_changes(self, cursor: str, block_ms: int = 0) -> list[tuple[str, dict]]:
        rows = self.redis.xread({self.changes_stream: cursor}, count=100,
                               block=min(block_ms, 1000) if block_ms > 0 else None)
        return [(message_id, fields) for _, entries in rows for message_id, fields in entries]

    @contextmanager
    def processing(self, kind: str, message_id: str, consumer: str):
        processing = Processing(self, kind, message_id, consumer)
        try:
            yield processing
        finally:
            processing.close()

    @contextmanager
    def lease(self, account_id: int, ttl_ms: int = 30000, *, lane: str = 'collection'):
        if lane not in {'collection', 'classification'}:
            raise ValueError('Unknown realtime lease lane')
        lease = Lease(self.redis, self.prefix+'lease:'+lane+':'+str(int(account_id)), ttl_ms)
        try:
            yield lease
        finally:
            lease.close()

    def close(self):
        if self._redis is not None:
            self._redis.close()
