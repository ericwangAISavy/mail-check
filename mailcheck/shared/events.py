"""Gateway-local bounded fanout of RabbitMQ change hints (no replay contract)."""
from __future__ import annotations

import asyncio
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
import threading
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from ..realtime.storage import Registry
from ..web.realtime_routes import EventResponse


class ReadOnlyRegistry(Registry):
    """Use existing registry validation without initialization or migrations."""
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()


class GatewaySubscriber:
    def __init__(self, amqp_url, *, capacity=32):
        self.amqp_url = amqp_url
        self.capacity = capacity
        self.listeners = defaultdict(set)
        self._stop = threading.Event()
        self._thread = None
        self._loop = None

    def subscribe(self, workspace):
        if len(self.listeners[workspace]) >= 8:
            raise ValueError('Too many live connections')
        queue = asyncio.Queue(maxsize=self.capacity)
        self.listeners[workspace].add(queue)
        return queue

    def unsubscribe(self, workspace, queue):
        self.listeners[workspace].discard(queue)
        if not self.listeners[workspace]:
            self.listeners.pop(workspace, None)

    def publish(self, workspace, event='changed'):
        for queue in tuple(self.listeners.get(workspace, ())):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait('resync')
            else:
                queue.put_nowait(event)

    def resync(self):
        for workspace in tuple(self.listeners):
            self.publish(workspace, 'resync')

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._loop = asyncio.get_running_loop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name='gateway-changes')
        self._thread.start()

    async def stop(self):
        self._stop.set()
        if self._thread:
            await asyncio.to_thread(self._thread.join, 10)

    def _run(self):
        # This thread alone owns the Pika connection and every channel operation.
        import pika
        while not self._stop.is_set():
            connection = None
            try:
                parameters = pika.URLParameters(self.amqp_url)
                parameters.socket_timeout = 3
                parameters.blocked_connection_timeout = 3
                parameters.connection_attempts = 1
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                channel.exchange_declare(exchange='offerpath.shared.changes', exchange_type='topic', durable=True)
                queue = channel.queue_declare(queue='', exclusive=True, auto_delete=True).method.queue
                channel.queue_bind(exchange='offerpath.shared.changes', queue=queue, routing_key='changes.#')
                def receive(channel, method, properties, body):
                    try:
                        payload = json.loads(body)
                        workspace = payload.get('workspace_id')
                        if isinstance(workspace, str) and workspace:
                            self._loop.call_soon_threadsafe(self.publish, workspace)
                    except (ValueError, TypeError, AttributeError):
                        pass
                channel.basic_consume(queue=queue, on_message_callback=receive, auto_ack=True)
                self._loop.call_soon_threadsafe(self.resync)
                while not self._stop.is_set():
                    connection.process_data_events(time_limit=0.5)
            except Exception:
                if not self._stop.is_set():
                    self._loop.call_soon_threadsafe(self.resync)
                    self._stop.wait(1)
            finally:
                if connection and connection.is_open:
                    try:
                        connection.close()
                    except Exception:
                        pass


async def event_frames(queue, authorized):
    yield 'retry: 3000\nevent: resync\ndata: {}\n\n'
    heartbeat = time.monotonic()
    while True:
        if not await authorized():
            yield 'event: session-ended\ndata: {}\n\n'
            return
        try:
            event = await asyncio.wait_for(queue.get(), 1)
        except TimeoutError:
            event = None
        if event:
            if not await authorized():
                yield 'event: session-ended\ndata: {}\n\n'
                return
            yield f'event: {"resync" if event == "resync" else "changed"}\ndata: {{}}\n\n'
        if time.monotonic() - heartbeat >= 10:
            yield ': heartbeat\n\n'
            heartbeat = time.monotonic()


def install(app, store, identity_for, cookie_name, *, amqp_url, subscriber=None):
    from .broker import RabbitBroker
    registry = ReadOnlyRegistry(store.root / 'realtime.db')
    subscriber = subscriber if subscriber is not None else GatewaySubscriber(amqp_url)

    @app.post('/hooks/microsoft')
    async def microsoft(request: Request):
        challenge = request.query_params.get('validationToken')
        if challenge is not None:
            if not challenge or len(challenge) > 4096:
                raise HTTPException(400, 'Invalid validation challenge.')
            return PlainTextResponse(challenge)
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid notification body.') from None
        values = payload.get('value') if isinstance(payload, dict) else None
        if not isinstance(values, list) or len(values) > 1000:
            raise HTTPException(400, 'Invalid notification batch.')
        try:
            if not amqp_url:
                raise HTTPException(503, 'Real-time processing is unavailable.')
            validated, enqueued = {}, set()
            for value in values:
                if not isinstance(value, dict):
                    continue
                sid, state = value.get('subscriptionId'), value.get('clientState')
                if not isinstance(sid, str) or not isinstance(state, str):
                    continue
                key = sid, state
                if key not in validated:
                    validated[key] = await asyncio.to_thread(registry.validate, sid, state)
                registered = validated[key]
                if not registered:
                    continue
                job = registered['workspace_id'], registered['kind'], registered['account_id']
                if job in enqueued:
                    continue
                try:
                    workspace = await asyncio.to_thread(store.workspace, registered['workspace_id'])
                except ValueError:
                    # Retired subscriptions may outlive workspace access.
                    continue
                if not workspace or not workspace.get('enabled', True):
                    continue
                def enqueue():
                    broker = RabbitBroker(amqp_url)
                    try:
                        broker.enqueue_unique(registered['kind'], registered['account_id'],
                                       reason='notification', workspace_id=registered['workspace_id'],
                                       coordination_root=Path(store.root) / 'shared-runtime')
                    finally:
                        broker.close()
                await asyncio.to_thread(enqueue)
                enqueued.add(job)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(503, 'Notification queue is unavailable.', headers={'Retry-After': '5'}) from None
        return JSONResponse({}, status_code=202)

    @app.get('/api/realtime/capabilities')
    def capabilities():
        return {'configured': bool(amqp_url)}

    @app.get('/api/realtime/events')
    async def events(request: Request, workspace: str):
        identity = request.state.identity
        if workspace != identity['workspace_id']:
            raise HTTPException(409, 'Workspace changed. Reload before continuing.')
        if not amqp_url:
            raise HTTPException(503, 'Real-time updates are not configured.')
        try:
            queue = subscriber.subscribe(workspace)
        except ValueError:
            raise HTTPException(503, 'Too many live connections for this workspace.', headers={'Retry-After': '5'}) from None
        token = request.cookies.get(cookie_name)
        original = tuple(identity.get(key) for key in ('role', 'user_id', 'bidder_id', 'workspace_id'))
        async def authorized():
            try:
                async with asyncio.timeout(1):
                    current = await asyncio.to_thread(identity_for, token)
                return bool(current and not current.get('must_change_password') and original == tuple(
                    current.get(key) for key in ('role', 'user_id', 'bidder_id', 'workspace_id')))
            except Exception:
                return False
        async def cleanup():
            subscriber.unsubscribe(workspace, queue)
        return EventResponse(event_frames(queue, authorized), cleanup)

    return subscriber
