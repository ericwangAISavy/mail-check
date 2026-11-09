"""Ordinary authentication backlog must not starve worker heartbeat validation."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import httpx

from tests.test_workspace_gateway import system


def test_internal_heartbeat_does_not_wait_for_browser_executor(system):
    app, _, _ = system

    async def scenario():
        loop = asyncio.get_running_loop()
        loop.set_default_executor(ThreadPoolExecutor(max_workers=1))
        entered = threading.Event()
        release = threading.Event()
        def ordinary_work():
            entered.set()
            release.wait(5)
        busy = asyncio.create_task(asyncio.to_thread(ordinary_work))
        while not entered.is_set():
            await asyncio.sleep(.001)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
                response = await asyncio.wait_for(client.get('/_internal/ping', headers={
                    'x-offerpath-worker': 'internal-secret'}), timeout=.5)
            assert response.status_code == 200
        finally:
            release.set()
            await busy

    asyncio.run(scenario())
