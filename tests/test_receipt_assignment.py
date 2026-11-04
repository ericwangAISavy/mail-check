from datetime import date
import pytest
from mailcheck import sourcing_verification as verification
from tests import test_sourcing_verification as fixtures


@pytest.fixture
def sheet():
    case = fixtures.SourcingVerificationTests()
    case.setUp()
    try:
        yield case
    finally:
        case.doCleanups()


def add_rows(sheet, values):
    base = sheet.snapshot()
    return sheet.native.append(sheet.conn, sheet.tab(), 'assignment-jobs', base['revision'],
                               values, work_date='2026-10-20')


@pytest.mark.parametrize('manual', [False, True])
def test_one_receipt_does_not_check_two_different_jobs(sheet, manual):
    base = add_rows(sheet, [['Acme','Engineer','https://jobs.test/1'],
                           ['Acme','Engineer','https://jobs.test/2']])
    sheet.receipt('one-receipt','Acme','2026-10-20T12:00:00+00:00')
    sheet.conn.commit()
    if manual:
        verification.verify(sheet.conn,sheet.tab(),'check',base['revision'],'2026-10-20')
    else:
        verification.verify_all(sheet.conn,sample=False)
    assert [row[3]['value'] for row in sheet.snapshot()['rows'][1:3]] == ['false','false']


def test_existing_check_is_preserved_when_another_row_creates_ambiguity(sheet):
    add_rows(sheet, [['Acme','Engineer','https://jobs.test/1']])
    sheet.receipt('one-receipt','Acme','2026-10-20T12:00:00+00:00')
    sheet.conn.commit()
    verification.verify_all(sheet.conn,sample=False)
    before = sheet.snapshot()
    sheet.native.append(sheet.conn,sheet.tab(),'more',before['revision'],
                        [['Acme','Engineer','https://jobs.test/2']],work_date='2026-10-20')
    verification.verify_all(sheet.conn,sample=False)
    assert [row[3]['value'] for row in sheet.snapshot()['rows'][1:3]] == ['true','false']


def test_shared_receipt_does_not_check_jobs_in_other_tabs(sheet):
    add_rows(sheet, [['Acme','Engineer','https://jobs.test/1']])
    other_book = sheet.native.create_book(sheet.conn,2)
    other_id = sheet.native.create_tab(sheet.conn,other_book,sheet.account_id,'Another tab')
    other = sheet.native.owned(sheet.conn,other_id,sheet.principal)
    base = sheet.native.snapshot(sheet.conn,other)
    sheet.native.append(sheet.conn,other,'other-jobs',base['revision'],
                        [['Acme','Engineer','https://jobs.test/2']],work_date='2026-10-20')
    sheet.receipt('one-receipt','Acme','2026-10-20T12:00:00+00:00')
    sheet.conn.commit()
    verification.verify_all(sheet.conn,sample=False)
    assert sheet.snapshot()['rows'][1][3]['value'] == 'false'
    assert sheet.native.snapshot(sheet.conn,other)['rows'][1][3]['value'] == 'false'


def test_safe_seniority_alias_matches_without_broad_fuzzy_matching(sheet):
    add_rows(sheet, [['Acme','Senior Software Engineer','https://jobs.test/1']])
    sheet.receipt('one-receipt','Acme','2026-10-20T12:00:00+00:00',role='Sr. Software Engineer')
    sheet.conn.commit()
    verification.verify_all(sheet.conn,sample=False)
    assert sheet.snapshot()['rows'][1][3]['value'] == 'true'
    assert verification.role_key('Junior Engineer') != verification.role_key('Senior Engineer')


def test_two_emails_for_one_job_keep_earliest_match(sheet):
    add_rows(sheet, [['Acme','Engineer','https://jobs.test/1']])
    sheet.receipt('first','Acme','2026-10-20T12:00:00+00:00')
    sheet.receipt('extra','Acme','2026-10-20T12:01:00+00:00')
    sheet.conn.commit()
    verification.verify_all(sheet.conn,sample=False)
    assert sheet.snapshot()['rows'][1][3]['value'] == 'true'
    assert sheet.conn.execute('SELECT message_id FROM sourcing_check_activity').fetchone()[0] == 'first'


def test_report_separates_extra_emails_and_preserves_receipt_payment_basis(sheet):
    from mailcheck import payments
    add_rows(sheet, [['Acme','Engineer','https://jobs.test/1']])
    sheet.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')",(sheet.account_id,))
    sheet.receipt('original','Acme','2026-10-20T12:00:00+00:00')
    sheet.receipt('extra','Acme','2026-10-20T12:01:00+00:00')
    sheet.conn.commit()
    verification.verify_all(sheet.conn,sample=False)
    report = payments.report(sheet.conn,date(2026,10,19),admin=True)
    bidder = next(row for row in report['bidders'] if row['id']==1)
    assert bidder['daily'][1] == 2
    assert bidder['checked_daily'][1] == 1
    assert 'verified_daily' not in bidder
    assert 'verified_total' not in bidder
    assert 'raw_daily' not in bidder
    assert 'reconciliation' not in report
    assert 'raw_daily' not in report


def test_weekly_refresh_cannot_broadcast_into_archived_rows(sheet):
    add_rows(sheet, [['Acme','Engineer','https://jobs.test/1'],
                     ['Acme','Engineer','https://jobs.test/2']])
    sheet.receipt('only','Acme','2026-10-20T12:00:00+00:00')
    sheet.conn.execute('UPDATE native_tabs SET archived=1 WHERE id=?',(sheet.tab_id,))
    sheet.conn.commit()
    verification.verify_all(sheet.conn,refresh_since=date(2026,10,19),
                            refresh_until=date(2026,10,25),week_only=True,sample=False)
    assert [row[3]['value'] for row in sheet.snapshot()['rows'][1:3]] == ['false','false']


def test_read_only_report_does_not_rewrite_recorded_payment(sheet):
    from mailcheck import payments
    add_rows(sheet, [['Acme','Engineer','https://jobs.test/1']])
    sheet.conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(1,?,'personal','2026-10-01')",(sheet.account_id,))
    sheet.receipt('first','Acme','2026-10-20T12:00:00+00:00')
    sheet.receipt('extra','Acme','2026-10-20T12:01:00+00:00')
    sheet.conn.commit()
    verification.verify_all(sheet.conn,sample=False)
    sheet.conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(1,'2026-10-19',99,1234,'2026-10-27T12:00:00Z','Recorded before reconciliation')")
    sheet.conn.commit()
    before = sheet.conn.total_changes
    sheet.conn.execute('PRAGMA query_only=ON')
    report = payments.report(sheet.conn,date(2026,10,19),read_only=True)
    bidder = next(row for row in report['bidders'] if row['id']==1)
    assert 'verified_total' not in bidder
    assert 'reconciliation' not in report
    assert bidder['total'] == 2
    assert bidder['payment']['application_count'] == 99
    assert bidder['payment']['amount_cents'] == 1234
    assert sheet.conn.total_changes == before
