import json
import threading
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest

from mailcheck import google_oauth as google


def test_disconnect_invalidates_pending_browser_authorizations(monkeypatch):
    values={}
    monkeypatch.setattr(google,'read_secret',lambda key:values.get(key))
    monkeypatch.setattr(google,'write_secret',lambda key,value:values.__setitem__(key,value))
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(200,json={
        'access_token':'synthetic-access','refresh_token':'synthetic-refresh'}))) as client:
        connection=google.GoogleConnection(client=client)
        connection.setup('client','secret','https://app.test/api/google/callback')
        pending=connection.begin()
        connection.disconnect()
        with pytest.raises(ValueError):
            connection.complete(pending['state'],'code',pending['cookie'])
    assert not json.loads(values['tokens']).get('refresh_token')


def test_disconnect_during_token_exchange_cannot_reconnect(monkeypatch):
    values={}
    monkeypatch.setattr(google,'read_secret',lambda key:values.get(key))
    monkeypatch.setattr(google,'write_secret',lambda key,value:values.__setitem__(key,value))
    started=threading.Event();release=threading.Event()
    def exchange(request):
        started.set();assert release.wait(2)
        return httpx.Response(200,json={'access_token':'synthetic-access','refresh_token':'synthetic-refresh'})
    with httpx.Client(transport=httpx.MockTransport(exchange)) as client:
        connection=google.GoogleConnection(client=client)
        connection.setup('client','secret','https://app.test/api/google/callback')
        pending=connection.begin()
        with ThreadPoolExecutor(max_workers=1) as executor:
            callback=executor.submit(connection.complete,pending['state'],'code',pending['cookie'])
            try:
                assert started.wait(2)
                connection.disconnect()
            finally:release.set()
            with pytest.raises(google.GoogleError):callback.result()
    assert not json.loads(values['tokens']).get('refresh_token')
