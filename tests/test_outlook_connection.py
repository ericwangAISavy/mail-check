"""Connection checks use granted mailbox permissions, without profile access."""

from unittest.mock import patch

import httpx
import pytest

from mailcheck.sources.base import SourceError
from mailcheck.sources.outlook import MESSAGES_URL, OutlookGraphSource


def graph_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize('messages', [[], [{'id': 'synthetic-message'}]])
def test_connection_succeeds_with_mail_permission_but_no_profile_permission(messages):
    requests = []

    def graph(request):
        requests.append(request)
        if request.url.path == '/v1.0/me':
            return httpx.Response(403, json={'error': {'code': 'Authorization_RequestDenied'}})
        assert str(request.url.copy_with(query=None)) == MESSAGES_URL
        assert request.method == 'GET'
        assert request.url.params['$select'] == 'id'
        assert request.url.params['$top'] == '1'
        return httpx.Response(200, json={'value': messages})

    source = OutlookGraphSource(label='synthetic', client_id='synthetic')
    with patch.object(source, '_client', return_value=graph_client(graph)):
        source.test()
    assert len(requests) == 1


@pytest.mark.parametrize('status', [401, 403])
def test_connection_keeps_real_mail_permission_failures_actionable(status):
    source = OutlookGraphSource(label='synthetic', client_id='synthetic')
    with patch.object(source, '_client', return_value=graph_client(lambda request: httpx.Response(status))):
        with pytest.raises(SourceError, match='Reconnect the account'):
            source.test()


@pytest.mark.parametrize('payload', [{}, {'value': None}, {'value': {}}, []])
def test_connection_rejects_invalid_mailbox_responses(payload):
    source = OutlookGraphSource(label='synthetic', client_id='synthetic')
    with patch.object(source, '_client', return_value=graph_client(lambda request: httpx.Response(200, json=payload))):
        with pytest.raises(SourceError, match='invalid mailbox response'):
            source.test()
