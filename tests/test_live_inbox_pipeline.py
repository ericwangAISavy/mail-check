"""Recent mailbox polling must leave the durable collection cursor untouched."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from mailcheck import db, mail_checkpoints, pipeline
from mailcheck.config import Config
from mailcheck.models import NormalizedMessage


@pytest.fixture
def mailbox(tmp_path, monkeypatch):
    monkeypatch.setenv('OFFERPATH_MAINTENANCE_LOCK', str(tmp_path / 'installation.lock'))
    conn = db.connect(tmp_path / 'mail.db')
    ids = [db.add_account(conn, label=label, email=f'{label}@example.com')
           for label in ('first', 'second', 'disabled')]
    conn.execute('UPDATE accounts SET enabled=0 WHERE id=?', (ids[2],))
    conn.commit()
    yield conn, ids
    conn.close()


@pytest.mark.parametrize('selection', ['first', 'empty', 'disabled'])
def test_targets_only_selected_enabled_accounts(mailbox, selection):
    conn, ids = mailbox
    selected = {'first': {ids[0]}, 'empty': set(), 'disabled': {ids[2]}}[selection]
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    with patch.object(pipeline, 'fetch_account', return_value=[]) as fetch:
        result = pipeline.check_once(conn, Config(), account_ids=selected, recent_since=cutoff)
    assert [call.args[0].id for call in fetch.call_args_list] == ([ids[0]] if selection == 'first' else [])
    assert result.accounts_checked == (1 if selection == 'first' else 0)
    if selection == 'first':
        assert fetch.call_args.args[1] == cutoff
        assert fetch.call_args.args[1].tzinfo is timezone.utc


@pytest.mark.parametrize('existing', ['checkpoint', 'pending', 'none'])
@pytest.mark.parametrize('with_message', [False, True])
def test_recent_scan_preserves_checkpoints_and_skips_retention(mailbox, existing, with_message):
    conn, ids = mailbox
    account = db.get_account(conn, "first")
    old = datetime.now(timezone.utc) - timedelta(days=3)
    if existing == 'checkpoint':
        mail_checkpoints.record(conn, account, old)
    elif existing == 'pending':
        mail_checkpoints.begin(conn, account, old)
    conn.commit()
    before = [tuple(row) for row in conn.execute('SELECT * FROM mail_checkpoints')]
    messages = [NormalizedMessage(account_id=account.id, account_label=account.label,
        message_id='digest', uid='1', folder='INBOX', from_addr='alerts@indeed.com',
        from_name='Indeed', subject='Job alert', date_utc=datetime.now(timezone.utc),
        body='Jobs matching your search')] if with_message else []
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    with patch.object(pipeline, 'fetch_account', return_value=messages), \
         patch.object(db, 'prune_messages', side_effect=AssertionError('recent scan pruned')), \
         patch.object(mail_checkpoints, 'begin', side_effect=AssertionError('recent scan began checkpoint')):
        result = pipeline.check_once(conn, Config(check={'mode': 'since_last'}),
                                     account_ids={account.id}, recent_since=cutoff)
    assert [tuple(row) for row in conn.execute('SELECT * FROM mail_checkpoints')] == before
    assert result.fetched == len(messages)
    assert result.prefiltered == len(messages)
    assert result.pruned == 0
    assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 1


def test_recent_cutoff_normalizes_to_utc(mailbox):
    conn, ids = mailbox
    cutoff = datetime.now(timezone(timedelta(hours=5, minutes=30))) - timedelta(minutes=10)
    with patch.object(pipeline, 'fetch_account', return_value=[]) as fetch:
        pipeline.check_once(conn, Config(), account_ids={ids[0]}, recent_since=cutoff)
    assert fetch.call_args.args[1] == cutoff
    assert fetch.call_args.args[1].tzinfo is timezone.utc


def test_recent_cutoff_requires_timezone(mailbox):
    conn, ids = mailbox
    with pytest.raises(ValueError, match='timezone-aware'):
        pipeline.check_once(conn, Config(), account_ids={ids[0]}, recent_since=datetime.now())
    assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 0
