import asyncio
import importlib
from pathlib import Path
import httpx
import pytest


def settings(tmp_path,role='core'):
    for name in (f'{role}_db_password',f'{role}_broker_password'):(tmp_path/name).write_text('x'*43)
    return importlib.import_module('mailcheck.services.settings').ServiceSettings.load(role,{'OFFERPATH_SECRET_DIR':str(tmp_path)})


def test_service_credentials_are_role_scoped_and_not_printable(tmp_path):
    value=settings(tmp_path)
    assert value.database=='offerpath_core'
    assert value.username=='core_app'
    assert 'x'*43 not in repr(value)
    with pytest.raises(ValueError):type(value).load('owner',{})


def test_missing_and_symlinked_secrets_fail_closed(tmp_path):
    module=importlib.import_module('mailcheck.services.settings')
    with pytest.raises(ValueError,match='secret'):module.ServiceSettings.load('mail',{'OFFERPATH_SECRET_DIR':str(tmp_path)})
    source=tmp_path/'source';source.write_text('x'*43)
    (tmp_path/'mail_db_password').symlink_to(source)
    with pytest.raises(ValueError,match='secret'):module.ServiceSettings.load('mail',{'OFFERPATH_SECRET_DIR':str(tmp_path)})


def test_liveness_and_readiness_do_not_claim_completed_business_migration(tmp_path):
    app_module=importlib.import_module('mailcheck.services.app')
    async def probe():return {'postgres':True,'rabbitmq':True}
    app=app_module.create_service_app(settings(tmp_path),probe)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            assert (await client.get('/health/live')).status_code==200
            state=await client.get('/health/dependencies')
            assert state.status_code==200
            assert state.json()['business_ready'] is False
            assert (await client.get('/api/bootstrap')).status_code==503
            assert (await client.post('/api/messages/1/send',json={})).status_code==503
    asyncio.run(scenario())


def test_dependency_error_is_sanitized_but_liveness_remains_available(tmp_path):
    app_module=importlib.import_module('mailcheck.services.app')
    async def probe():raise RuntimeError('private password xxxxxxxxx')
    app=app_module.create_service_app(settings(tmp_path),probe)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as client:
            response=await client.get('/health/dependencies')
            assert response.status_code==503
            assert 'private' not in response.text
            assert (await client.get('/health/live')).status_code==200
    asyncio.run(scenario())
