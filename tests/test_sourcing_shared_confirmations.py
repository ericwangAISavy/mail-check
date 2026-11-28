"""A role-qualified confirmation checks every eligible matching sheet row."""
from datetime import date, datetime, timezone

import pytest

from mailcheck import native_sourcing as sheets, sourcing_activity, sourcing_verification as verification
from mailcheck.sourcing_fallbacks import candidate_rows
from tests.test_sourcing_fallbacks import records


def proposed(records, receipts):
    conn,account,*_=records
    return verification._combined_matching_plan(conn,candidate_rows(conn,[account]),receipts,early_since=date(2026,11,15))


def test_one_role_confirmation_checks_three_distinct_job_ids(records):
    _,_,_,job,receipt=records
    ids={job('Kendra Scott','Lead AI/ML Engineer',f'https://jobs.test/{n}') for n in range(3)}
    wrong_role=job('Kendra Scott','Accountant','https://jobs.test/accountant')
    too_old=job('Kendra Scott','Lead AI/ML Engineer','https://jobs.test/old','2026-11-01')
    r=receipt('Kendra Scott','Lead AI/ML Engineer')
    result=proposed(records,[r])
    assert set(result)==ids
    assert wrong_role not in result and too_old not in result
    assert {match[1] for match in result.values()}=={r['message_id']}


@pytest.mark.parametrize('manual',[False,True])
def test_shared_proof_is_persisted_and_repeat_check_does_not_rewrite_it(records,monkeypatch,manual):
    conn,account,tab_id,job,receipt=records
    monkeypatch.setattr(verification.payments,'today',lambda:date(2026,11,23))
    ids={job('Kendra Scott','Lead AI/ML Engineer',f'https://jobs.test/{n}') for n in range(3)}
    r=receipt('Kendra Scott','Lead AI/ML Engineer')
    monkeypatch.setattr('mailcheck.sourcing_fallbacks.prepare_postings',lambda *a,**kw:None)
    if manual:
        tab=sheets.owned(conn,tab_id,{'role':'admin','bidder_id':None})
        snap=sheets.snapshot(conn,tab)
        result=verification.verify(conn,tab,'check-all',snap['revision'],'2026-11-23')
        assert result['verification']['checked']==3
    else:
        assert verification.verify_all(conn,sample=False)['changed']==3
    saved=[tuple(row) for row in conn.execute('SELECT * FROM sourcing_check_activity ORDER BY row_id')]
    assert {row['row_id'] for row in conn.execute('SELECT * FROM sourcing_check_activity')}==ids
    assert {row['message_id'] for row in conn.execute('SELECT * FROM sourcing_check_activity')}=={r['message_id']}
    before=conn.total_changes
    verification.verify_all(conn,sample=False)
    assert conn.total_changes==before
    assert [tuple(row) for row in conn.execute('SELECT * FROM sourcing_check_activity ORDER BY row_id')]==saved


def test_existing_confirmation_can_check_another_matching_job_without_moving_old_proof(records):
    conn,_,_,job,receipt=records
    old=job('Kendra Scott','Engineer','https://jobs.test/old',checked=True)
    r=receipt('Kendra Scott','Engineer',key='shared-proof')
    sourcing_activity.confirm(conn,old,datetime(2026,11,23,15,tzinfo=timezone.utc),'shared-proof');conn.commit()
    saved=tuple(conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(old,)).fetchone())
    new=job('Kendra Scott','Engineer','https://jobs.test/new')
    assert set(proposed(records,[r]))=={old,new}
    assert tuple(conn.execute('SELECT * FROM sourcing_check_activity WHERE row_id=?',(old,)).fetchone())==saved


def test_alias_fallback_can_check_multiple_matching_rows(records):
    _,_,_,job,receipt=records
    ids={job('WisdomAI','Engineer',f'https://jobs.test/{n}') for n in range(3)}
    assert set(proposed(records,[receipt('Wisdom AI','Engineer')]))==ids


def test_saved_alias_confirmation_can_check_later_matching_rows(records):
    conn,_,_,job,receipt=records
    old=job('WisdomAI','Engineer','https://jobs.test/old',checked=True)
    r=receipt('Wisdom AI','Engineer',key='alias-proof')
    sourcing_activity.confirm(conn,old,datetime(2026,11,23,15,tzinfo=timezone.utc),'alias-proof');conn.commit()
    new=job('WisdomAI','Engineer','https://jobs.test/new')
    assert new in proposed(records,[r])


def test_alias_confirmation_extends_a_main_match_to_other_matching_rows(records):
    _,_,_,job,receipt=records
    a=job('Wisdom AI','Engineer','https://jobs.test/spaced')
    b=job('WisdomAI','Engineer','https://jobs.test/compact')
    assert set(proposed(records,[receipt('Wisdom AI','Engineer')]))=={a,b}


def test_explicit_link_does_not_block_other_company_role_alias_matches(records):
    _,_,_,job,receipt=records
    url='https://job-boards.greenhouse.io/wisdom/jobs/123456'
    a=job('WisdomAI','Engineer',url)
    b=job('WisdomAI','Engineer',url.replace('123456','789012'))
    r=receipt('Wisdom AI','Engineer',f'Your application for Engineer at Wisdom AI has been received. {url}')
    assert set(proposed(records,[r]))=={a,b}


def test_historical_brassring_duplicates_are_all_checked(records,monkeypatch):
    conn,_,tab_id,job,receipt=records
    monkeypatch.setattr(verification.payments,'today',lambda:date(2026,11,23))
    url='https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?partnerid=26224&siteid=5247&jobid=1442605'
    first=job('Kendra Scott','Lead AI/ML Engineer',url)
    # Reconstruct duplicates saved before identity-aware incoming filtering.
    second=sheets.new_id()
    conn.execute('INSERT INTO native_rows(id,tab_id,position,work_date) SELECT ?,tab_id,position+100,work_date FROM native_rows WHERE id=?',(second,first))
    conn.execute('INSERT INTO native_cells(row_id,column_id,value) SELECT ?,column_id,value FROM native_cells WHERE row_id=?',(second,first))
    conn.execute("UPDATE native_cells SET value=replace(value,'5247','5251') WHERE row_id=?",(second,));conn.commit()
    receipt('Kendra Scott','Lead AI/ML Engineer','Your resume has been received for Lead AI/ML Engineer 11992BR at Kendra Scott.')
    assert verification.verify_all(conn,sample=False)['changed']==2
    assert {row['row_id'] for row in conn.execute('SELECT * FROM sourcing_check_activity')}=={first,second}


def test_saved_proof_does_not_spread_after_company_reclassification(records):
    conn,_,_,job,receipt=records
    old=job('Original Company','Engineer','https://jobs.test/old',checked=True)
    r=receipt('Wisdom AI','Engineer',key='changed-company')
    sourcing_activity.confirm(conn,old,datetime(2026,11,23,15,tzinfo=timezone.utc),'changed-company');conn.commit()
    new=job('WisdomAI','Engineer','https://jobs.test/new')
    assert new not in proposed(records,[r])


def test_company_only_confirmation_checks_all_matching_roles(records):
    _,_,_,job,receipt=records
    ids={job('Kendra Scott','Engineer','https://jobs.test/engineer'),
         job('Kendra Scott','Accountant','https://jobs.test/accountant')}
    assert set(proposed(records,[receipt('Kendra Scott',None,'Your application has been received.')]))==ids
