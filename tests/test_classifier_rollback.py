"""Original sender policy and complete, repeatable historical relogging."""
from datetime import datetime, date
from mailcheck import db, pipeline, payments, prefilter
from mailcheck.config import Config
from mailcheck.models import NormalizedMessage, Classification
from mailcheck.taxonomy import CATEGORIES


def message(account, key, sender='noreply@indeed.com', stamp='2026-11-04T18:00:00+00:00'):
    return NormalizedMessage(account_id=account, account_label='inbox', message_id=str(key), uid=str(key), folder='INBOX', from_addr=sender, from_name='', subject='Application received', date_utc=datetime.fromisoformat(stamp), body='We received your application.')


def test_original_board_policy_restored():
    assert prefilter.apply(message(1, 1)).category == 'job_alert'


def test_historical_relog_updates_every_receipt_and_is_idempotent(tmp_path):
    with db.session(tmp_path/'history.db') as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        for key in range(205):
            pk=db.upsert_message(conn,message(account,key))
            db.save_classification(conn,pk,Classification(category='application_ack'), 'model','2',commit=False)
        outside=db.upsert_message(conn,message(account,'outside',stamp='2026-11-09T06:00:00+00:00'))
        db.save_classification(conn,outside,Classification(category='application_ack'),'model','2')
        conn.execute("INSERT INTO bidders(name,created_at) VALUES('Alex','2026-01-01')")
        payments.assign(conn,1,payments.AssignmentBody(account_id=account,start_date=date(2026,11,2)))
        conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(1,'2026-11-02',205,1230,'2026-11-09','saved')")
        conn.commit()
        before=dict(conn.execute('SELECT * FROM bidder_payments').fetchone())
        for _ in range(2):
            result=pipeline.reclassify(conn,Config(),categories=[category.name for category in CATEGORIES],since_iso='2026-11-02T06:00:00+00:00',until_iso='2026-11-09T06:00:00+00:00',limit=None)
            assert result.fetched == 205
            assert result.prefiltered == 205
            report=payments.report(conn,date(2026,11,2))
            assert sum(report['daily']) == 0
            assert 'reconciliation' not in report
            assert dict(conn.execute('SELECT * FROM bidder_payments').fetchone()) == before
        assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0] == 2
        assert conn.execute("SELECT category FROM application_receipts WHERE message_id='outside'").fetchone()[0] == 'application_ack'


def test_week_relog_endpoint_runs_in_background_and_rejects_bidder(tmp_path,monkeypatch):
    from mailcheck import config
    from mailcheck.web import app as web
    from tests.web_client import TestClient,sign_in_bidder
    path=tmp_path/'api.db'
    monkeypatch.setattr(config,'db_path',lambda:path)
    monkeypatch.setattr(config,'config_dir',lambda:tmp_path)
    monkeypatch.setattr(config,'config_path',lambda:tmp_path/'config.toml')
    config.save(Config.model_validate({'llm':{'base_url':'http://example.test','model':'test'}}))
    with db.session() as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        pk=db.upsert_message(conn,message(account,'one'))
        db.save_classification(conn,pk,Classification(category='application_ack'),'test','2')
    jobs=[]
    def start(work,**kwargs):
        jobs.append(work)
        web._job_lock.release()
    monkeypatch.setattr(web,'_start_job',start)
    with TestClient(web.create_app()) as client:
        response=client.post('/api/payments/reclassify',json={'week':'2026-11-04'})
        assert response.status_code==200,response.text
        assert response.json()['count']==1
        jobs.pop()()
        with db.session() as conn:
            assert conn.execute('SELECT category FROM application_receipts').fetchone()[0]=='job_alert'
            assert conn.execute('SELECT COUNT(*) FROM runs').fetchone()[0]==1
        assert client.post('/api/payments/reclassify',json={}).status_code==200
        assert client.post('/api/payments/reclassify',json={'week':'2025-01-01'}).status_code==404
        sign_in_bidder(client)
        assert client.post('/api/payments/reclassify',json={}).status_code==403


def test_history_job_does_not_run_an_unscoped_verification(monkeypatch):
    from mailcheck.web import app as web
    class ImmediateThread:
        def __init__(self, *, target, **kwargs): self.target=target
        def start(self): self.target()
    monkeypatch.setattr(web.threading,'Thread',ImmediateThread)
    calls=[]
    monkeypatch.setattr(web.sourcing_verification,'verify_all',lambda *args,**kwargs:calls.append(kwargs))
    assert web._job_lock.acquire(blocking=False)
    web._start_job(lambda:None,failed='failure',verify_sourcing=False)
    assert calls==[]
    assert not web._job_lock.locked()


def test_history_selection_exposes_fallback_received_time(tmp_path):
    with db.session(tmp_path/'missing-date.db') as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        pk=db.upsert_message(conn,message(account,'no-date'))
        conn.execute("UPDATE messages SET date_utc=NULL,fetched_at='2026-10-01T12:00:00Z' WHERE id=?",(pk,))
        db.save_classification(conn,pk,Classification(category='other'),'test','2')
        rows=db.messages_in_categories(conn,['other'],limit=None)
        assert rows[0]['received_at']=='2026-10-01T12:00:00Z'


def test_historical_relog_batches_successfully_classified_mail(tmp_path,monkeypatch):
    from contextlib import nullcontext
    import json
    from mailcheck.taxonomy import CATEGORIES
    calls=[]
    class Model:
        model='test'
        def complete(self,system,user,**kwargs):
            inputs=json.loads(user.split('Classify these emails:\n',1)[1])
            calls.append(len(inputs))
            return json.dumps({'results':[{'id':row['id'],'category':'application_ack'} for row in inputs]})
    monkeypatch.setattr(pipeline.LLMClient,'from_config',lambda *args,**kwargs:nullcontext(Model()))
    with db.session(tmp_path/'batches.db') as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        for key in range(6):
            pk=db.upsert_message(conn,message(account,key,sender='recruiter@acme.test'))
            db.save_classification(conn,pk,Classification(category='application_ack'),'test','2')
        cfg=Config();cfg.llm.batch_size=5;cfg.llm.concurrency=1
        result=pipeline.reclassify(conn,cfg,categories=[category.name for category in CATEGORIES],limit=None)
        assert result.classified==6
        assert sorted(calls)==[1,5]


def test_failed_history_model_preserves_known_receipts_and_logs_failure(tmp_path,monkeypatch):
    from contextlib import nullcontext
    monkeypatch.setattr(pipeline.LLMClient,'from_config',lambda *args,**kwargs:nullcontext(type('Model',(),{'model':'test'})()))
    monkeypatch.setattr(pipeline,'classify',lambda *args,**kwargs:([Classification(category='unclassified',retryable=True,summary='Model busy')],[]))
    with db.session(tmp_path/'failure.db') as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        pk=db.upsert_message(conn,message(account,'receipt',sender='hr@employer.test'))
        db.save_classification(conn,pk,Classification(category='application_ack',company='Acme'),'test','2')
        result=pipeline.reclassify(conn,Config(),categories=[category.name for category in CATEGORIES],limit=None)
        assert db.get_cached(conn,pk,None).category=='application_ack'
        assert conn.execute('SELECT category FROM application_receipts').fetchone()[0]=='application_ack'
        assert result.classified==0
        assert result.retryable==1
        assert any('previous classification preserved' in error for error in result.errors)
        assert conn.execute('SELECT finished_at FROM runs').fetchone()[0]


def test_history_preflight_can_omit_email_bodies(tmp_path):
    with db.session(tmp_path/'preflight.db') as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        pk=db.upsert_message(conn,message(account,'receipt'))
        db.save_classification(conn,pk,Classification(category='application_ack'),'test','2')
        preview=db.messages_in_categories(conn,['application_ack'],include_body=False)
        assert preview[0]['body_text']==''
        assert preview[0]['received_at']
        assert db.messages_in_categories(conn,['application_ack'])[0]['body_text']
