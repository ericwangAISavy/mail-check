import errno
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient
from starlette.staticfiles import StaticFiles
from tests.test_workspace_gateway import system


@pytest.mark.parametrize('path',['/assets/index.js:267:43834','/assets/index.js%3A62%3A4323','/static/app.js:1:2'])
def test_stack_trace_asset_urls_return_404_on_windows(system,path):
    app,_,_=system
    original=StaticFiles.lookup_path
    def windows_lookup(self,path):
        if ':' in path:
            error=OSError(errno.EINVAL,'Invalid filename');error.winerror=123
            raise error
        return original(self,path)
    with patch.object(StaticFiles,'lookup_path',windows_lookup),TestClient(app) as client:
        response=client.get(path)
        assert response.status_code==404
        assert response.headers['cache-control']=='no-store'
        assert client.get('/static/app.js').status_code==200


@pytest.mark.parametrize('code',[123,161,206])
def test_platform_invalid_path_errors_return_not_found(tmp_path,code):
    import asyncio
    from mailcheck.web.static_files import PortableStaticFiles
    from fastapi import FastAPI
    files=PortableStaticFiles(directory=tmp_path)
    app=FastAPI();app.mount("/",files)
    error=OSError(errno.EINVAL,'Invalid path');error.winerror=code
    async def scenario():
        with patch.object(files,'lookup_path',side_effect=error):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                assert (await client.get('/file.js')).status_code==404
    asyncio.run(scenario())


def test_real_io_errors_are_not_hidden(tmp_path):
    import asyncio
    from mailcheck.web.static_files import PortableStaticFiles
    from fastapi import FastAPI
    files=PortableStaticFiles(directory=tmp_path)
    app=FastAPI();app.mount("/",files)
    async def scenario():
        with patch.object(files,'lookup_path',side_effect=OSError(errno.EIO,'disk I/O failed')):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
                with pytest.raises(OSError,match='disk I/O failed'):await client.get('/file.js')
    asyncio.run(scenario())


def test_valid_assets_keep_cache_head_and_range_behavior(system):
    app,_,_=system
    with TestClient(app) as client:
        response=client.get('/assets/startup-recovery-v1.js')
        assert response.status_code==200
        assert 'immutable' in response.headers['cache-control']
        assert client.head('/assets/startup-recovery-v1.js').content==b''
        part=client.get('/assets/startup-recovery-v1.js',headers={'range':'bytes=0-9'})
        assert part.status_code==206
        assert part.content==response.content[:10]
        cached=client.get('/assets/startup-recovery-v1.js',headers={'if-none-match':response.headers['etag']})
        assert cached.status_code==304
