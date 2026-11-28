import asyncio

from mailcheck.web.admission import RequestAdmission


def test_stream_and_callback_have_separate_finite_budgets():
    async def scenario():
        held = asyncio.Event()
        release = asyncio.Event()
        statuses = []
        async def app(scope, receive, send):
            if scope['path'] == '/api/realtime/events':
                held.set()
                await release.wait()
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b''})
        async def receive():
            return {'type': 'http.request', 'body': b''}
        async def send(message):
            if message['type'] == 'http.response.start': statuses.append(message['status'])
        middleware = RequestAdmission(app, max_requests=1, max_streams=1, max_callbacks=1)
        def scope(path):
            return {'type':'http','path':path,'headers':[],'client':('127.0.0.1',12)}
        stream = asyncio.create_task(middleware(scope('/api/realtime/events'), receive, send))
        await held.wait()
        try:
            await middleware(scope('/login'), receive, send)
            await middleware(scope('/hooks/microsoft'), receive, send)
            await middleware(scope('/api/realtime/events'), receive, send)
            assert statuses == [200, 200, 503]
        finally:
            release.set()
            await stream
        assert middleware.stream_active == 0
    asyncio.run(scenario())


def test_actual_network_send_timeout_releases_stream_capacity():
    from fastapi import FastAPI
    from mailcheck.web.realtime_routes import EventResponse
    async def scenario():
        closed=asyncio.Event()
        app=FastAPI()
        @app.middleware('http')
        async def boundary(request,call_next):return await call_next(request)
        @app.get('/api/realtime/events')
        async def events():
            async def frames():
                while True:yield b'data: {}\n\n'
            async def cleanup():closed.set()
            return EventResponse(frames(),cleanup)
        async def receive():
            await asyncio.Future()
        async def send(message):
            if message['type']=='http.response.body':await asyncio.Future()
        middleware=RequestAdmission(app,max_streams=1,stream_send_timeout=.01)
        scope={'type':'http','method':'GET','path':'/api/realtime/events','raw_path':b'/api/realtime/events',
            'query_string':b'','headers':[],'scheme':'http','server':('localhost',80),'client':('127.0.0.1',12),'http_version':'1.1'}
        await asyncio.wait_for(middleware(scope,receive,send),.5)
        await asyncio.wait_for(closed.wait(),.5)
        assert middleware.stream_active==0
    asyncio.run(scenario())


def test_bidder_can_receive_only_safe_realtime_get_hints():
    from mailcheck.bidder_access import viewer_read_allowed
    assert viewer_read_allowed('/api/realtime/events','GET')
    assert viewer_read_allowed('/api/realtime/capabilities','GET')
    assert not viewer_read_allowed('/api/realtime/accounts/1','POST')
