"""Company-only confirmations check all eligible company links."""
from datetime import date, datetime, timezone

import pytest

from mailcheck import db, native_sourcing as sheets, sourcing_activity, sourcing_verification as verification
from mailcheck.sourcing_fallbacks import candidate_rows
from tests.test_sourcing_fallbacks import records


def proposed(records,receipts):
    conn,account,*_=records
    return verification._combined_matching_plan(conn,candidate_rows(conn,[account]),receipts,early_since=date(2026,11,15))


@pytest.mark.parametrize('manual',[False,True])
def test_company_only_checks_every_role_and_preserves_shared_proof(records,monkeypatch,manual):
    conn,_,tab_id,job,receipt=records
    monkeypatch.setattr(verification.payments,'today',lambda:date(2026,11,23))
    ids={job('Modus Create','Engineer', 'https://jobs.test/engineer'),
         job('Modus Create','Architect','https://jobs.test/architect')}
    receipt('Modus Create LLC',None,'Thank you for applying to Modus Create. We are reviewing your application.',key='company-only')
    monkeypatch.setattr('mailcheck.sourcing_fallbacks.prepare_postings',lambda *a,**kw:None)
    if manual:
        tab=sheets.owned(conn,tab_id,{'role':'admin','bidder_id':None})
        result=verification.verify(conn,tab,'company-check',sheets.snapshot(conn,tab)['revision'],'2026-11-23')
        assert result['verification']['checked']==2
    else:
        assert verification.verify_all(conn,sample=False)['changed']==2
    saved=[tuple(r) for r in conn.execute('SELECT * FROM sourcing_check_activity ORDER BY row_id')]
    assert {r['row_id'] for r in conn.execute('SELECT * FROM sourcing_check_activity')}==ids
    assert {r['message_id'] for r in conn.execute('SELECT * FROM sourcing_check_activity')}=={'company-only'}
    before=conn.total_changes
    verification.verify_all(conn,sample=False)
    assert conn.total_changes==before
    assert [tuple(r) for r in conn.execute('SELECT * FROM sourcing_check_activity ORDER BY row_id')]==saved


def test_company_only_keeps_mailbox_company_and_date_boundaries(records):
    conn,account,_,job,receipt=records
    ids={job('Modus Create','Engineer','https://jobs.test/current'),
         job('Modus Create','Architect','https://jobs.test/recent','2026-11-22')}
    job('Modus Create','Engineer','https://jobs.test/old','2026-11-01')
    job('Other Company','Engineer','https://jobs.test/other')
    r=receipt('Modus Create LLC',None,'Thank you for applying to Modus Create.')
    assert set(proposed(records,[r]))==ids
    other=db.add_account(conn,label='other',email='other@example.test');conn.commit()
    assert not proposed(records,[{**r,'account_id':other}])


def test_saved_company_only_proof_can_check_later_company_rows(records):
    conn,_,_,job,receipt=records
    old=job('Modus Create','Engineer','https://jobs.test/old',checked=True)
    r=receipt('Modus Create LLC',None,'Thank you for applying to Modus Create.',key='saved-company')
    sourcing_activity.confirm(conn,old,datetime(2026,11,23,15,tzinfo=timezone.utc),'saved-company');conn.commit()
    saved=tuple(conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(old,)).fetchone())
    new=job('Modus Create','Architect','https://jobs.test/new')
    assert new in proposed(records,[r])
    assert tuple(conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(old,)).fetchone())==saved


def test_company_alias_without_role_checks_all_related_rows(records):
    _,_,_,job,receipt=records
    ids={job('WisdomAI','Engineer','https://jobs.test/a'),job('WisdomAI','Architect','https://jobs.test/b')}
    r=receipt('Wisdom AI',None,'Thank you for applying to Wisdom AI. Your application has been received.')
    assert set(proposed(records,[r]))==ids


@pytest.mark.parametrize('known',[False,True])
@pytest.mark.parametrize('location',['body','subject'])
def test_missing_role_with_explicit_job_identity_does_not_check_other_jobs(records,known,location):
    conn,_,_,job,receipt=records
    url='https://job-boards.greenhouse.io/modus/jobs/123456'
    a=job('Modus Create','Engineer',url)
    job('Modus Create','Architect',url.replace('123456','789012'))
    linked=url if known else url.replace('123456','999999')
    body='Thank you for applying to Modus Create. Your application has been received.'
    r=receipt('Modus Create LLC',None,body+(f' {linked}' if location=='body' else ''))
    if location=='subject':
        conn.execute('UPDATE messages SET subject=? WHERE account_id=? AND message_id=?',
                     ('Application received for Job ID: '+('123456' if known else '999999'),r['account_id'],r['message_id']))
        conn.commit()
    assert set(proposed(records,[r]))==({a} if known else set())
