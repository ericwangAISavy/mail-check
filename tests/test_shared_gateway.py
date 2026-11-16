import asyncio
import json
from unittest.mock import patch
import httpx
from mailcheck.web.gateway import create_gateway
from tests.test_workspace_gateway import system


def test_shared_gateway_forwards_server_selected_workspace(system,monkeypatch):
    _,store,pool=system
    app=create_gateway(store=store,pool=pool,start_workers=False,worker_mode='shared',amqp_url='amqp://guest:guest@localhost/')
    seen=[]
    original=httpx.AsyncClient
    async def worker(request):
        seen.append(request.headers['x-offerpath-workspace'])
        return httpx.Response(200,json={'ok':True})
    def client(**kwargs):
        return original(transport=httpx.MockTransport(worker),**kwargs)
    async def scenario():
        async with original(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch('mailcheck.web.gateway.httpx.AsyncClient',side_effect=client):
                result=await browser.get('/api/bootstrap',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
            assert result.status_code==200
    asyncio.run(scenario())
    assert seen==['legacy']


def test_shared_manual_check_is_enqueued_after_authorization(system):
    _,store,pool=system
    app=create_gateway(store=store,pool=pool,start_workers=False,worker_mode='shared',amqp_url='amqp://guest:guest@localhost/')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch('mailcheck.shared.dispatch.submit_manual',return_value={'ok':True,'queued':True}) as submit:
                result=await browser.post('/api/check',json={},headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
            assert result.status_code==200
            assert submit.call_args.args[2:5]==('legacy',store.owner_token,'manual-check')
    asyncio.run(scenario())


def test_interview_sync_alias_enqueues_calendar_work_without_body(system):
    _,store,pool=system
    app=create_gateway(store=store,pool=pool,start_workers=False,worker_mode='shared',amqp_url='amqp://test/')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://testserver') as browser:
            with patch('mailcheck.shared.dispatch.submit_manual',return_value={'ok':True,'queued':True}) as submit:
                result=await browser.post('/api/interviews/sync',headers={'cookie':f'offerpath_session={store.owner_token}','x-offerpath-workspace':'legacy'})
            assert result.status_code==200
            assert submit.call_args.args[4]=='manual-check'
            assert json.loads(submit.call_args.args[5])['mode']=='calendar'
    asyncio.run(scenario())
