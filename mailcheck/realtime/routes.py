"""Workspace-authenticated account opt-in and safe operational status."""
from __future__ import annotations

import time

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from .. import db
from . import storage
from .settings import Settings


class AccountOptIn(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool


def install(app):
    def snapshot():
        try:
            settings = Settings.from_env()
        except ValueError:
            settings = Settings()
        runtime = getattr(app.state, 'realtime', None)
        subscriptions = []
        if runtime:
            subscriptions = runtime.registry.list_workspace(runtime.workspace_id)
        callback_url = settings.public_url + '/hooks/microsoft' if settings.public_url else ''
        live = {(s['account_id'], s['kind']) for s in subscriptions if callback_url
                and s['expires'] > time.time() and s.get('callback_url', '') == callback_url
                and s.get('resource', '') == runtime.graph.resources.get(s['kind'])}
        with db.session() as conn:
            records = storage.status(conn)
            providers = {a.id: a.provider for a in db.list_accounts(conn)}
        for row in records:
            row['enabled'] = bool(row['enabled'])
            if runtime and row['enabled'] and runtime.queue_error and not row['last_error']:
                row['last_error'] = runtime.queue_error
            row['subscription_status'] = ('disabled' if not row['enabled'] else
                'subscribed' if all((row['account_id'], k) in live for k in ('mail', 'calendar')) else
                'polling' if providers.get(row['account_id']) != 'outlook' or not settings.public_url else 'pending')
            row['subscription_error'] = (runtime.subscription_error if runtime and row['enabled']
                                         and providers.get(row['account_id']) == 'outlook' else '')
        return {'configured': settings.enabled, 'public_ready': bool(settings.public_url), 'accounts': records}

    @app.get('/api/realtime/accounts')
    def accounts():
        return snapshot()

    @app.get('/api/realtime/accounts/{account_id}')
    def account(account_id: int):
        state = snapshot()
        row = next((r for r in state['accounts'] if r['account_id'] == account_id), None)
        if row is None:
            raise HTTPException(404, 'Account does not exist.')
        return {**row, 'configured': state['configured'], 'public_ready': state['public_ready']}

    @app.post('/api/realtime/accounts/{account_id}')
    def set_account(account_id: int, body: AccountOptIn):
        state = snapshot()
        if not any(row['account_id'] == account_id for row in state['accounts']):
            raise HTTPException(404, 'Account does not exist.')
        if body.enabled and not state['configured']:
            raise HTTPException(503, 'Real-time processing is not configured.')
        with db.session() as conn:
            storage.set_account(conn, account_id, body.enabled)
        runtime = getattr(app.state, 'realtime', None)
        if runtime:
            runtime.wake()
        return account(account_id)
