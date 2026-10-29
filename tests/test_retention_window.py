from datetime import datetime, timezone
from unittest.mock import Mock, patch
from mailcheck import pipeline
from mailcheck.config import Config


class FrozenDatetime(datetime):
    @classmethod
    def now(cls,tz=None):
        return datetime(2026,10,29,18,30,tzinfo=timezone.utc)


def test_retention_never_deletes_messages_inside_date_based_fetch_window():
    cfg=Config()
    cfg.check.lookback_days=7
    cfg.check.retain_days=7
    with patch.object(pipeline,'datetime',FrozenDatetime), patch.object(pipeline.db,'start_run',return_value=1), patch.object(pipeline.db,'list_accounts',return_value=[]), patch.object(pipeline.db,'prune_messages',return_value=0) as prune, patch.object(pipeline,'_finish'):
        pipeline.check_once(Mock(),cfg)
    assert prune.call_args.kwargs['before_iso']=='2026-10-22T00:00:00+00:00'


def test_done_message_on_first_fetch_morning_keeps_identity_and_status(tmp_path):
    from mailcheck import db
    from mailcheck.models import NormalizedMessage
    cfg=Config()
    cfg.check.lookback_days=cfg.check.retain_days=7
    conn=db.connect(tmp_path/'mail.db')
    try:
        account=db.add_account(conn,label='test',email='test@example.test')
        message=NormalizedMessage(account_id=account,account_label='test',message_id='<early>',uid='1',folder='INBOX',from_addr='sender@example.test',from_name='Sender',subject='Interview',date_utc=datetime(2026,10,22,8,tzinfo=timezone.utc),body='Hello')
        pk=db.upsert_message(conn,message)
        db.set_handled(conn,pk,True)
        with patch.object(pipeline,'datetime',FrozenDatetime),patch.object(pipeline,'fetch_account',return_value=[]),patch.object(pipeline,'_finish'):
            pipeline.check_once(conn,cfg)
        stored=db.get_message(conn,pk)
        assert stored is not None
        assert stored['handled_at'] is not None
        assert db.upsert_message(conn,message)==pk
        assert db.get_message(conn,pk)['handled_at'] is not None
    finally:conn.close()
