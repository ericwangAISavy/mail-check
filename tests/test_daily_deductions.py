"""Workspace deduction policy, assignment days and settled-payment preservation."""
from datetime import date
from decimal import Decimal
from unittest.mock import patch
import pytest
from mailcheck import db,payments,sourcing_verification,config
from tests.web_client import TestClient,sign_in_bidder
from mailcheck.web.app import create_app


@pytest.fixture
def workspace(tmp_path,monkeypatch):
    path=tmp_path/'pay.db'
    monkeypatch.setattr(config,'db_path',lambda:path)
    monkeypatch.setattr(config,'config_dir',lambda:tmp_path)
    monkeypatch.setattr(config,'config_path',lambda:tmp_path/'config.toml')
    with db.session() as conn:
        account=db.add_account(conn,label='inbox',email='user@example.test')
        conn.execute("INSERT INTO bidders(name,created_at,pay_per_bid,adjustment_percent) VALUES('Alex','2026-01-01','0.05','20')")
        payments.assign(conn,1,payments.AssignmentBody(account_id=account,start_date=date(2026,11,2)))
        conn.commit()
        yield conn,account


def report(conn,account,counts,*,today=date(2026,11,9)):
    checks={(1,account,f'2026-11-{day:02d}'):count for day,count in counts.items()}
    with patch.object(payments,'today',return_value=today),patch.object(sourcing_verification,'completed_account_counts',return_value=checks):
        return payments.report(conn,date(2026,11,2),admin=True)


def test_deductions_are_flat_per_completed_weekday_and_capped_at_zero(workspace):
    conn,account=workspace
    payments.save_deduction_rule(conn,payments.DeductionRuleBody(minimum_daily=50,deduction_amount=Decimal('1.25')))
    result=report(conn,account,{2:50,3:49,4:0,5:60,6:50,7:0,8:0})
    bidder=result['bidders'][0]
    assert bidder['below_minimum_daily']==[False,True,True,False,False,False,False]
    assert bidder['deduction_daily']==[0,125,125,0,0,0,0]
    assert bidder['deduction_total_cents']==250
    assert bidder['gross_amount_cents']==1254
    assert bidder['calculated_amount_cents']==1004
    assert bidder['payable_amount_cents']==1004
    assert result['deduction_rule']=={'minimum_daily':50,'amount_cents':125}
    assert report(conn,account,{})['bidders'][0]['calculated_amount_cents']==0


def test_no_deduction_for_today_future_or_days_before_assignment(workspace):
    conn,account=workspace
    conn.execute("UPDATE bidder_assignments SET start_date='2026-11-03',end_date='2026-11-05'")
    payments.save_deduction_rule(conn,payments.DeductionRuleBody(minimum_daily=50,deduction_amount='2'))
    bidder=report(conn,account,{},today=date(2026,11,4))['bidders'][0]
    assert bidder['deduction_daily']==[0,200,0,0,0,0,0]
    assert bidder['below_minimum_daily']==[False,True,False,False,False,False,False]


def test_disabled_rule_and_zero_fee_highlighting(workspace):
    conn,account=workspace
    assert report(conn,account,{})['bidders'][0]['deduction_total_cents']==0
    payments.save_deduction_rule(conn,payments.DeductionRuleBody(minimum_daily=50,deduction_amount='0'))
    bidder=report(conn,account,{})['bidders'][0]
    assert bidder['below_minimum_daily']==[True]*5+[False]*2
    assert bidder['deduction_total_cents']==0


def test_saved_payments_overrides_and_read_only_reports_remain_intact(workspace):
    conn,account=workspace
    payments.save_deduction_rule(conn,payments.DeductionRuleBody(minimum_daily=50,deduction_amount='1'))
    conn.execute("INSERT INTO bidder_payment_amounts VALUES(1,'2026-11-02',999,10)")
    assert report(conn,account,{2:100})['bidders'][0]['payable_amount_cents']==999
    conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at) VALUES(1,'2026-11-02',10,777,'2026-11-09')")
    conn.commit()
    before=conn.total_changes
    conn.execute('PRAGMA query_only=ON')
    with patch.object(payments,'today',return_value=date(2026,11,9)):
        result=payments.report(conn,date(2026,11,2),read_only=True)
    assert result['bidders'][0]['payment']['amount_cents']==777
    assert result['bidders'][0]['payable_amount_cents']==777
    assert conn.total_changes==before


def test_rule_api_validation_persistence_and_bidder_write_denial(workspace):
    conn,_=workspace
    with TestClient(create_app()) as client:
        for body in ({'minimum_daily':-1,'deduction_amount':'1'}, {'minimum_daily':50,'deduction_amount':'0.001'}):
            assert client.post('/api/payments/deduction-rule',json=body).status_code==422
        response=client.post('/api/payments/deduction-rule',json={'minimum_daily':50,'deduction_amount':'1.25'})
        assert response.status_code==200,response.text
        assert payments.deduction_rule(conn)=={'minimum_daily':50,'amount_cents':125}
        sign_in_bidder(client)
        assert client.post('/api/payments/deduction-rule',json={'minimum_daily':0,'deduction_amount':'0'}).status_code==403


def test_multiple_assignments_do_not_multiply_daily_fee(workspace):
    conn,account=workspace
    second=db.add_account(conn,label='second',email='other@example.test')
    payments.assign(conn,1,payments.AssignmentBody(account_id=second,start_date=date(2026,11,2)))
    payments.save_deduction_rule(conn,payments.DeductionRuleBody(minimum_daily=50,deduction_amount='1.25'))
    assert report(conn,account,{})['bidders'][0]['deduction_total_cents']==625


def test_existing_database_gets_disabled_deduction_policy_on_upgrade(tmp_path):
    path=tmp_path/'old.db'
    conn=db.connect(path)
    conn.execute('DROP TABLE payment_deduction_rule')
    conn.execute('PRAGMA user_version=41')
    conn.commit();conn.close()
    conn=db.connect(path)
    try:
        assert payments.deduction_rule(conn)=={'minimum_daily':0,'amount_cents':0}
        assert conn.execute('PRAGMA user_version').fetchone()[0]==db.SCHEMA_VERSION
    finally:conn.close()
