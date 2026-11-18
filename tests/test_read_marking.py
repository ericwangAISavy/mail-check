import sqlite3
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from mailcheck import read_marking
from mailcheck.sources.base import SourceError
from mailcheck.sources.outlook import OutlookGraphSource


def test_message_failure_does_not_block_other_read_tasks(tmp_path):
    from mailcheck.sources.base import MessageReadError
    account = SimpleNamespace(id=1, email='a@example.com', provider='outlook')
    with sqlite3.connect(tmp_path / 'queue.db') as conn:
        conn.executescript(read_marking.SCHEMA)
        for uid in ['a-bad', 'b-good']:
            read_marking.enqueue(conn, account, uid)
        conn.commit()
        seen = []
        def mark_read(uid):
            seen.append(uid)
            if uid == 'a-bad':
                raise MessageReadError('invalid message ID')
        assert len(read_marking.drain(conn, account, SimpleNamespace(mark_read=mark_read))) == 1
        assert seen == ['a-bad', 'b-good']
        assert conn.execute('SELECT uid FROM outlook_read_tasks').fetchall() == [('a-bad',)]


def test_connection_grants_collection_reply_and_read_update_scopes():
    from mailcheck.outlook_auth import CONNECT_SCOPES
    from mailcheck.replies import SEND_SCOPES
    assert {'Mail.Read', 'Mail.ReadWrite', 'Calendars.Read'} <= set(CONNECT_SCOPES)
    assert set(SEND_SCOPES) <= set(CONNECT_SCOPES)


def test_bound_workspace_upgrades_previous_schema_without_losing_data(tmp_path):
    from mailcheck import db
    from mailcheck.workspaces import WorkspaceContext, bind_workspace
    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        db.add_account(conn, label='preserved', email='person@example.com')
        conn.execute('DROP TABLE outlook_read_tasks')
        conn.execute('PRAGMA user_version=50')
    context = WorkspaceContext('legacy', None, tmp_path / 'config.toml', path, tmp_path / 'control')
    with bind_workspace(context), db.session(path) as conn:
        assert conn.execute('PRAGMA user_version').fetchone()[0] == db.SCHEMA_VERSION
        assert conn.execute('SELECT label FROM accounts').fetchone()[0] == 'preserved'
        assert conn.execute('SELECT count(*) FROM outlook_read_tasks').fetchone()[0] == 0


def test_bound_workspace_still_rejects_unsupported_schema(tmp_path):
    from mailcheck import db
    from mailcheck.workspaces import WorkspaceContext, bind_workspace
    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        conn.execute('PRAGMA user_version=49')
    context = WorkspaceContext('legacy', None, tmp_path / 'config.toml', path, tmp_path / 'control')
    with bind_workspace(context), pytest.raises(RuntimeError, match='no automatic migration'):
        db.connect(path)


@pytest.mark.parametrize('version', [50, 51, 49])
def test_workspace_schema_probe_closes_connection(tmp_path, monkeypatch, version):
    from mailcheck import db
    from mailcheck.workspaces import WorkspaceContext, bind_workspace
    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        conn.execute(f'PRAGMA user_version={version}')
    original = sqlite3.connect
    probes = []
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        if kwargs.get('uri') and 'mode=ro' in str(args[0]):
            probes.append(connection)
        return connection
    monkeypatch.setattr(sqlite3, 'connect', connect)
    context = WorkspaceContext('legacy', None, tmp_path / 'config.toml', path, tmp_path / 'control')
    with bind_workspace(context):
        if version == 49:
            with pytest.raises(RuntimeError):
                db.connect(path)
        else:
            db.connect(path).close()
    assert len(probes) == 1
    with pytest.raises(sqlite3.ProgrammingError, match='closed'):
        probes[0].execute('SELECT 1')


def test_outlook_read_state_survives_normalization_and_clears_retry(tmp_path):
    from mailcheck.normalize import normalize
    from mailcheck.sources.outlook import _to_raw
    account = SimpleNamespace(id=1, email='a@example.com', provider='outlook')
    raw = _to_raw({'id': 'already-read', 'isRead': True})
    msg = normalize(raw, account_id=1, account_label='test', max_body_chars=100)
    assert msg.is_read is True
    with sqlite3.connect(tmp_path / 'queue.db') as conn:
        conn.executescript(read_marking.SCHEMA)
        read_marking.enqueue(conn, account, msg.uid)
        read_marking.enqueue(conn, account, msg.uid, is_read=msg.is_read)
        assert conn.execute('SELECT count(*) FROM outlook_read_tasks').fetchone()[0] == 0


@pytest.mark.parametrize('status', [200, 204, 404, 410])
def test_graph_read_update(status):
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(status)
    client = httpx.Client(transport=httpx.MockTransport(handle))
    with patch('mailcheck.sources.outlook.acquire_token', return_value='token') as token, patch('mailcheck.sources.outlook.httpx.Client', return_value=client):
        OutlookGraphSource(label='test', client_id='test').mark_read('graph/id')
    token.assert_called_once_with('test', 'test', scopes=['Mail.ReadWrite'])
    assert requests[0].method == 'PATCH'
    assert requests[0].content == b'{"isRead":true}'


def test_permission_failure_keeps_read_task():
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403)))
    with patch('mailcheck.sources.outlook.acquire_token', return_value='token'), patch('mailcheck.sources.outlook.httpx.Client', return_value=client):
        with pytest.raises(SourceError, match='Reconnect'):
            OutlookGraphSource(label='test', client_id='test').mark_read('id')


def test_queue_survives_failure_and_retries(tmp_path):
    path = tmp_path / 'queue.db'
    account = SimpleNamespace(id=1, email='a@example.com', provider='outlook')
    with sqlite3.connect(path) as conn:
        conn.executescript(read_marking.SCHEMA)
        read_marking.enqueue(conn, account, 'graph-id')
        read_marking.enqueue(conn, account, 'graph-id')
        conn.commit()
        def fail(uid):
            raise SourceError('Reconnect the account')
        errors = read_marking.drain(conn, account, SimpleNamespace(mark_read=fail))
        assert errors
        assert conn.execute('SELECT count(*) FROM outlook_read_tasks').fetchone()[0] == 1
    with sqlite3.connect(path) as conn:
        seen = []
        assert read_marking.drain(conn, account, SimpleNamespace(mark_read=seen.append)) == []
        assert seen == ['graph-id']
        assert conn.execute('SELECT count(*) FROM outlook_read_tasks').fetchone()[0] == 0


def test_rollback_and_mailbox_isolation(tmp_path):
    conn = sqlite3.connect(tmp_path / 'queue.db')
    conn.executescript(read_marking.SCHEMA)
    account = SimpleNamespace(id=1, email='a@example.com', provider='outlook')
    read_marking.enqueue(conn, account, 'rolled-back')
    conn.rollback()
    read_marking.enqueue(conn, account, 'old-mailbox')
    conn.commit()
    account.email = 'b@example.com'
    seen = []
    read_marking.drain(conn, account, SimpleNamespace(mark_read=seen.append))
    assert seen == []
    conn.close()


def test_manual_check_marks_committed_mail_before_classification(tmp_path, monkeypatch):
    from mailcheck import db, pipeline
    from mailcheck.config import Config
    from tests.test_realtime_runtime import message
    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        aid = db.add_account(conn, label='primary', email='person@example.com', provider='outlook')
        seen = []
        def mark_read(uid):
            with db.session(path) as reader:
                assert reader.execute('SELECT count(*) FROM messages').fetchone()[0] == 1
                assert reader.execute('SELECT count(*) FROM outlook_read_tasks').fetchone()[0] == 1
            seen.append(uid)
        monkeypatch.setattr(pipeline, 'fetch_account', lambda *a: [message(aid)])
        monkeypatch.setattr(pipeline, 'build_source', lambda *a: SimpleNamespace(mark_read=mark_read))
        monkeypatch.setattr(pipeline.prefilter, 'apply', lambda *a: None)
        def unavailable(*a, **kw):
            assert seen == ['1']
            raise RuntimeError('model unavailable')
        monkeypatch.setattr(pipeline.LLMClient, 'from_config', unavailable)
        with pytest.raises(RuntimeError, match='model unavailable'):
            pipeline.check_once(conn, Config())
        assert conn.execute('SELECT count(*) FROM outlook_read_tasks').fetchone()[0] == 0
