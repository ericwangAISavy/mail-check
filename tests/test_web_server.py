"""Windows uses native IOCP serving and keeps listener failures actionable."""
from unittest.mock import MagicMock, patch
import pytest
from mailcheck.web.server import run


def test_windows_uses_native_loop_for_serving():
    app=object()
    with patch('mailcheck.web.server.sys.platform','win32'), patch('mailcheck.web.server.asyncio.Runner') as runner, patch('mailcheck.web.server.asyncio.ProactorEventLoop', create=True) as native, patch('mailcheck.web.server.uvicorn.Config') as config, patch('mailcheck.web.server.uvicorn.Server') as server:
        server.return_value.serve=MagicMock(return_value='serve-coroutine')
        run(app,host='0.0.0.0',port=52400,log_level='warning')
        import asyncio
        runner.assert_called_once_with(loop_factory=native)
        wrapped=config.call_args.args[0]
        assert wrapped.app is app
        config.assert_called_once_with(wrapped,host='0.0.0.0',port=52400,log_level='warning',loop='asyncio',proxy_headers=True,forwarded_allow_ips='127.0.0.1,::1',server_header=False,limit_concurrency=256,timeout_keep_alive=5,timeout_graceful_shutdown=15)
        runner.return_value.__enter__.return_value.run.assert_called_once_with('serve-coroutine')


def test_other_platforms_keep_uvicorn_startup():
    app=object()
    with patch('mailcheck.web.server.sys.platform','linux'), patch('mailcheck.web.server.uvicorn.run') as start:
        run(app,host='127.0.0.1',port=52400,log_level='warning')
        wrapped=start.call_args.args[0]
        assert wrapped.app is app
        start.assert_called_once_with(wrapped,host='127.0.0.1',port=52400,log_level='warning',proxy_headers=True,forwarded_allow_ips='127.0.0.1,::1',server_header=False,limit_concurrency=256,timeout_keep_alive=5,timeout_graceful_shutdown=15)


def test_windows_does_not_hide_server_errors():
    with patch('mailcheck.web.server.sys.platform','win32'), patch('mailcheck.web.server.asyncio.ProactorEventLoop', create=True), patch('mailcheck.web.server.asyncio.Runner') as runner, patch('mailcheck.web.server.uvicorn.Server') as server:
        server.return_value.serve=MagicMock(return_value='serve-coroutine')
        runner.return_value.__enter__.return_value.run.side_effect=RuntimeError('startup failed')
        with pytest.raises(RuntimeError,match='startup failed'):
            run(object(),host='0.0.0.0',port=52400)


def test_windows_runner_uses_provided_native_factory_and_closes_loop():
    import asyncio
    from types import SimpleNamespace
    loops=[]
    class Server:
        def __init__(self, config): pass
        async def serve(self):
            loops.append(asyncio.get_running_loop())
            await asyncio.sleep(0)
    # Replace this module's sys reference, not the host's global platform.
    with patch('mailcheck.web.server.sys',SimpleNamespace(platform='win32')), patch('mailcheck.web.server.asyncio.ProactorEventLoop', asyncio.SelectorEventLoop, create=True), patch('mailcheck.web.server.uvicorn.Server',Server):
        run(object(),host='127.0.0.1',port=52400)
    assert len(loops)==1
    assert isinstance(loops[0],asyncio.SelectorEventLoop)
    assert loops[0].is_closed()


def test_fatal_listener_failure_requests_shutdown_and_is_not_hidden():
    import asyncio
    from types import SimpleNamespace
    error=OSError('listener invalid');error.winerror=10022
    loop=MagicMock()
    server=SimpleNamespace(should_exit=False)
    failures=[]
    from mailcheck.web.server import windows_exception_handler
    handler=windows_exception_handler(server,failures)
    context={'message':'Accept failed on a socket','exception':error,'socket':object()}
    handler(loop,context)
    assert server.should_exit
    assert failures==[error]
    loop.default_exception_handler.assert_called_once_with(context)


def test_unrelated_application_errors_are_never_suppressed():
    from types import SimpleNamespace
    from mailcheck.web.server import windows_exception_handler
    loop=MagicMock();server=SimpleNamespace(should_exit=False)
    context={'message':'Task exception was never retrieved','exception':RuntimeError('app failed')}
    windows_exception_handler(server,[])(loop,context)
    loop.default_exception_handler.assert_called_once_with(context)
    assert not server.should_exit


def test_expected_closed_connection_reset_does_not_kill_listener():
    from types import SimpleNamespace
    from mailcheck.web.server import windows_exception_handler
    class _ProactorBasePipeTransport:
        _sock=MagicMock()
        _server=MagicMock()
        _called_connection_lost=False
        def is_closing(self): return True
        def _call_connection_lost(self,exc): pass
    error=ConnectionResetError('peer reset');error.winerror=10054
    transport=_ProactorBasePipeTransport()
    handle=SimpleNamespace(_callback=transport._call_connection_lost)
    context={'exception':error,'handle':handle}
    loop=MagicMock();server=SimpleNamespace(should_exit=False)
    windows_exception_handler(server,[])(loop,context)
    loop.default_exception_handler.assert_not_called()
    assert transport._sock is None
    assert transport._server is None
    assert transport._called_connection_lost
    assert not server.should_exit


def test_reset_during_application_task_remains_visible():
    from types import SimpleNamespace
    from mailcheck.web.server import windows_exception_handler
    error=ConnectionResetError('app reset');error.winerror=10054
    context={'message':'Task exception was never retrieved','exception':error}
    loop=MagicMock();server=SimpleNamespace(should_exit=False)
    windows_exception_handler(server,[])(loop,context)
    loop.default_exception_handler.assert_called_once_with(context)
    assert not server.should_exit


def test_native_listener_failure_is_raised_after_serve_cleanup():
    import asyncio
    from types import SimpleNamespace
    error=OSError('listener invalid');error.winerror=10022
    cleaned=[]
    class Server:
        should_exit=False
        def __init__(self,config): pass
        async def serve(self):
            loop=asyncio.get_running_loop()
            loop.call_exception_handler({'message':'Accept failed on a socket','exception':error,'socket':object()})
            assert self.should_exit
            await asyncio.sleep(0)
            cleaned.append(True)
    with patch('mailcheck.web.server.sys',SimpleNamespace(platform='win32')), patch('mailcheck.web.server.asyncio.ProactorEventLoop',asyncio.SelectorEventLoop,create=True), patch('mailcheck.web.server.uvicorn.Server',Server):
        with pytest.raises(OSError,match='listener invalid'):
            run(object(),host='127.0.0.1',port=52400)
    assert cleaned==[True]


def test_origin_health_check_is_local_only_and_does_not_wait_for_application():
    import asyncio
    import httpx
    from mailcheck.web.server import LocalOriginHealth
    async def busy(scope,receive,send):
        raise AssertionError('Health check entered the busy application')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=LocalOriginHealth(busy),client=('127.0.0.1',40000)),base_url='http://127.0.0.1') as client:
            result=await client.get('/_internal/origin-health')
            assert result.status_code==204
            assert result.headers['x-offerpath-health']=='1'
    asyncio.run(scenario())


def test_remote_and_forwarded_health_checks_do_not_bypass_authentication():
    import asyncio
    import httpx
    from starlette.responses import Response
    from mailcheck.web.server import LocalOriginHealth
    async def app(scope,receive,send):await Response(status_code=403)(scope,receive,send)
    async def scenario():
        for peer,headers in [(('203.0.113.1',1),{}),(('127.0.0.1',1),{'x-forwarded-for':'203.0.113.1'})]:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=LocalOriginHealth(app),client=peer),base_url='http://localhost') as client:
                assert (await client.get('/_internal/origin-health',headers=headers)).status_code==403
    asyncio.run(scenario())
