import asyncio

from mailcheck.shared.events import GatewaySubscriber, event_frames


def test_fanout_is_workspace_scoped_and_overflow_resyncs():
    async def check():
        subscriber = GatewaySubscriber('amqp://unused', capacity=1)
        first = subscriber.subscribe('a')
        other = subscriber.subscribe('b')
        subscriber.publish('a')
        assert await first.get() == 'changed'
        assert other.empty()
        subscriber.publish('a')
        subscriber.publish('a')
        assert await first.get() == 'resync'
        subscriber.unsubscribe('a', first)
        assert not subscriber.listeners.get('a')
    asyncio.run(check())


def test_connections_are_bounded_and_reconnect_resyncs():
    subscriber = GatewaySubscriber('amqp://unused')
    queues = [subscriber.subscribe('a') for _ in range(8)]
    try:
        subscriber.subscribe('a')
        assert False, 'ninth connection accepted'
    except ValueError:
        pass
    subscriber.resync()
    assert all(q.get_nowait() == 'resync' for q in queues)


def test_stream_revalidates_before_relay_and_ignores_payload():
    async def check():
        queue = asyncio.Queue()
        await queue.put('changed')
        allowed = iter([True, False])
        async def authorized():
            return next(allowed)
        stream = event_frames(queue, authorized)
        assert 'event: resync' in await anext(stream)
        assert 'event: session-ended' in await anext(stream)
        await stream.aclose()
    asyncio.run(check())


def test_hook_validates_registry_deduplicates_and_requires_confirmation(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from mailcheck.shared import events, broker
    recorded = []
    registered = {'workspace_id': 'a', 'kind': 'mail', 'account_id': 3}
    class Lookup:
        def __init__(self, path):
            pass
        def validate(self, sid, state):
            return registered if (sid, state) == ('known', 'secret') else None
    class FakeBroker:
        def __init__(self, url):
            pass
        def enqueue_unique(self, kind, account_id, reason, workspace_id, coordination_root):
            recorded.append((workspace_id, kind, account_id, reason, coordination_root))
            if fail[0]:
                raise RuntimeError('credentials should not escape')
        def close(self):
            pass
    fail = [False]
    monkeypatch.setattr(events, 'ReadOnlyRegistry', Lookup)
    monkeypatch.setattr(broker, 'RabbitBroker', FakeBroker)
    app = FastAPI()
    events.install(app, SimpleNamespace(root=tmp_path, workspace=lambda wid: {'enabled': True}),
                   lambda token: None, 'session', amqp_url='amqp://example')
    client = TestClient(app)
    assert client.post('/hooks/microsoft?validationToken=abc').text == 'abc'
    value = {'subscriptionId': 'known', 'clientState': 'secret', 'workspace_id': 'attacker'}
    assert client.post('/hooks/microsoft', json={'value': [value, value]}).status_code == 202
    assert recorded == [('a', 'mail', 3, 'notification', tmp_path / 'shared-runtime')]
    fail[0] = True
    response = client.post('/hooks/microsoft', json={'value': [value]})
    assert response.status_code == 503
    assert 'credentials' not in response.text
    assert client.post('/hooks/microsoft', json={'value': 'bad'}).status_code == 400


def test_event_route_rejects_wrong_workspace_and_bounded_connections(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from mailcheck.shared import events
    monkeypatch.setattr(events, 'ReadOnlyRegistry', lambda path: None)
    app = FastAPI()
    @app.middleware('http')
    async def identity(request, call_next):
        request.state.identity = {'workspace_id': 'a', 'bidder_id': 3}
        return await call_next(request)
    subscriber = GatewaySubscriber('amqp://unused')
    for _ in range(8):
        subscriber.subscribe('a')
    events.install(app, SimpleNamespace(root=tmp_path), lambda token: None, 'session',
                   amqp_url='amqp://unused', subscriber=subscriber)
    client = TestClient(app)
    assert client.get('/api/realtime/events?workspace=b').status_code == 409
    assert client.get('/api/realtime/events?workspace=a&cursor=arbitrary-old-cursor').status_code == 503
    assert client.get('/api/realtime/capabilities').json() == {'configured': True}


def test_registry_reads_do_not_create_missing_database(tmp_path):
    import sqlite3
    from mailcheck.shared.events import ReadOnlyRegistry
    path = tmp_path / 'missing.db'
    registry = ReadOnlyRegistry(path)
    try:
        registry.validate('sid', 'secret')
        assert False, 'missing registry accepted'
    except sqlite3.OperationalError:
        pass
    assert not path.exists()


def test_subscriber_uses_exclusive_queue_and_resyncs_on_reconnect(monkeypatch):
    import sys
    from types import SimpleNamespace
    subscriber = GatewaySubscriber('amqp://unused')
    recorded = []
    connections = []
    class Loop:
        def call_soon_threadsafe(self, fn, *args):
            recorded.append((fn.__name__, args))
    class Channel:
        def exchange_declare(self, **kwargs):
            assert kwargs['exchange'] == 'offerpath.shared.changes'
        def queue_declare(self, **kwargs):
            assert kwargs == {'queue': '', 'exclusive': True, 'auto_delete': True}
            return SimpleNamespace(method=SimpleNamespace(queue='temporary'))
        def queue_bind(self, **kwargs):
            assert kwargs['routing_key'] == 'changes.#'
        def basic_consume(self, **kwargs):
            kwargs['on_message_callback'](None, None, None, b'{"workspace_id":"a","secret":"hidden"}')
    class Connection:
        is_open = True
        def __init__(self, parameters):
            connections.append(self)
        def channel(self):
            return Channel()
        def process_data_events(self, **kwargs):
            if len(connections) >= 2:
                subscriber._stop.set()
            raise OSError('disconnected')
        def close(self):
            self.is_open = False
    monkeypatch.setitem(sys.modules, 'pika', SimpleNamespace(
        URLParameters=lambda url: SimpleNamespace(), BlockingConnection=Connection))
    subscriber._loop = Loop()
    subscriber._run()
    assert len(connections) == 2
    assert all(not connection.is_open for connection in connections)
    assert sum(name == 'resync' for name, args in recorded) >= 2
    assert ('publish', ('a',)) in recorded


def test_hook_skips_disabled_workspace_but_keeps_registry_errors(tmp_path, monkeypatch):
    import sqlite3
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from mailcheck.shared import events, broker
    recorded = []
    monkeypatch.setattr(events, 'ReadOnlyRegistry', lambda path: SimpleNamespace(validate=lambda sid, state:
        {'workspace_id': sid, 'kind': 'mail', 'account_id': 1}))
    monkeypatch.setattr(broker, 'RabbitBroker', lambda url: SimpleNamespace(
        enqueue_unique=lambda *args, **kwargs: recorded.append(kwargs['workspace_id']), close=lambda: None))
    failure = [ValueError('disabled')]
    def workspace(wid):
        if wid == 'disabled':
            raise failure[0]
        return {'enabled': True}
    app = FastAPI()
    events.install(app, SimpleNamespace(root=tmp_path, workspace=workspace), lambda token: None,
                   'session', amqp_url='amqp://unused')
    client = TestClient(app)
    body = {'value': [{'subscriptionId': wid, 'clientState': 'secret'} for wid in ('disabled', 'active')]}
    assert client.post('/hooks/microsoft', json=body).status_code == 202
    assert recorded == ['active']
    failure[0] = sqlite3.OperationalError('unavailable')
    assert client.post('/hooks/microsoft', json=body).status_code == 503
