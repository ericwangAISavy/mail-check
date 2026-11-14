import asyncio
import time
from unittest.mock import patch
import pytest

from fastapi.testclient import TestClient

from mailcheck.realtime.storage import Registry
from tests.test_workspace_gateway import system, login


def test_graph_challenge_is_public_but_other_apis_are_private(system, monkeypatch):
    app, store, pool = system
    with TestClient(app) as browser:
        response = browser.post('/hooks/microsoft?validationToken=challenge%2B123')
        assert response.status_code == 200
        assert response.text == 'challenge+123'
        assert response.headers['content-type'].startswith('text/plain')
        assert browser.get('/api/realtime/capabilities').status_code == 401


def test_public_callback_configuration_requires_a_root_url(monkeypatch):
    import pytest
    from mailcheck.realtime.settings import Settings
    monkeypatch.setenv('OFFERPATH_PUBLIC_URL','https://app.example.test/unknown-prefix')
    with pytest.raises(ValueError):Settings.from_env()


@pytest.mark.parametrize('resource', ['untrusted/path', "me/mailFolders('junkemail')/messages/new-message"])
def test_callback_uses_registered_workspace_and_only_acks_enqueued_work(system, monkeypatch, resource):
    app, store, pool = system
    monkeypatch.setenv('OFFERPATH_REDIS_URL', 'redis://127.0.0.1:56379/0')
    registry = Registry(store.root/'realtime.db')
    registry.save('subscription', 'legacy', 12, 'mail', 'unpredictable-state', time.time()+3600)
    body = {'value':[{'subscriptionId':'subscription','clientState':'unpredictable-state',
                      'resource':resource,'workspace_id':'another-workspace'}]}
    body['value'] *= 20
    with TestClient(app) as browser, patch('mailcheck.web.realtime_routes.Broker') as broker:
        response = browser.post('/hooks/microsoft', json=body)
        assert response.status_code == 202
        assert broker.call_args.args[1] == 'legacy'
        broker.return_value.enqueue.assert_called_once_with('mail', 12, reason='notification')
        broker.return_value.enqueue.side_effect = ConnectionError('broker unavailable')
        assert browser.post('/hooks/microsoft', json=body).status_code == 503
        body['value'][0]['clientState'] = 'forged'
        broker.return_value.enqueue.reset_mock()
        assert browser.post('/hooks/microsoft', json=body).status_code == 202
        broker.return_value.enqueue.assert_not_called()


def test_sse_requires_current_workspace_and_valid_cursor(system, monkeypatch):
    app, _, _ = system
    monkeypatch.setenv('OFFERPATH_REDIS_URL', 'redis://127.0.0.1:56379/0')
    with TestClient(app) as browser:
        login(browser)
        assert browser.get('/api/realtime/events?workspace=other').status_code == 409
        assert browser.get('/api/realtime/events?workspace=legacy', headers={'Last-Event-ID':'bad\nvalue'}).status_code == 400


def test_stream_stops_when_session_is_revoked():
    from mailcheck.web.realtime_routes import event_frames
    class Broker:
        async def read_changes(self, cursor, block_ms=1000):
            return [('2-0', {'topics':'["mail"]'})]
    async def scenario():
        active = True
        async def authorized():return active
        stream = event_frames(Broker(), '1-0', authorized)
        assert 'resync' in await anext(stream)
        active = False
        assert 'session-ended' in await anext(stream)
        try:await anext(stream)
        except StopAsyncIteration:pass
        else:raise AssertionError('revoked event stream must close')
    asyncio.run(scenario())


def test_revocation_during_redis_read_prevents_changed_frames():
    from mailcheck.web.realtime_routes import event_frames
    async def scenario():
        active=True
        class Changes:
            async def read_changes(self, cursor, block_ms=1000):
                nonlocal active
                active=False
                return [('2-0', {})]
        async def authorized():return active
        frames=event_frames(Changes(),'1-0',authorized)
        await anext(frames)
        assert 'session-ended' in await anext(frames)
        await frames.aclose()
    asyncio.run(scenario())


def test_concurrent_sse_setup_reserves_workspace_capacity_before_redis_io(system, monkeypatch):
    from starlette.requests import Request
    from fastapi import HTTPException
    app, _, _=system
    monkeypatch.setenv('OFFERPATH_REDIS_URL','redis://127.0.0.1:56379/0')
    endpoint=next(r.endpoint for r in app.routes if getattr(r,'path',None)=='/api/realtime/events')
    class Source:
        async def ping(self):await asyncio.sleep(.02)
        async def aclose(self):pass
    async def scenario():
        def invoke():
            request=Request({'type':'http','method':'GET','path':'/api/realtime/events',
                'headers':[(b'last-event-id',b'1-0')], 'query_string':b''})
            request.state.identity={'workspace_id':'legacy','role':'admin','user_id':1}
            return endpoint(request,workspace='legacy')
        with patch('redis.asyncio.Redis.from_url',side_effect=lambda *a,**k:Source()):
            results=await asyncio.gather(*(invoke() for _ in range(9)),return_exceptions=True)
        responses=[r for r in results if not isinstance(r,Exception)]
        try:
            assert len(responses)==8
            assert isinstance(results[-1],HTTPException) and results[-1].status_code==503
        finally:
            for response in responses:await response.cleanup()
    asyncio.run(scenario())
