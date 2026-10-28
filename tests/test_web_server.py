"""Platform-specific server startup avoids Windows Proactor teardown failures."""
from unittest.mock import MagicMock, patch
import pytest
from mailcheck.web.server import run


def test_windows_uses_selector_loop_for_serving():
    app=object()
    with patch('mailcheck.web.server.sys.platform','win32'), patch('mailcheck.web.server.asyncio.Runner') as runner, patch('mailcheck.web.server.uvicorn.Config') as config, patch('mailcheck.web.server.uvicorn.Server') as server:
        server.return_value.serve=MagicMock(return_value='serve-coroutine')
        run(app,host='0.0.0.0',port=52400,log_level='warning')
        import asyncio
        runner.assert_called_once_with(loop_factory=asyncio.SelectorEventLoop)
        config.assert_called_once_with(app,host='0.0.0.0',port=52400,log_level='warning',loop='asyncio')
        runner.return_value.__enter__.return_value.run.assert_called_once_with('serve-coroutine')


def test_other_platforms_keep_uvicorn_startup():
    app=object()
    with patch('mailcheck.web.server.sys.platform','linux'), patch('mailcheck.web.server.uvicorn.run') as start:
        run(app,host='127.0.0.1',port=52400,log_level='warning')
        start.assert_called_once_with(app,host='127.0.0.1',port=52400,log_level='warning')


def test_windows_does_not_hide_server_errors():
    with patch('mailcheck.web.server.sys.platform','win32'), patch('mailcheck.web.server.asyncio.Runner') as runner, patch('mailcheck.web.server.uvicorn.Server') as server:
        server.return_value.serve=MagicMock(return_value='serve-coroutine')
        runner.return_value.__enter__.return_value.run.side_effect=RuntimeError('startup failed')
        with pytest.raises(RuntimeError,match='startup failed'):
            run(object(),host='0.0.0.0',port=52400)


def test_windows_runner_actually_runs_on_selector_loop():
    import asyncio
    from types import SimpleNamespace
    loops=[]
    class Server:
        def __init__(self, config): pass
        async def serve(self):
            loops.append(asyncio.get_running_loop())
            await asyncio.sleep(0)
    # Replace this module's sys reference, not the host's global platform.
    with patch('mailcheck.web.server.sys',SimpleNamespace(platform='win32')), patch('mailcheck.web.server.uvicorn.Server',Server):
        run(object(),host='127.0.0.1',port=52400)
    assert len(loops)==1
    assert isinstance(loops[0],asyncio.SelectorEventLoop)
    assert loops[0].is_closed()
