"""Interrupted lease validation must not block every workspace's model queue."""
import asyncio
from types import SimpleNamespace

import pytest
from starlette.requests import Request
from fastapi import HTTPException

from mailcheck.control_store import ControlStore
from mailcheck.web.auth import AuthStore
from mailcheck.web.gateway import create_gateway


@pytest.mark.parametrize("interruption", ["cancel", "error", "revoked"])
def test_interrupted_worker_validation_returns_model_slot(tmp_path, monkeypatch, interruption):
    auth = AuthStore(lambda: tmp_path / 'auth.json')
    auth.change_password('admin', 'owner-password-123')
    store = ControlStore(tmp_path / 'control', auth)
    pool = SimpleNamespace(authenticate_worker=lambda token: 'legacy')
    app = create_gateway(store=store, pool=pool, start_workers=False)
    acquire = next(r.endpoint for r in app.routes if r.path == '/_internal/model/acquire')
    release = next(r.endpoint for r in app.routes if r.path == '/_internal/model/release')

    async def scenario():
        validating = asyncio.Event()
        blocker = asyncio.Event()
        first = True

        async def authenticate(function, *args):
            nonlocal first
            if first:
                first = False
                validating.set()
                if interruption == 'cancel':
                    await blocker.wait()
                elif interruption == 'error':
                    raise OSError('validation unavailable')
                else:
                    return None
            return function(*args)

        monkeypatch.setattr('mailcheck.web.gateway.asyncio.to_thread', authenticate)
        request = Request({'type': 'http', 'headers': [(b'x-offerpath-worker', b'worker')],
                           'state': {'worker': 'legacy'}})
        pending = asyncio.create_task(acquire(request))
        await validating.wait()
        if interruption == 'cancel':
            pending.cancel()
        expected = {'cancel': asyncio.CancelledError, 'error': OSError, 'revoked': HTTPException}[interruption]
        with pytest.raises(expected):
            await pending
        # A new request must immediately obtain the capacity abandoned above.
        lease = await asyncio.wait_for(acquire(request), timeout=.2)
        async def body(): return {'lease': lease['lease']}
        request.json = body
        await release(request)

    asyncio.run(scenario())
