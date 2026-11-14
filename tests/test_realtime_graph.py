"""Subscription lifecycle uses mocked Microsoft calls and hash-only routing."""
import time
from datetime import datetime, timezone

import httpx
import pytest

from mailcheck import db
from mailcheck.config import Config
from mailcheck.realtime.settings import Settings
from mailcheck.realtime.storage import Registry


def account():
    return db.Account(1, 'primary', 'person@example.com', '', 993, True, 'INBOX', True, 'outlook')


def test_create_renew_and_disable_subscription(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions
    registry = Registry(tmp_path / 'registry.db')
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        payload = kwargs.get('json', {})
        return {'id': 'sub-' + str(len(calls)), 'expirationDateTime': payload.get('expirationDateTime')}
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'private-token')
    graph = GraphSubscriptions(registry, 'workspace', 'https://example.com')
    monkeypatch.setattr(graph, '_request', request)
    graph.sync([account()], {1}, Config())
    rows = registry.list_workspace('workspace')
    assert {r['kind'] for r in rows} == {'mail', 'calendar'}
    assert {c[2]['json']['resource'] for c in calls} == {'me/messages', 'me/events'}
    assert all(c[2]['json']['notificationUrl'] == 'https://example.com/hooks/microsoft' for c in calls)
    for call, row in zip(calls, rows):
        state = call[2]['json']['clientState']
        assert registry.validate(row['subscription_id'], state)
        assert state not in (tmp_path / 'registry.db').read_bytes().decode('latin1')
        registry.update_expiry(row['subscription_id'], time.time() + 60)
    graph.sync([account()], {1}, Config())
    assert [c[0] for c in calls[2:]] == ['PATCH', 'PATCH']
    assert all('clientState' not in c[2]['json'] for c in calls[2:])
    graph.sync([account()], set(), Config())
    assert [c[0] for c in calls[4:]] == ['DELETE', 'DELETE']
    assert not registry.list_workspace('workspace')


def test_graph_never_connects_before_optin_or_without_public_url(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: pytest.fail('token before opt in'))
    registry = Registry(tmp_path / 'registry.db')
    GraphSubscriptions(registry, 'workspace', 'https://example.com').sync([account()], set(), Config())
    GraphSubscriptions(registry, 'workspace', '').sync([account()], {1}, Config())
    assert not registry.list_workspace('workspace')


def test_graph_failure_is_sanitized_and_workspace_scoped(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions, GraphError
    registry = Registry(tmp_path / 'registry.db')
    registry.save('other', 'other-workspace', 1, 'mail', 'state', time.time() + 60)
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'token')
    graph = GraphSubscriptions(registry, 'workspace', 'https://example.com')
    def failed(*a, **k):
        raise httpx.ConnectError('token secret provider response')
    monkeypatch.setattr(graph, '_request', failed)
    with pytest.raises(GraphError, match='Microsoft subscription unavailable') as exc:
        graph.sync([account()], {1}, Config())
    assert 'secret' not in str(exc.value)
    assert registry.list_workspace('other-workspace')


def test_missing_renewal_subscription_recreated_on_next_sync(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions, GraphError
    registry = Registry(tmp_path / 'registry.db')
    registry.save('gone', 'workspace', 1, 'mail', 'state', time.time() + 60,
                  callback_url='https://example.com/hooks/microsoft', resource='me/messages')
    registry.save('calendar', 'workspace', 1, 'calendar', 'state', time.time() + 86400,
                  callback_url='https://example.com/hooks/microsoft', resource='me/events')
    graph = GraphSubscriptions(registry, 'workspace', 'https://example.com')
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'private-token')
    calls = []
    def request(method, url, **kwargs):
        calls.append(method)
        if method == 'PATCH':
            response = httpx.Response(404, request=httpx.Request('PATCH', 'https://graph.microsoft.com/v1.0/subscriptions/gone'))
            response.raise_for_status()
        return {'id': 'replacement', 'expirationDateTime': kwargs['json']['expirationDateTime']}
    monkeypatch.setattr(graph, '_request', request)
    with pytest.raises(GraphError): graph.sync([account()], {1}, Config())
    assert not any(r['subscription_id'] == 'gone' for r in registry.list_workspace('workspace'))
    graph.sync([account()], {1}, Config())
    assert calls == ['PATCH', 'POST']
    assert any(r['subscription_id'] == 'replacement' for r in registry.list_workspace('workspace'))


def test_graph_throttling_defers_with_bounded_retry_after(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions, GraphError
    registry = Registry(tmp_path / 'registry.db')
    registry.save('mail', 'workspace', 1, 'mail', 'state', time.time() + 60,
                  callback_url='https://example.com/hooks/microsoft', resource='me/messages')
    registry.save('calendar', 'workspace', 1, 'calendar', 'state', time.time() + 86400,
                  callback_url='https://example.com/hooks/microsoft', resource='me/events')
    graph = GraphSubscriptions(registry, 'workspace', 'https://example.com')
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'private-token')
    calls = []
    def throttled(method, url, **kwargs):
        calls.append(method)
        response = httpx.Response(429, headers={'Retry-After': '36000'}, request=httpx.Request('PATCH', 'https://graph.microsoft.com/v1.0/subscriptions/mail'))
        response.raise_for_status()
    monkeypatch.setattr(graph, '_request', throttled)
    before = time.time()
    with pytest.raises(GraphError): graph.sync([account()], {1}, Config())
    assert before + 299 <= graph._deferred[(1, 'mail')] <= time.time() + 300
    with pytest.raises(GraphError): graph.sync([account()], {1}, Config())
    assert calls == ['PATCH']


def test_public_url_change_replaces_subscriptions_after_restart(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions
    path = tmp_path / 'registry.db'
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, kwargs))
        payload = kwargs.get('json', {})
        return {'id': 'sub-' + str(len(calls)), 'expirationDateTime': payload.get('expirationDateTime')}
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'private-token')
    old = GraphSubscriptions(Registry(path), 'workspace', 'https://old.example')
    monkeypatch.setattr(old, '_request', request)
    old.sync([account()], {1}, Config())
    previous = old.registry.list_workspace('workspace')
    replacement = GraphSubscriptions(Registry(path), 'workspace', 'https://new.example')
    monkeypatch.setattr(replacement, '_request', request)
    replacement.sync([account()], {1}, Config())
    assert [c[0] for c in calls] == ['POST', 'POST', 'DELETE', 'DELETE', 'POST', 'POST']
    assert all(c[1]['json']['notificationUrl'] == 'https://new.example/hooks/microsoft' for c in calls[4:])
    current = replacement.registry.list_workspace('workspace')
    assert all(r['callback_url'] == 'https://new.example/hooks/microsoft' for r in current)
    assert {r['subscription_id'] for r in current}.isdisjoint(r['subscription_id'] for r in previous)


def test_registry_migrates_old_database_and_preserves_callback_validation(tmp_path):
    import hashlib
    import sqlite3
    path = tmp_path / 'old-registry.db'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE realtime_subscriptions (
            subscription_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
            account_id INTEGER NOT NULL,kind TEXT NOT NULL,
            client_state_hash TEXT NOT NULL,expires REAL NOT NULL)''')
        conn.execute('INSERT INTO realtime_subscriptions VALUES(?,?,?,?,?,?)',
                     ('old', 'workspace', 1, 'mail', hashlib.sha256(b'state').hexdigest(), time.time() + 60))
    registry = Registry(path)
    assert registry.validate('old', 'state')['callback_url'] == ''
    assert registry.list_workspace('workspace')[0]['callback_url'] == ''
    registry.save('new', 'workspace', 1, 'calendar', 'new-state', time.time() + 60,
                  callback_url='https://new.example/hooks/microsoft')
    assert registry.validate('new', 'new-state')['callback_url'] == 'https://new.example/hooks/microsoft'
    # Opening an already migrated registry is idempotent.
    assert len(Registry(path).list_workspace('workspace')) == 2


@pytest.mark.parametrize('previous_callback', ['https://old.example/hooks/microsoft', 'https://new.example/hooks/microsoft'])
def test_failed_old_callback_deletion_never_renews_old_destination(tmp_path, monkeypatch, previous_callback):
    from mailcheck.realtime.graph import GraphSubscriptions, GraphError
    registry = Registry(tmp_path / 'registry.db')
    for kind in ('mail', 'calendar'):
        registry.save(kind, 'workspace', 1, kind, 'state', time.time() + 60,
                      callback_url=previous_callback)
    graph = GraphSubscriptions(registry, 'workspace', 'https://new.example')
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'private-token')
    methods = []
    def unavailable(method, *a, **k):
        methods.append(method)
        raise httpx.ConnectError('provider unavailable')
    monkeypatch.setattr(graph, '_request', unavailable)
    with pytest.raises(GraphError): graph.sync([account()], {1}, Config())
    assert methods == ['DELETE', 'DELETE']
    assert all(r['callback_url'] == previous_callback for r in registry.list_workspace('workspace'))


def test_inbox_only_subscription_upgrade_covers_junk_mail(tmp_path, monkeypatch):
    from mailcheck.realtime.graph import GraphSubscriptions
    registry = Registry(tmp_path / 'registry.db')
    registry.save('old-inbox', 'workspace', 1, 'mail', 'state', time.time() + 86400,
                  callback_url='https://example.com/hooks/microsoft')
    graph = GraphSubscriptions(registry, 'workspace', 'https://example.com')
    monkeypatch.setattr('mailcheck.realtime.graph.acquire_token', lambda *a, **k: 'token')
    calls = []
    def request(method, path, **kwargs):
        calls.append((method, path, kwargs.get('json', {})))
        return {'id': 'new-' + str(len(calls)), 'expirationDateTime': kwargs.get('json', {}).get('expirationDateTime')}
    monkeypatch.setattr(graph, '_request', request)
    graph.sync([account()], {1}, Config())
    assert calls[0][:2] == ('DELETE', 'subscriptions/old-inbox')
    assert {call[2]['resource'] for call in calls if call[0] == 'POST'} == {'me/messages', 'me/events'}
    rows = registry.list_workspace('workspace')
    assert {row['resource'] for row in rows} == {'me/messages', 'me/events'}
    count = len(calls)
    graph.sync([account()], {1}, Config())
    assert len(calls) == count


def test_registry_upgrade_defaults_legacy_resource_to_unknown(tmp_path):
    import sqlite3
    path = tmp_path / 'old.db'
    with sqlite3.connect(path) as conn:
        conn.execute('''CREATE TABLE realtime_subscriptions (
            subscription_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
            account_id INTEGER NOT NULL,kind TEXT NOT NULL,
            client_state_hash TEXT NOT NULL,expires REAL NOT NULL,
            callback_url TEXT NOT NULL DEFAULT '')''')
        conn.execute("INSERT INTO realtime_subscriptions VALUES('legacy','workspace',1,'mail','hash',99999999999,'https://example.com/hooks/microsoft')")
    assert Registry(path).list_workspace('workspace')[0]['resource'] == ''
