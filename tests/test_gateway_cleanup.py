import asyncio
from unittest.mock import Mock
from mailcheck.web.gateway import create_gateway
from tests.test_workspace_gateway import system


def test_failed_background_task_does_not_skip_worker_cleanup(system):
    _,store,pool=system
    async def failed():raise RuntimeError('monitor failed unexpectedly')
    pool.monitor=failed;pool.close=Mock()
    app=create_gateway(store=store,pool=pool,start_workers=True)
    async def scenario():
        async with app.router.lifespan_context(app):await asyncio.sleep(0)
    asyncio.run(scenario())
    pool.close.assert_called_once()
