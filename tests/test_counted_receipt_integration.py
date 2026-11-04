from datetime import date, datetime
from unittest.mock import patch
import pytest
from mailcheck import db, payments, sourcing_verification
from mailcheck.models import Classification, NormalizedMessage
from tests import test_sourcing_verification as fixtures


@pytest.fixture
def pair():
    case = fixtures.SourcingVerificationTests(); case.setUp()
    try:
        base=case.snapshot()
        case.native.append(case.conn,case.tab(),'one-job',base['revision'],
            [['Acme','Engineer','https://jobs.test/job-123']],work_date='2026-11-04')
        case.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-11-01')",(case.account_id,))
        case.conn.execute("UPDATE bidders SET pay_per_bid='0.05',adjustment_percent='20' WHERE id=1")
        for identity,sender,stamp in [('platform','jobs-noreply@linkedin.com','2026-11-04T18:00:00Z'),('employer','recruiting@acme.test','2026-11-04T18:01:00Z')]:
            message=NormalizedMessage(account_id=case.account_id,account_label='personal',message_id=identity,
                uid=identity,folder='INBOX',from_addr=sender,from_name='',subject='Application received',
                date_utc=datetime.fromisoformat(stamp),body='We received your application to Acme for Engineer.')
            pk=db.upsert_message(case.conn,message)
            db.save_classification(case.conn,pk,Classification(category='application_ack',company='Acme',role='Engineer'), 'same-model','2')
        case.conn.commit()
        sourcing_verification.verify_all(case.conn,refresh_since=date(2026,11,2),refresh_until=date(2026,11,8),week_only=True,sample=False)
        yield case
    finally:case.doCleanups()


def test_classifier_admitted_platform_and_employer_count_once(pair):
    report=payments.report(pair.conn,date(2026,11,2),admin=True)
    bidder=next(row for row in report['bidders'] if row['id']==1)
    assert bidder['daily'][2] == 1
    assert bidder['calculated_amount_cents'] == 6
    assert bidder['raw_daily'][2] == 2
    assert report['reconciliation']['raw_receipts'] == 2
    assert report['reconciliation']['counted_receipts'] == 1
    assert report['reconciliation']['confirmed_platform_copies'] == 1
    assert report['reconciliation']['verified_applications'] == 1
    assert report['reconciliation']['possible_extra_confirmations'] == 0
    assert report['reconciliation']['unmatched_receipts'] == 0
    assert pair.conn.execute("SELECT COUNT(*) FROM application_receipts WHERE category='application_ack'").fetchone()[0] == 2


def test_today_badge_uses_same_corrected_receipt_predicate(pair):
    with patch.object(payments,'today',return_value=date(2026,11,4)):
        assert payments.received_today(pair.conn) == 1


def test_saved_payment_is_not_changed_and_read_only_count_agrees(pair):
    pair.conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(1,'2026-11-02',2,12,'2026-11-09T12:00:00Z','Existing payment')")
    pair.conn.commit()
    payments.report(pair.conn,date(2026,11,2),admin=True)
    pair.conn.commit()
    before=pair.conn.total_changes
    pair.conn.execute('PRAGMA query_only=ON')
    report=payments.report(pair.conn,date(2026,11,2),read_only=True)
    bidder=next(row for row in report['bidders'] if row['id']==1)
    assert bidder['total'] == 1
    assert bidder['payment']['application_count'] == 2
    assert bidder['payment']['amount_cents'] == 12
    assert pair.conn.total_changes == before


def test_origin_is_preserved_after_repeated_sync(pair):
    payments.sync_receipts(pair.conn)
    assert pair.conn.execute("SELECT sender FROM application_receipts WHERE message_id='platform'").fetchone()[0] == 'jobs-noreply@linkedin.com'


def test_actual_classifier_keeps_both_acks_but_estimate_counts_one(pair):
    import json
    from mailcheck.llm.classify import classify
    from mailcheck import prefilter
    class ControlledModel:
        def complete(self, system, user, **options):
            messages=json.loads(user.split('Classify these emails:\n',1)[1])
            return json.dumps({'results':[{'id':message['id'],'category':'application_ack',
                'confidence':.99,'company':'Acme','role':'Engineer','action_required':False,
                'needs_review':False,'summary':'Application received.'} for message in messages]})
    messages=[]
    for row in pair.conn.execute('SELECT * FROM messages ORDER BY id'):
        messages.append(NormalizedMessage(account_id=row['account_id'],account_label='personal',
            message_id=row['message_id'],uid=row['uid'],folder=row['folder'],
            from_addr=row['from_addr'],from_name='',subject=row['subject'],
            date_utc=datetime.fromisoformat(row['date_utc']),body=row['body_text']))
    assert all(prefilter.apply(message) is None for message in messages)
    results, errors=classify(ControlledModel(),messages)
    assert not errors
    assert [result.category for result in results]==['application_ack','application_ack']
    for message,result in zip(messages,results):
        pk=db.upsert_message(pair.conn,message)
        db.save_classification(pair.conn,pk,result,'controlled-model','2')
    assert pair.conn.execute("SELECT COUNT(*) FROM application_receipts WHERE category='application_ack'").fetchone()[0]==2
    with patch.object(payments,'today',return_value=date(2026,11,4)):
        assert payments.received_today(pair.conn)==1
    assert payments.report(pair.conn,date(2026,11,2))['bidders'][0]['total']==1
