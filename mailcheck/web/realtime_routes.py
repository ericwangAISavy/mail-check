"""Validated provider hints and bounded, authenticated browser change streams."""
from __future__ import annotations

import asyncio
import json
import re
import time
from collections import Counter

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from ..realtime.queue import Broker
from ..realtime.settings import Settings
from ..realtime.storage import Registry


async def event_frames(broker, cursor, authorized):
    yield 'retry: 3000\nevent: resync\ndata: {}\n\n'
    heartbeat = time.monotonic()
    while True:
        if not await authorized():
            yield 'event: session-ended\ndata: {}\n\n'
            return
        try:
            rows = await broker.read_changes(cursor, block_ms=1000)
        except Exception:
            yield 'event: degraded\ndata: {}\n\n'
            return
        for event_id, fields in rows:
            if not await authorized():
                yield 'event: session-ended\ndata: {}\n\n'
                return
            if not re.fullmatch(r'\d+-\d+', event_id):
                continue
            cursor = event_id
            # Topics are hints only; never relay arbitrary broker contents.
            yield f'id: {cursor}\nevent: changed\ndata: {{}}\n\n'
        if time.monotonic()-heartbeat >= 10:
            yield ': heartbeat\n\n'
            heartbeat = time.monotonic()


class EventResponse(StreamingResponse):
    def __init__(self, content, cleanup):
        super().__init__(content, media_type='text/event-stream', headers={
            'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})
        self.cleanup = cleanup

    async def __call__(self, scope, receive, send):
        async def bounded_send(message):
            await asyncio.wait_for(send(message), 10)
        try:
            await super().__call__(scope, receive, bounded_send)
        finally:
            await self.cleanup()


def install(app, store, identity_for, cookie_name):
    registry = Registry(store.root/'realtime.db')
    active = Counter()

    @app.post('/hooks/microsoft')
    async def microsoft(request: Request):
        challenge = request.query_params.get('validationToken')
        if challenge is not None:
            if not challenge or len(challenge)>4096:
                raise HTTPException(400, 'Invalid validation challenge.')
            return PlainTextResponse(challenge)
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            raise HTTPException(400, 'Invalid notification body.') from None
        values = payload.get('value') if isinstance(payload, dict) else None
        if not isinstance(values, list) or len(values)>1000:
            raise HTTPException(400, 'Invalid notification batch.')
        try:
            settings = Settings.from_env()
            if not settings.enabled:
                raise HTTPException(503, 'Real-time processing is unavailable.')
            validated = {}
            enqueued = set()
            for value in values:
                if not isinstance(value, dict):
                    continue
                sid, state = value.get('subscriptionId'), value.get('clientState')
                if not isinstance(sid, str) or not isinstance(state, str):
                    continue
                key = (sid, state)
                if key not in validated:
                    validated[key] = await asyncio.to_thread(registry.validate, sid, state)
                registered = validated[key]
                if registered is None:
                    continue
                job = (registered['workspace_id'], registered['kind'], registered['account_id'])
                if job in enqueued:
                    continue
                workspace = await asyncio.to_thread(store.workspace, registered['workspace_id'])
                if not workspace or not workspace.get('enabled', True):
                    continue
                broker = Broker(settings.redis_url, registered['workspace_id'])
                try:
                    await asyncio.to_thread(broker.enqueue, registered['kind'], registered['account_id'], reason='notification')
                    enqueued.add(job)
                finally:
                    broker.close()
        except HTTPException:
            raise
        except Exception:
            # Do not acknowledge undurable work or disclose proxy/provider credentials.
            raise HTTPException(503, 'Notification queue is unavailable.', headers={'Retry-After':'5'}) from None
        return JSONResponse({}, status_code=202)

    @app.get('/api/realtime/capabilities')
    def capabilities():
        try:
            return {'configured':Settings.from_env().enabled}
        except ValueError:
            return {'configured':False}

    @app.get('/api/realtime/events')
    async def events(request: Request, workspace: str):
        identity = request.state.identity
        if workspace != identity['workspace_id']:
            raise HTTPException(409, 'Workspace changed. Reload before continuing.')
        cursor = request.headers.get('last-event-id') or request.query_params.get('cursor', '')
        if cursor and (len(cursor)>48 or not re.fullmatch(r'\d+-\d+', cursor)):
            raise HTTPException(400, 'Invalid event cursor.')
        settings = Settings.from_env()
        if not settings.enabled:
            raise HTTPException(503, 'Real-time updates are not configured.')
        if active[workspace]>=8:
            raise HTTPException(503, 'Too many live connections for this workspace.', headers={'Retry-After':'5'})
        from redis.asyncio import Redis
        source = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=3)
        naming = Broker(settings.redis_url, workspace)
        stream_name = naming.changes_stream
        naming.close()
        active[workspace] += 1
        try:
            if not cursor:
                latest = await source.xrevrange(stream_name, count=1)
                cursor = latest[0][0] if latest else '0-0'
            else:
                await source.ping()
        except BaseException as exc:
            active[workspace] -= 1
            if not active[workspace]:
                del active[workspace]
            await source.aclose()
            if not isinstance(exc, Exception):
                raise
            raise HTTPException(503, 'Live updates are temporarily unavailable.') from None
        token = request.cookies.get(cookie_name)
        original = (identity.get('role'), identity.get('user_id'), identity.get('bidder_id'), workspace)
        async def authorized():
            try:
                async with asyncio.timeout(5):
                    current = await asyncio.to_thread(identity_for, token)
                return bool(current and not current.get('must_change_password') and original == (
                    current.get('role'), current.get('user_id'), current.get('bidder_id'), current['workspace_id']))
            except Exception:
                return False
        class Changes:
            async def read_changes(self, after, block_ms=1000):
                batches = await source.xread({stream_name:after}, count=100, block=block_ms)
                return [(eid, fields) for _, rows in batches for eid, fields in rows]
        async def cleanup():
            active[workspace] -= 1
            if not active[workspace]:
                del active[workspace]
            await source.aclose()
        return EventResponse(event_frames(Changes(), cursor, authorized), cleanup)
