import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from mailcheck import db
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.realtime.runtime import AccountDisabled
from mailcheck.shared.runtime import execute_job
from mailcheck.shared.state import OperationLock, atomic_json, runtime_root
from tests.test_shared_runtime import manual_fixture


def selection_fixture(tmp_path, *, disabled=False, body=None):
    reader, legacy, fields, aid = manual_fixture(tmp_path)
    fields['kind'] = 'manual-reclassify'
    path = reader.root/'shared-runtime'/'dispatch'/f"{fields['id']}.json"
    record = json.loads(path.read_text())
    record.update(kind=fields['kind'], body=body or {})
    atomic_json(path, record)
    with db.session(legacy[1]) as conn:
        pk = db.upsert_message(conn, NormalizedMessage(aid, 'same', 'waiting', 'waiting',
            'INBOX', 'sender@example.test', 'Sender', 'Waiting',
            datetime.now(timezone.utc), 'Temporary body'))
        db.save_classification(conn, pk, Classification('unclassified', retryable=True), 'test', 'test')
        if disabled:
            conn.execute('UPDATE accounts SET enabled=0 WHERE id=?', (aid,))
    return reader, legacy, fields, aid, pk


def test_disabled_reclassification_target_never_reaches_operation(tmp_path):
    reader, legacy, fields, aid, pk = selection_fixture(tmp_path, disabled=True)
    handler = Mock()
    with pytest.raises(AccountDisabled):
        execute_job(reader, legacy, fields, handler=handler)
    handler.assert_not_called()


def test_reclassification_freezes_candidates_and_leases_only_targets(tmp_path, monkeypatch):
    reader, legacy, fields, aid, pk = selection_fixture(tmp_path)
    with db.session(legacy[1]) as conn:
        unrelated = db.add_account(conn, label='unrelated', email='other@example.test')
    from mailcheck.web import app as web
    seen = []
    def reclassify(body):
        seen.append(body.pks)
        from mailcheck.workspaces import current_workspace
        lock = OperationLock(runtime_root(current_workspace())/f'classification-{aid}.lock')
        assert not lock.acquire(False)
        other = OperationLock(runtime_root(current_workspace())/f'classification-{unrelated}.lock')
        assert other.acquire(False)
        other.release()
    monkeypatch.setattr(web, '_run_reclassify', reclassify)
    execute_job(reader, legacy, fields)
    assert seen == [[pk]]


def test_disabled_target_selected_by_primary_key_is_rejected(tmp_path):
    reader, legacy, fields, aid, pk = selection_fixture(tmp_path, disabled=True)
    path = reader.root/'shared-runtime'/'dispatch'/f"{fields['id']}.json"
    record = json.loads(path.read_text())
    record['body'] = {'pks': [pk]}
    atomic_json(path, record)
    with pytest.raises(AccountDisabled):
        execute_job(reader, legacy, fields, handler=Mock())


def test_empty_reclassification_selection_cannot_expand_to_all_messages(tmp_path, monkeypatch):
    reader, legacy, fields, aid, pk = selection_fixture(tmp_path, body={'pks': [999999]})
    from mailcheck.web import app as web
    def reclassify(body):
        with sqlite3.connect(legacy[1]) as conn:
            conn.row_factory = sqlite3.Row
            assert not db.messages_in_categories(conn, ['unclassified'], pks=body.pks or None)
    monkeypatch.setattr(web, '_run_reclassify', reclassify)
    execute_job(reader, legacy, fields)
