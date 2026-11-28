import asyncio
import time
from contextlib import suppress
from types import SimpleNamespace
from unittest.mock import patch
from mailcheck.workspace_workers import WorkerPool


def test_slow_workspace_discovery_does_not_stall_gateway_loop():
    def slow():
        time.sleep(.2)
        return []
    pool=WorkerPool(SimpleNamespace(enabled_workspaces=slow),'http://127.0.0.1:1',())
    async def scenario():
        real_sleep=asyncio.sleep
        async def tick(_):await real_sleep(.001)
        with patch('mailcheck.workspace_workers.asyncio',SimpleNamespace(sleep=tick,to_thread=asyncio.to_thread)):
            task=asyncio.create_task(pool.monitor())
            start=time.monotonic()
            try:
                await real_sleep(.03)
                assert time.monotonic()-start < .15, 'Workspace discovery blocked the HTTP serving loop'
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):await task
    asyncio.run(scenario())


def test_workspace_monitor_recovers_after_discovery_failure():
    calls=[]
    def discover():
        calls.append(True)
        if len(calls)==1:raise OSError('temporary disk error')
        return [{'id':'legacy'}]
    pool=WorkerPool(SimpleNamespace(enabled_workspaces=discover),'http://127.0.0.1:1',())
    async def scenario():
        real_sleep=asyncio.sleep
        async def tick(_):await real_sleep(.001)
        reached=asyncio.Event()
        loop=asyncio.get_running_loop()
        pool.ensure=lambda workspace:loop.call_soon_threadsafe(reached.set)
        with patch('mailcheck.workspace_workers.asyncio',SimpleNamespace(sleep=tick,to_thread=asyncio.to_thread)):
            task=asyncio.create_task(pool.monitor())
            try:
                await asyncio.wait_for(reached.wait(),.3)
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError,OSError):await task
    asyncio.run(scenario())
