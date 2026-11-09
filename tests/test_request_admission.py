"""Active work remains bounded without rejecting idle keep-alive traffic."""
import asyncio
import socket

import pytest
import uvicorn

from mailcheck.web.admission import RequestAdmission


async def response(send, status=200):
    await send({'type': 'http.response.start', 'status': status,
                'headers': [(b'content-length', b'2')]})
    await send({'type': 'http.response.body', 'body': b'ok'})


def test_active_budget_control_reservation_and_cancellation_cleanup():
    async def check():
        entered = asyncio.Event()
        blocked = asyncio.Event()
        async def app(scope, receive, send):
            if scope['path'] == '/slow':
                entered.set()
                await blocked.wait()
            await response(send)
        admission = RequestAdmission(app, max_requests=1, max_control_requests=1)
        async def invoke(path, *, peer='127.0.0.1', token=b'secret'):
            messages=[]
            async def send(message): messages.append(message)
            await admission({'type': 'http', 'path': path, 'client': (peer, 123),
                             'headers': [(b'x-offerpath-worker', token)]}, None, send)
            return messages[0]['status']
        task=asyncio.create_task(invoke('/slow'))
        await entered.wait()
        assert await invoke('/ordinary') == 503
        assert await invoke('/_internal/ping') == 200
        assert await invoke('/_internal/model/release') == 200
        assert await invoke('/_internal/model/acquire') == 503
        assert await invoke('/_internal/ping', peer='192.0.2.1') == 503
        assert await invoke('/_internal/ping', token=b'') == 503
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert admission.active == 0
        assert await invoke('/ordinary') == 200
    asyncio.run(check())


def test_control_lane_is_bounded_and_does_not_bypass_application_auth():
    async def check():
        entered=asyncio.Event()
        release=asyncio.Event()
        async def app(scope, receive, send):
            entered.set()
            await release.wait()
            await response(send, 403)
        admission=RequestAdmission(app,max_control_requests=1)
        async def invoke():
            messages=[]
            async def send(message): messages.append(message)
            await admission({'type':'http','path':'/_internal/model/release',
                             'client':('127.0.0.1',1),
                             'headers':[(b'x-offerpath-worker',b'wrong-token')]},None,send)
            return messages[0]['status']
        first=asyncio.create_task(invoke())
        await entered.wait()
        assert await invoke() == 503
        release.set()
        assert await first == 403
        assert admission.control_active == 0
    asyncio.run(check())


def test_real_server_idle_connections_and_active_backpressure():
    async def check():
        sock=socket.socket()
        sock.bind(('127.0.0.1',0));sock.listen();sock.setblocking(False)
        port=sock.getsockname()[1]
        release=asyncio.Event()
        async def app(scope, receive, send):
            if scope['path']=='/slow': await release.wait()
            await response(send)
        admission=RequestAdmission(app)
        server=uvicorn.Server(uvicorn.Config(admission, limit_concurrency=256,
            timeout_keep_alive=5, lifespan='off',log_level='error'))
        serving=asyncio.create_task(server.serve(sockets=[sock]))
        connections=[]
        async def connect(path='/', internal=False):
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            connections.append(writer)
            token=b'X-Offerpath-Worker: secret\r\n' if internal else b''
            writer.write(b'GET '+path.encode()+b' HTTP/1.1\r\nHost: localhost\r\n'+token+b'\r\n')
            await writer.drain()
            return reader
        async def read(reader):
            headers=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),2)
            size=int(next(line.split(b':',1)[1] for line in headers.split(b'\r\n')
                          if line.lower().startswith(b'content-length:')))
            await reader.readexactly(size)
            return int(headers.split(b' ')[1])
        try:
            while not server.started: await asyncio.sleep(.001)
            for _ in range(63): assert await read(await connect()) == 200
            assert await read(await connect()) == 200
            pending=[await connect('/slow') for _ in range(64)]
            async def wait_full():
                while admission.active != 64: await asyncio.sleep(.001)
            await asyncio.wait_for(wait_full(),2)
            assert await read(await connect()) == 503
            assert await read(await connect('/_internal/ping',True)) == 200
            assert await read(await connect('/_internal/model/release',True)) == 200
            release.set()
            assert all(status==200 for status in await asyncio.gather(*(read(r) for r in pending)))
            assert await read(await connect()) == 200
        finally:
            release.set()
            for writer in connections: writer.close()
            await asyncio.gather(*(writer.wait_closed() for writer in connections))
            server.should_exit=True
            await serving
    asyncio.run(check())
