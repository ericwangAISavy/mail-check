"""Malformed Graph mail pages must remain retryable collection failures."""
from contextlib import nullcontext
from datetime import date
from unittest.mock import patch

import pytest

from mailcheck.sources.base import SourceError
from mailcheck.sources.outlook import OutlookGraphSource


@pytest.mark.parametrize('payload', [None, [], {}, {'value': None}, {'value': {}},
    {'value': [None]}, {'value': ['message']}, {'value': [{}]},
    {'value': [{'id': 'one', 'body': 'invalid'}]}])
def test_malformed_page_fails_closed(payload):
    source = OutlookGraphSource(label='test', client_id='test')
    with patch.object(source, '_client', return_value=nullcontext(object())), \
         patch.object(source, '_get', return_value=payload):
        with pytest.raises(SourceError, match='invalid'):
            list(source.fetch_unread(date(2026, 1, 1)))


def test_empty_page_and_optional_message_fields_are_supported():
    source = OutlookGraphSource(label='test', client_id='test')
    for payload, count in [({'value': []}, 0), ({'value': [{'id': 'one'}]}, 1)]:
        with patch.object(source, '_client', return_value=nullcontext(object())), \
             patch.object(source, '_get', return_value=payload):
            assert len(list(source.fetch_unread(date(2026, 1, 1)))) == count


def test_invalid_graph_page_preserves_checkpoint_and_continues_other_account(tmp_path):
    from datetime import datetime, timedelta, timezone
    from mailcheck import db, pipeline, mail_checkpoints
    from mailcheck.config import Config

    conn = db.connect(tmp_path / 'mail.db')
    try:
        db.add_account(conn, label='broken', email='broken@example.test')
        db.add_account(conn, label='healthy', email='healthy@example.test')
        account = db.get_account(conn, 'broken')
        previous = datetime.now(timezone.utc) - timedelta(days=3)
        mail_checkpoints.record(conn, account, previous)
        conn.commit()
        broken = OutlookGraphSource(label='broken', client_id='test')
        healthy = OutlookGraphSource(label='healthy', client_id='test')
        with patch.object(pipeline, 'build_source', side_effect=lambda account, cfg: broken if account.label == 'broken' else healthy), \
             patch.object(broken, '_client', return_value=nullcontext(object())), \
             patch.object(healthy, '_client', return_value=nullcontext(object())), \
             patch.object(broken, '_get', return_value={}), \
             patch.object(healthy, '_get', return_value={'value': []}):
            result = pipeline.check_once(conn, Config(check={'mode': 'since_last'}))
        assert result.accounts_checked == 1
        assert len(result.errors) == 1
        assert mail_checkpoints.checkpoint(conn, account) == previous
        assert mail_checkpoints.checkpoint(conn, db.get_account(conn, 'healthy')) is not None
    finally:
        conn.close()
