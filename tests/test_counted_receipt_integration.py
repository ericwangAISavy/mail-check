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


def test_existing_ack_ledger_counts_every_receipt_until_reclassified(pair):
    report=payments.report(pair.conn,date(2026,11,2),admin=True)
    bidder=next(row for row in report['bidders'] if row['id']==1)
    assert bidder['daily'][2] == 2
    assert bidder['calculated_amount_cents'] == 12
    assert 'raw_daily' not in bidder
    assert 'verified_daily' not in bidder
    assert 'reconciliation' not in report
    assert pair.conn.execute("SELECT COUNT(*) FROM application_receipts WHERE category='application_ack'").fetchone()[0] == 2


def test_today_badge_counts_existing_ack_labels(pair):
    with patch.object(payments,'today',return_value=date(2026,11,4)):
        assert payments.received_today(pair.conn) == 2


def test_saved_payment_is_not_changed_and_read_only_count_agrees(pair):
    pair.conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(1,'2026-11-02',2,12,'2026-11-09T12:00:00Z','Existing payment')")
    pair.conn.commit()
    payments.report(pair.conn,date(2026,11,2),admin=True)
    pair.conn.commit()
    before=pair.conn.total_changes
    pair.conn.execute('PRAGMA query_only=ON')
    report=payments.report(pair.conn,date(2026,11,2),read_only=True)
    bidder=next(row for row in report['bidders'] if row['id']==1)
    assert bidder['total'] == 2
    assert bidder['payment']['application_count'] == 2
    assert bidder['payment']['amount_cents'] == 12
    assert pair.conn.total_changes == before


def test_origin_is_preserved_after_repeated_sync(pair):
    payments.sync_receipts(pair.conn)
    assert pair.conn.execute("SELECT sender FROM application_receipts WHERE message_id='platform'").fetchone()[0] == 'jobs-noreply@linkedin.com'


def test_explicit_reclassification_restores_board_prefilter_and_keeps_employer_ack(pair):
    import json
    from mailcheck import pipeline
    from mailcheck.config import Config

    class ControlledModel:
        model = 'controlled-original'

        def complete(self, system, user, **options):
            messages = json.loads(user.split('Classify these emails:\n', 1)[1])
            assert len(messages) == 1  # The platform sender never reaches the model.
            return json.dumps({'results': [{'id': message['id'], 'category': 'application_ack',
                'confidence': .99, 'company': 'Acme', 'role': 'Engineer',
                'action_required': False, 'summary': 'Application received.'} for message in messages]})

    pair.conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(1,'2026-11-02',2,12,'2026-11-09T12:00:00Z','Existing payment')")
    pair.conn.commit()
    with patch.object(payments, 'today', return_value=date(2026, 11, 4)):
        assert payments.received_today(pair.conn) == 2
    assert payments.report(pair.conn, date(2026, 11, 2))['bidders'][0]['total'] == 2
    with patch.object(pipeline.LLMClient, 'from_config') as factory, patch.object(pipeline.interviews, 'process_run', return_value=[]):
        factory.return_value.__enter__.return_value = ControlledModel()
        result = pipeline.reclassify(pair.conn, Config(), categories=['application_ack'], limit=None)
    assert result.prefiltered == 1
    assert result.classified == 1
    assert not result.errors
    receipts = {row['message_id']: row['category'] for row in pair.conn.execute('SELECT message_id,category FROM application_receipts')}
    assert receipts == {'platform': 'job_alert', 'employer': 'application_ack'}
    with patch.object(payments, 'today', return_value=date(2026, 11, 4)):
        assert payments.received_today(pair.conn) == 1
    report = payments.report(pair.conn, date(2026, 11, 2))
    bidder = report['bidders'][0]
    assert bidder['total'] == 1
    assert bidder['calculated_amount_cents'] == 6
    assert bidder['payment']['application_count'] == 2
    assert bidder['payment']['amount_cents'] == 12
    assert 'reconciliation' not in report
    assert 'raw_daily' not in report
    assert 'verified_total' not in bidder
