from pathlib import Path
from unittest.mock import Mock
import tempfile
import pytest
import uuid
import sqlite3
import time

from mailcheck.shared.runtime import execute_job, publish_outbox, finish_manual


def test_disabled_workspace_never_executes_job():
    reader = Mock()
    reader.workspace.side_effect = ValueError('disabled')
    handler = Mock()
    with pytest.raises(ValueError):
        execute_job(reader, (Path('/unused'),)*3, {'workspace_id':'a'*32,'kind':'mail','account_id':1}, handler=handler)
    handler.assert_not_called()


def test_manual_reason_cannot_bypass_dispatch_authorization():
    reader = Mock()
    with tempfile.TemporaryDirectory() as folder:
        reader.root = Path(folder)
        reader.workspace.return_value = {'id':'legacy','root':None}
        handler = Mock()
        with pytest.raises((ValueError, PermissionError)):
            execute_job(reader, (Path(folder)/'config.toml',Path(folder)/'db',Path(folder)/'auth'),
                {'workspace_id':'legacy','kind':'manual-check','account_id':0,'dispatch_id':None}, handler=handler)
        handler.assert_not_called()


def test_outbox_publish_failure_never_acknowledges_database_rows():
    conn = Mock()
    broker = Mock()
    broker.publish.side_effect = ConnectionError('down')
    from unittest.mock import patch
    with patch('mailcheck.shared.runtime.storage.pending_outbox',return_value=[{'id':12,'topic':'messages'}]), \
         patch('mailcheck.shared.runtime.storage.acknowledge_outbox') as ack:
        with pytest.raises(ConnectionError):
            publish_outbox(conn,broker,'legacy')
        ack.assert_not_called()


def test_coordinator_reuses_connection_and_reconnects_after_failure(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from mailcheck.shared import runtime

    coordinator = runtime.Coordinator(SimpleNamespace(root=tmp_path, enabled_workspaces=lambda: []), (), 'amqp://test')
    monkeypatch.setattr(coordinator, 'subscriptions_run', lambda: None)
    monkeypatch.setattr(coordinator.stop, 'wait', lambda _: False)
    sessions = []
    polls = []

    class Broker:
        def __init__(self, url):
            if sessions:
                assert sessions[-1].closed
            self.closed = False
            sessions.append(self)

        def claim_dead_notice(self):
            polls.append(self)
            if len(polls) == 3:
                raise ConnectionError('connection dropped')
            if len(polls) == 5:
                coordinator.stop.set()

        def process_events(self, time_limit=0):
            pass

        def close(self):
            self.closed = True

    monkeypatch.setattr(runtime, 'RabbitBroker', Broker)
    coordinator.run()
    assert len(sessions) == 2
    assert polls == [sessions[0]] * 3 + [sessions[1]] * 2
    assert all(session.closed for session in sessions)


def test_already_enabled_capture_does_not_need_sqlite_writer_lock(tmp_path):
    from contextlib import closing
    from mailcheck import db
    from mailcheck.realtime import storage

    path = tmp_path / 'mail.db'
    with db.session(path) as conn:
        storage.set_publishing(conn, True)
    with closing(sqlite3.connect(path)) as writer, closing(sqlite3.connect(path, timeout=0)) as reader:
        writer.execute('BEGIN IMMEDIATE')
        storage.set_publishing(reader, True)
        assert reader.execute('SELECT enabled FROM realtime_runtime WHERE id=1').fetchone() == (1,)


def manual_fixture(tmp_path):
    from mailcheck import db
    from mailcheck.shared.state import atomic_json
    path=tmp_path/'mail.db'
    with db.session(path) as conn:
        aid=db.add_account(conn,label='same',email='person@example.com')
    reader=Mock(root=tmp_path/'control')
    reader.workspace.return_value={'id':'legacy','root':None}
    legacy=(tmp_path/'config.toml',path,tmp_path/'web-auth.json')
    dispatch=str(uuid.uuid4())
    fields=dict(id=dispatch,workspace_id='legacy',kind='manual-check',account_id=0,dispatch_id=dispatch)
    atomic_json(reader.root/'shared-runtime'/'dispatch'/f'{dispatch}.json',dict(
        workspace_id='legacy',kind='manual-check',token='test-session',body={},expires=time.time()+60))
    return reader,legacy,fields,aid


def test_manual_job_commit_rejects_account_disabled_during_fetch(tmp_path):
    from mailcheck import db
    from mailcheck.realtime.runtime import AccountDisabled
    reader,legacy,fields,aid=manual_fixture(tmp_path)
    def work(context,fields):
        with sqlite3.connect(legacy[1]) as concurrent:
            concurrent.execute('UPDATE accounts SET enabled=0 WHERE id=?',(aid,))
        with db.session() as conn:
            conn.execute("UPDATE accounts SET label='must-rollback' WHERE id=?",(aid,))
    with pytest.raises(AccountDisabled):
        execute_job(reader,legacy,fields,handler=work)
    with sqlite3.connect(legacy[1]) as conn:
        assert conn.execute("SELECT COUNT(*) FROM accounts WHERE label='must-rollback'").fetchone()[0]==0


def test_manual_job_requires_no_automatic_opt_in_and_holds_collection_lock(tmp_path):
    from mailcheck.shared.state import OperationLock,runtime_root
    reader,legacy,fields,aid=manual_fixture(tmp_path)
    def work(context,fields):
        competing=OperationLock(runtime_root(context)/f'collection-{aid}.lock')
        assert not competing.acquire(False)
        return 'manual operation allowed'
    assert execute_job(reader,legacy,fields,handler=work)=='manual operation allowed'


def test_shared_manual_failure_propagates_for_consumer_retry(tmp_path,monkeypatch):
    from mailcheck.web import app as web
    reader,legacy,fields,aid=manual_fixture(tmp_path)
    def fail(body,**kwargs):
        web._start_job(lambda:(_ for _ in ()).throw(ConnectionError('transient')),
                       failed='Check failed',verify_sourcing=False)
    monkeypatch.setattr(web,'_run_check',fail)
    with pytest.raises(ConnectionError):
        execute_job(reader,legacy,fields)


def test_registry_initializes_missing_file_but_never_migrates_existing(tmp_path):
    from mailcheck.shared.runtime import prepare_registry
    registry=prepare_registry(tmp_path)
    assert registry.list_workspace('legacy')==[]
    before=registry.path.read_bytes()
    prepare_registry(tmp_path)
    assert registry.path.read_bytes()==before


def test_cancelled_manual_job_clears_only_its_own_status(tmp_path):
    from mailcheck.shared.state import JobState
    job=str(uuid.uuid4())
    fields=dict(id=job,workspace_id='legacy',kind='manual-check',dispatch_id=job)
    state=JobState(tmp_path/'legacy'/'job.json')
    state.update(job_id=job,running=True)
    finish_manual(fields,tmp_path)
    assert not state['running'] and not state['ok']
    assert state['completion_id']==1
    state.update(job_id=job,running=False,ok=True)
    finish_manual(fields,tmp_path)
    assert state['ok']
    newer=str(uuid.uuid4())
    state.update(job_id=newer,running=True,ok=True)
    finish_manual(fields,tmp_path)
    assert state['running'] and state['job_id']==newer


def test_mail_collection_releases_capacity_when_classification_hint_is_full(tmp_path,monkeypatch):
    from mailcheck import db,config
    from mailcheck.realtime import storage
    from mailcheck.shared.broker import PendingCapacityError
    from mailcheck.shared.runtime import WorkspaceOperations
    from mailcheck.workspaces import WorkspaceContext,bind_workspace
    from tests.test_realtime_runtime import message
    path=tmp_path/'mail.db'
    with db.session(path) as conn:
        aid=db.add_account(conn,label='primary',email='person@example.com')
        storage.set_account(conn,aid,True)
    context=WorkspaceContext.from_record({'id':'legacy','root':None},
        (tmp_path/'config.toml',path,tmp_path/'auth'),tmp_path/'control')
    monkeypatch.setattr('mailcheck.shared.runtime.pipeline.fetch_account',lambda *args:[message(aid)])
    monkeypatch.setattr('mailcheck.shared.runtime.prefilter.apply',lambda *args:None)
    with bind_workspace(context):
        operation=WorkspaceOperations(context,'amqp://test')
        def full(*args,**kwargs):raise PendingCapacityError('full')
        monkeypatch.setattr(operation.broker,'enqueue',full)
        operation.collect_mail(aid)
    with db.session(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0]==1
        assert conn.execute('SELECT category FROM classifications').fetchone()[0]=='unclassified'


@pytest.mark.parametrize('checkpoint', ['broken-json', 'bad-date', 'future', 'naive'])
def test_bad_workspace_mail_checkpoint_cannot_stop_new_mail_collection(tmp_path, monkeypatch, checkpoint):
    import json
    from datetime import datetime, timedelta, timezone
    from mailcheck import db, mail_checkpoints
    from mailcheck.realtime import storage
    from mailcheck.shared.runtime import WorkspaceOperations
    from mailcheck.shared.state import runtime_root
    from mailcheck.workspaces import WorkspaceContext, bind_workspace
    from tests.test_realtime_runtime import message
    path = tmp_path/'mail.db'
    with db.session(path) as conn:
        aid = db.add_account(conn, label='primary', email='person@example.com')
        storage.set_account(conn, aid, True)
        account = db.list_accounts(conn)[0]
    context = WorkspaceContext.from_record({'id':'legacy','root':None},
        (tmp_path/'config.toml',path,tmp_path/'auth'),tmp_path/'control')
    now = datetime.now(timezone.utc)
    value = {'mailbox':mail_checkpoints.mailbox_key(account), 'checked':
        'not-a-date' if checkpoint=='bad-date' else
        (now+timedelta(days=7)).isoformat() if checkpoint=='future' else
        (now-timedelta(hours=1)).replace(tzinfo=None).isoformat()}
    saved = runtime_root(context)/f'mail-{aid}.json'
    saved.parent.mkdir(parents=True)
    saved.write_text('{' if checkpoint=='broken-json' else json.dumps(value))
    received = message(aid)
    def fetch(account, since, cfg):
        assert since.tzinfo is not None
        # A future checkpoint silently produces an empty mailbox result.
        return [received] if since <= now else []
    monkeypatch.setattr('mailcheck.shared.runtime.pipeline.fetch_account', fetch)
    monkeypatch.setattr('mailcheck.shared.runtime.prefilter.apply',lambda *args:None)
    with bind_workspace(context):
        operation = WorkspaceOperations(context, 'amqp://test')
        monkeypatch.setattr(operation.broker, 'enqueue', lambda *args:None)
        operation.collect_mail(aid)
    with db.session(path) as conn:
        assert conn.execute('SELECT COUNT(*) FROM messages').fetchone()[0] == 1
    assert 'checked' in json.loads(saved.read_text())


def test_mail_window_keeps_valid_pending_catchup_after_failure(tmp_path):
    import json
    from datetime import datetime, timedelta, timezone
    from mailcheck.shared.runtime import mail_collection_since
    now = datetime(2026,11,16,tzinfo=timezone.utc)
    path = tmp_path/'mail.json'
    old = now-timedelta(days=20)
    path.write_text(json.dumps(dict(mailbox='same',pending=old.isoformat(),checked=(now-timedelta(hours=1)).isoformat())))
    assert mail_collection_since(path,'same',now,7) == old
    assert mail_collection_since(path,'new-mailbox',now,7) == now-timedelta(days=7)
    path.write_text(json.dumps(dict(mailbox='same',pending='invalid',checked=old.isoformat())))
    assert mail_collection_since(path,'same',now,7) == old-timedelta(minutes=3)
    path.write_text(json.dumps(dict(mailbox='same',checked='0001-01-01T00:00:00+00:00')))
    assert mail_collection_since(path,'same',now,7) == now-timedelta(days=7)


def test_mail_window_does_not_hide_checkpoint_permission_errors(tmp_path):
    from datetime import datetime, timezone
    from mailcheck.shared.runtime import mail_collection_since
    path = Mock()
    path.read_text.side_effect = PermissionError('checkpoint unavailable')
    with pytest.raises(PermissionError):
        mail_collection_since(path,'same',datetime.now(timezone.utc),7)
