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
        if "junkemail" in url:return {"value":[]}
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
    assert all(p is None for p in calls[1:-1])
    assert calls[-1]["$filter"] == calls[0]["$filter"]


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
    box.folder.list.return_value = []
    box.fetch.return_value = []
    with patch.object(source, '_open', return_value=box):
        assert list(source.fetch_unread(date(2026, 10, 1), include_read=True)) == []
    criteria = str(box.fetch.call_args.args[0]).upper()
    assert 'UNSEEN' not in criteria
    assert 'SEEN' not in criteria
    assert 'SINCE' in criteria
    assert box.fetch.call_args.kwargs['mark_seen'] is False
    box.logout.assert_called_once()


def test_outlook_incremental_filter_keeps_the_full_received_timestamp():
    from datetime import datetime
    source = OutlookGraphSource(label='test', client_id='test')
    with patch.object(source, '_client', return_value=nullcontext(None)), patch.object(source, '_get', return_value={'value': []}) as get:
        list(source.fetch_unread(datetime.fromisoformat('2026-11-01T14:32:15+03:00'), include_read=True))
    assert get.call_args.args[2]['$filter'] == 'receivedDateTime ge 2026-11-01T11:32:15Z'


def test_imap_incremental_checks_internal_arrival_dates_before_downloading_bodies():
    from datetime import datetime, timezone
    from mailcheck.sources.imap import IMAPSource
    source = IMAPSource(host='example.test', port=993, username='test', password='password')
    box = Mock()
    box.folder.list.return_value = []
    box.uids.return_value = ['1', '2', '3', '4']
    box.client.uid.return_value = ('OK', [
        b'1 (UID 1 INTERNALDATE "01-Nov-2026 10:00:00 +0000")',
        b'2 (UID 2 INTERNALDATE "01-Nov-2026 11:00:00 +0000")',
        b'3 (UID 3 INTERNALDATE "01-Nov-2026 13:00:00 +0200")',
        b'4 (UID 4 INTERNALDATE "01-Nov-2026 03:30:00 -0800")',
    ])
    box.fetch.return_value = [Mock()]
    raw = Mock()
    with patch.object(source, '_open', return_value=box), patch('mailcheck.sources.imap._to_raw', return_value=raw):
        assert list(source.fetch_unread(datetime(2026, 11, 1, 11, tzinfo=timezone.utc), include_read=True)) == [raw]
    assert box.fetch.call_args.kwargs['uid_list'] == ['2', '3', '4']
    assert box.fetch.call_args.kwargs['mark_seen'] is False
    assert 'UNSEEN' not in str(box.uids.call_args.args[0]).upper()
    box.logout.assert_called_once()


def test_imap_incomplete_arrival_metadata_is_a_failure_not_a_silent_skip():
    from datetime import datetime, timezone
    from mailcheck.sources.imap import IMAPSource
    source = IMAPSource(host='example.test', port=993, username='test', password='password')
    box = Mock()
    box.folder.list.return_value = []
    box.uids.return_value = ['1']
    box.client.uid.return_value = ('OK', [])
    with patch.object(source, '_open', return_value=box), pytest.raises(SourceError, match='arrival'):
        list(source.fetch_unread(datetime(2026, 11, 1, tzinfo=timezone.utc), include_read=True))
    box.fetch.assert_not_called()
    box.logout.assert_called_once()


def test_outlook_collects_inbox_and_junk_and_deduplicates_moves():
    source = OutlookGraphSource(label='test', client_id='test')
    urls=[]
    def get(client,url,params):
        urls.append(url)
        if 'junkemail' in url:
            return {'value':[{'id':'moved','internetMessageId':'<same@test>'},{'id':'junk','internetMessageId':'<junk@test>','isRead':True}]}
        return {'value':[{'id':'inbox','internetMessageId':'<same@test>'}]}
    with patch.object(source,'_client',return_value=nullcontext(None)),patch.object(source,'_get',side_effect=get):
        messages=list(source.fetch_unread(date(2026,10,1),include_read=True))
    assert any('junkemail' in url for url in urls)
    assert [m.message_id for m in messages]==['<same@test>','<junk@test>']
    assert messages[1].folder=='Junk Email'


def test_imap_discovers_special_junk_and_selects_every_folder_read_only():
    from types import SimpleNamespace
    from mailcheck.sources.imap import IMAPSource
    source=IMAPSource(host='example.test',port=993,username='test',password='password')
    box=Mock()
    box.folder.list.return_value=[
        SimpleNamespace(name='INBOX',flags=()),
        SimpleNamespace(name='[Gmail]/Spam',flags=('\\Junk',)),
        SimpleNamespace(name='Trash',flags=('\\Trash',)),
    ]
    box.fetch.side_effect=[[Mock()],[Mock()]]
    raw1=Mock(message_id='<one@test>');raw2=Mock(message_id='<spam@test>')
    with patch.object(source,'_open',return_value=box),patch('mailcheck.sources.imap._to_raw',side_effect=[raw1,raw2]):
        assert list(source.fetch_unread(date(2026,10,1),include_read=True))==[raw1,raw2]
    selected=[call.args[0] for call in box.folder.set.call_args_list]
    assert '[Gmail]/Spam' in selected
    assert 'Trash' not in selected
    assert all(call.kwargs['readonly'] for call in box.folder.set.call_args_list)
    assert all(call.kwargs['mark_seen'] is False for call in box.fetch.call_args_list)


def test_imap_junk_failure_is_reported_instead_of_becoming_a_successful_check():
    from types import SimpleNamespace
    from mailcheck.sources.imap import IMAPSource
    source=IMAPSource(host='example.test',port=993,username='test',password='password')
    box=Mock()
    box.folder.list.return_value=[SimpleNamespace(name='Spam',flags=())]
    box.folder.set.side_effect=OSError('Folder offline')
    box.fetch.return_value=[]
    with patch.object(source,'_open',return_value=box),pytest.raises(SourceError,match='Spam'):
        list(source.fetch_unread(date(2026,10,1),include_read=True))
    box.logout.assert_called_once()


def test_folder_collection_status_reports_empty_folders_too():
    from mailcheck.sources.base import collection_scope
    source=OutlookGraphSource(label='test',client_id='test')
    status=[]
    with collection_scope(status.append),patch.object(source,'_client',return_value=nullcontext(None)),patch.object(source,'_get',return_value={'value':[]}):
        list(source.fetch_unread(date(2026,10,1),include_read=True))
    assert 'Collected 0 message(s) from Inbox.' in status
    assert 'Collected 0 message(s) from Junk Email.' in status


def test_imap_incremental_looks_up_arrival_metadata_in_both_folders():
    from datetime import datetime,timezone
    from types import SimpleNamespace
    from mailcheck.sources.imap import IMAPSource
    source=IMAPSource(host='example.test',port=993,username='test',password='password')
    box=Mock()
    box.folder.list.return_value=[SimpleNamespace(name='Spam',flags=())]
    box.uids.side_effect=[[],['5']]
    box.client.uid.return_value=('OK',[b'1 (UID 5 INTERNALDATE "03-Nov-2026 13:00:00 +0000")'])
    box.fetch.return_value=[Mock()]
    raw=Mock(message_id='<junk@test>')
    with patch.object(source,'_open',return_value=box),patch('mailcheck.sources.imap._to_raw',return_value=raw):
        assert list(source.fetch_unread(datetime(2026,11,3,12,tzinfo=timezone.utc),include_read=True))==[raw]
    assert box.uids.call_count==2
    assert box.fetch.call_args.kwargs['uid_list']==['5']
    assert box.fetch.call_args.kwargs['mark_seen'] is False
