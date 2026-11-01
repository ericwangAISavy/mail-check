from contextlib import nullcontext
from datetime import date
from unittest.mock import Mock, patch

import pytest

from mailcheck import pipeline
from mailcheck.config import Config
from mailcheck.sources.outlook import OutlookGraphSource, MAX_PAGES, SELECT
from mailcheck.sources.base import SourceError


def test_normal_checks_collect_read_and_unread_mail():
    source = Mock()
    source.fetch_unread.return_value = []
    account = Mock()
    with patch.object(pipeline, 'build_source', return_value=source):
        pipeline.fetch_account(account, date(2026, 10, 1), Config())
    source.fetch_unread.assert_called_once_with(date(2026, 10, 1), include_read=True)


def test_inclusive_outlook_fetch_keeps_bodies_and_follows_every_page():
    source = OutlookGraphSource(label='test', client_id='test')
    calls = []
    def get(client, url, params):
        calls.append(params)
        n = len(calls)
        data = {'value': [{'id': str(n), 'isRead': n % 2 == 0, 'body': {'content': 'complete body'}, 'webLink': 'https://outlook.live.com/mail/'}]}
        if n <= MAX_PAGES:
            data['@odata.nextLink'] = f'https://graph.microsoft.com/v1.0/page/{n}'
        return data
    with patch.object(source, '_client', return_value=nullcontext(None)), patch.object(source, '_get', side_effect=get):
        messages = list(source.fetch_unread(date(2026, 10, 1), include_read=True))
    assert len(messages) == MAX_PAGES + 1
    assert calls[0]['$select'] == SELECT
    assert 'isRead' not in calls[0]['$filter']
    assert all(m.text == 'complete body' and m.provider_url for m in messages)
    assert all(p is None for p in calls[1:])


def test_outlook_repeated_page_is_reported_instead_of_looping():
    source = OutlookGraphSource(label='test', client_id='test')
    data = {'value': [], '@odata.nextLink': 'https://graph.microsoft.com/v1.0/repeated'}
    with patch.object(source, '_client', return_value=nullcontext(None)), patch.object(source, '_get', return_value=data):
        with pytest.raises(SourceError, match='repeated'):
            list(source.fetch_unread(date(2026, 10, 1), include_read=True))


def test_inclusive_imap_fetch_does_not_filter_or_mark_seen():
    from mailcheck.sources.imap import IMAPSource
    source = IMAPSource(host='example.test', port=993, username='test', password='password')
    box = Mock()
    box.fetch.return_value = []
    with patch.object(source, '_open', return_value=box):
        assert list(source.fetch_unread(date(2026, 10, 1), include_read=True)) == []
    criteria = str(box.fetch.call_args.args[0]).upper()
    assert 'UNSEEN' not in criteria
    assert 'SEEN' not in criteria
    assert 'SINCE' in criteria
    assert box.fetch.call_args.kwargs['mark_seen'] is False
    box.logout.assert_called_once()
