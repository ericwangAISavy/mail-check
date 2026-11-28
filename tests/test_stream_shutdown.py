import asyncio
import logging
import socket

import httpx
import uvicorn
import pytest
from fastapi import FastAPI

from mailcheck.web import server as serving
from mailcheck.web.admission import RequestAdmission
from mailcheck.web.realtime_routes import EventResponse


def test_live_stream_shutdown_finishes_without_grace_timeout(caplog):
    async def scenario():
        cleaned=asyncio.Event()
        app=FastAPI()
        @app.middleware('http')
        async def boundary(request,call_next):
            return await call_next(request)
        @app.get('/api/realtime/events')
        async def events():
            async def frames():
                yield b'event: resync\ndata: {}\n\n'
                await asyncio.Future()
            async def cleanup():
                await asyncio.sleep(.01)
                cleaned.set()
            return EventResponse(frames(),cleanup)
        admission=RequestAdmission(app)
        listener=socket.socket()
        listener.bind(('127.0.0.1',0))
        listener.listen(16)
        port=listener.getsockname()[1]
        server_type=getattr(serving,'GracefulServer',uvicorn.Server)
        instance=server_type(uvicorn.Config(serving.LocalOriginHealth(admission),log_config=None,log_level='warning',
            timeout_graceful_shutdown=.15,timeout_keep_alive=1))
        task=asyncio.create_task(instance.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(3):
                while not instance.started:
                    await asyncio.sleep(.01)
            async with httpx.AsyncClient(timeout=2,trust_env=False) as client:
                async with client.stream('GET',f'http://127.0.0.1:{port}/api/realtime/events') as response:
                    body=response.aiter_raw()
                    assert b'resync' in await anext(body)
                    instance.should_exit=True
                    await asyncio.wait_for(task,3)
                    await asyncio.wait_for(cleaned.wait(),1)
                    assert admission.stream_active==0
        finally:
            instance.should_exit=True
            if not task.done():
                await asyncio.wait_for(task,3)
            listener.close()
    logger=logging.getLogger('uvicorn.error')
    logger.addHandler(caplog.handler)
    try:
        with caplog.at_level(logging.ERROR,logger='uvicorn.error'):
            asyncio.run(scenario())
    finally:
        logger.removeHandler(caplog.handler)
    assert 'timeout graceful shutdown exceeded' not in caplog.text
    assert 'Exception in ASGI application' not in caplog.text


def test_shutdown_closes_only_live_streams_and_rejects_new_streams():
    async def scenario():
        started=asyncio.Event()
        business_started=asyncio.Event()
        finish_business=asyncio.Event()
        cleaned=asyncio.Event()
        messages=[]
        async def app(scope,receive,send):
            await send({'type':'http.response.start','status':200,'headers':[]})
            try:
                if scope['path']=='/api/realtime/events':
                    started.set()
                    await asyncio.Future()
                else:
                    business_started.set()
                    await finish_business.wait()
                await send({'type':'http.response.body','body':b''})
            finally:
                if scope['path']=='/api/realtime/events':
                    cleaned.set()
        async def receive():
            await asyncio.Future()
        async def send(message):
            messages.append(message)
        def scope(path):
            return dict(type='http',path=path,headers=[],client=('127.0.0.1',1))
        admission=RequestAdmission(app)
        stream=asyncio.create_task(admission(scope('/api/realtime/events'),receive,send))
        business=asyncio.create_task(admission(scope('/api/check'),receive,send))
        await started.wait()
        await business_started.wait()
        try:
            admission.begin_shutdown()
            await asyncio.wait_for(stream,1)
            assert cleaned.is_set()
            assert not business.done()
            assert admission.stream_active==0 and admission.active==1
            await admission(scope('/api/realtime/events'),receive,send)
            assert messages[-2]['status']==503
        finally:
            finish_business.set()
            await business
            if not stream.done():
                stream.cancel()
                await asyncio.gather(stream,return_exceptions=True)
    asyncio.run(scenario())


def test_stream_shutdown_does_not_suppress_real_cleanup_errors():
    async def scenario():
        started=asyncio.Event()
        async def app(scope,receive,send):
            started.set()
            try:
                await asyncio.Future()
            finally:
                raise RuntimeError('cleanup failed')
        async def receive():await asyncio.Future()
        async def send(message):pass
        admission=RequestAdmission(app)
        task=asyncio.create_task(admission(dict(type='http',path='/api/realtime/events',headers=[]),receive,send))
        await started.wait()
        admission.begin_shutdown()
        with pytest.raises(RuntimeError,match='cleanup failed'):
            await task
        assert admission.stream_active==0
    asyncio.run(scenario())


def test_unrelated_stream_cancellation_is_not_hidden():
    async def scenario():
        started=asyncio.Event()
        async def app(scope,receive,send):
            started.set()
            await asyncio.Future()
        async def receive():await asyncio.Future()
        async def send(message):pass
        admission=RequestAdmission(app)
        task=asyncio.create_task(admission(dict(type='http',path='/api/realtime/events',headers=[]),receive,send))
        await started.wait()
        task.cancel('unrelated cancellation')
        with pytest.raises(asyncio.CancelledError,match='unrelated cancellation'):
            await task
        assert admission.stream_active==0
    asyncio.run(scenario())
