"""Bounded Microsoft subscription lifecycle; callback secrets are never persisted raw."""
from __future__ import annotations

import secrets
import time
import math
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from ..outlook_auth import acquire_token, CALENDAR_SCOPES


class GraphError(RuntimeError):
    pass


class GraphSubscriptions:
    # Mail collection includes Inbox and Junk Email. Mailbox-wide hints cover
    # both; the collector still decides which folders and messages to import.
    resources = {'mail': 'me/messages', 'calendar': 'me/events'}

    def __init__(self, registry, workspace_id: str, public_url: str):
        self.registry, self.workspace_id = registry, workspace_id
        self.public_url = public_url.rstrip('/')
        self._deferred = {}

    def _request(self, method, path, *, token, **kwargs):
        # Paths are built locally; provider response URLs are never followed.
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False) as client:
            response = client.request(method, 'https://graph.microsoft.com/v1.0/' + path,
                                      headers={'Authorization': 'Bearer ' + token}, **kwargs)
            if method == 'DELETE' and response.status_code == 404:
                return {}
            response.raise_for_status()
            return response.json() if response.content else {}

    def _token(self, account, cfg, kind):
        return acquire_token(account.label, cfg.outlook.client_id,
                             **({'scopes': CALENDAR_SCOPES} if kind == 'calendar' else {}))

    def sync(self, accounts, enabled_ids, cfg):
        accounts = {a.id: a for a in accounts}
        existing = self.registry.list_workspace(self.workspace_id)
        callback_url = self.public_url + '/hooks/microsoft' if self.public_url else ''
        failures = False
        for row in existing:
            account = accounts.get(row['account_id'])
            wanted = account and account.enabled and account.provider == 'outlook' and account.id in enabled_ids
            if (wanted and self.public_url and row['expires'] > time.time()
                    and row.get('callback_url', '') == callback_url
                    and row.get('resource', '') == self.resources.get(row['kind'])):
                continue
            try:
                if account and account.provider == 'outlook':
                    self._request('DELETE', 'subscriptions/' + quote(row['subscription_id'], safe=''),
                                  token=self._token(account, cfg, row['kind']))
                self.registry.delete(row['subscription_id'])
            except Exception:
                failures = True
        if not self.public_url:
            if failures:
                raise GraphError('Microsoft subscription unavailable; polling continues.') from None
            return
        existing = {(r['account_id'], r['kind']): r for r in self.registry.list_workspace(self.workspace_id)}
        for account in accounts.values():
            if not account.enabled or account.id not in enabled_ids or account.provider != 'outlook':
                continue
            for kind in ('mail', 'calendar'):
                key = (account.id, kind)
                if self._deferred.get(key, 0) > time.time():
                    failures = True
                    continue
                row = existing.get((account.id, kind))
                # Failed deletion must not silently renew the old destination.
                if row and (row.get('callback_url', '') != callback_url
                            or row.get('resource', '') != self.resources[kind]):
                    failures = True
                    continue
                if row and row['expires'] > time.time() + 12 * 3600:
                    continue
                expiry = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace('+00:00', 'Z')
                try:
                    token = self._token(account, cfg, kind)
                    if row:
                        reply = self._request('PATCH', 'subscriptions/' + quote(row['subscription_id'], safe=''),
                                              token=token, json={'expirationDateTime': expiry})
                        self.registry.update_expiry(row['subscription_id'], reply.get('expirationDateTime', expiry))
                    else:
                        state = secrets.token_urlsafe(32)
                        reply = self._request('POST', 'subscriptions', token=token, json={
                            'changeType': 'created' if kind == 'mail' else 'created,updated,deleted',
                            'notificationUrl': callback_url,
                            'resource': self.resources[kind],
                            'expirationDateTime': expiry, 'clientState': state})
                        self.registry.save(reply['id'], self.workspace_id, account.id, kind, state,
                                           reply.get('expirationDateTime', expiry), callback_url=callback_url,
                                           resource=self.resources[kind])
                except Exception as exc:
                    if isinstance(exc, httpx.HTTPStatusError):
                        if row and exc.response.status_code in {404, 410}:
                            self.registry.delete(row['subscription_id'])
                        if exc.response.status_code == 429:
                            try:
                                delay = float(exc.response.headers.get('Retry-After', '60'))
                                delay = min(300, max(1, delay)) if math.isfinite(delay) else 60
                            except ValueError:
                                delay = 60
                            self._deferred[key] = time.time() + delay
                    failures = True
        if failures:
            raise GraphError('Microsoft subscription unavailable; polling continues.') from None
