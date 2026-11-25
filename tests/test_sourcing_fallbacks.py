"""Additive evidence must improve recall without changing old matching decisions."""
from datetime import date, datetime, timezone

import pytest

from mailcheck import db, native_sourcing as sheets, sourcing_activity
from mailcheck.models import Classification, NormalizedMessage
from mailcheck.sourcing_verification import _matching_plan


@pytest.fixture
def records(tmp_path):
    conn=db.connect(tmp_path/'mail.db')
    account=db.add_account(conn,label='personal',email='person@example.test')
    conn.execute("INSERT INTO bidders(id,name,created_at) VALUES(1,'Current','2026-11-01')")
    conn.commit()
    book=sheets.create_book(conn,1,'Applications')
    tab_id=sheets.create_tab(conn,book,account,'Profile')
    def job(company,role,link,day='2026-11-23',checked=False):
        tab=sheets.owned(conn,tab_id,{'role':'admin','bidder_id':None})
        snapshot=sheets.snapshot(conn,tab)
        result=sheets.append(conn,tab,sheets.new_id(),snapshot['revision'],[[company,role,link]],work_date=day)
        rid=next(r for r in reversed(result['row_ids']) if r and conn.execute('SELECT work_date FROM native_rows WHERE id=?',(r,)).fetchone()[0]==day
                 and conn.execute("SELECT 1 FROM native_cells c JOIN native_columns k ON k.id=c.column_id WHERE c.row_id=? AND k.kind='link' AND c.value=?",(r,link)).fetchone())
        if checked:
            col=next(k['id'] for k in result['columns'] if k['kind']=='check')
            conn.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?) ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value',(rid,col,'true'))
            conn.commit()
        return rid
    def receipt(company,role,body=None,key=None,stamp='2026-11-23T15:00:00+00:00',account_id=None):
        key=key or sheets.new_id()
        aid=account_id or account
        pk=db.upsert_message(conn,NormalizedMessage(account_id=aid,account_label='personal',message_id=key,uid=key,folder='INBOX',from_addr='no-reply@us.greenhouse-mail.io',from_name='Recruiting',subject='Thank you for applying',date_utc=datetime.fromisoformat(stamp),body=body or f'Thank you for applying for the {role} role at {company}. Your application has been received.'))
        db.save_classification(conn,pk,Classification('application_ack',company=company,role=role),'test','1')
        return dict(account_id=aid,message_id=key,received_at=stamp,company=company or '',role=role or '')
    yield conn,account,tab_id,job,receipt
    conn.close()


def plan(records,receipts,postings=None):
    from mailcheck.sourcing_fallbacks import candidate_rows,extend_plan
    conn,*_=records
    rows=candidate_rows(conn,{r['account_id'] for r in receipts})
    legacy=_matching_plan(conn,rows,receipts,early_since=date(2026,11,14))
    evidence={}
    combined=extend_plan(conn,rows,receipts,legacy,early_since=date(2026,11,14),postings=postings or {},evidence=evidence)
    return legacy,combined,evidence


def test_original_bindings_win_and_alias_is_additive(records):
    _,_,_,job,receipt=records
    old=job('Acme','Engineer','https://jobs.test/acme')
    new=job('WisdomAI','Machine Learning Engineer','https://jobs.test/wisdom')
    receipts=[receipt('Acme','Engineer'),receipt('Wisdom AI','Machine Learning Engineer')]
    legacy,combined,evidence=plan(records,receipts)
    assert set(legacy)=={old}
    assert combined[old]==legacy[old]
    assert set(combined)=={old,new}
    assert evidence[new]['rule']=='company_alias'


def test_unique_unchecked_candidate_does_not_move_old_proof(records):
    conn,_,_,job,receipt=records
    old=job('AlphaSense','Staff AI Platform Engineer','https://jobs.test/old','2026-11-19',True)
    sourcing_activity.confirm(conn,old,datetime(2026,11,19,15,tzinfo=timezone.utc),'old-proof')
    conn.commit()
    new=job('AlphaSense','Staff AI Platform Engineer','https://jobs.test/new')
    r=receipt('AlphaSense','Staff AI Platform Engineer')
    legacy,combined,evidence=plan(records,[r])
    assert set(legacy)=={old,new}
    assert set(combined)=={old,new}
    assert combined[new]==legacy[new]
    assert conn.execute('SELECT message_id FROM sourcing_check_activity WHERE row_id=?',(old,)).fetchone()[0]=='old-proof'


def test_reserved_receipt_can_check_another_matching_company_alias(records):
    conn,_,_,job,receipt=records
    r=receipt('Wisdom AI','Engineer',key='reserved')
    old=job('Wisdom AI','Engineer','https://jobs.test/old',checked=True)
    sourcing_activity.confirm(conn,old,datetime(2026,11,23,15,tzinfo=timezone.utc),'reserved')
    conn.commit()
    new=job('WisdomAI','Engineer','https://jobs.test/new')
    _,combined,evidence=plan(records,[r])
    assert new in combined
    assert evidence[new]['rule']=='company_alias'


@pytest.mark.parametrize('company,saved,role,body',[
    ('Robots and Pencils','Robots & Pencils','Staff AI Developer - Canada','Thank you for applying for our Staff AI Developer - Canada at Robots & Pencils.'),
    ('Code.org','CodeAI','Software Engineer, Teacher Experience','Thank you for your interest in CodeAI. We received your application for the Software Engineer, Teacher Experience role.'),
    ('CCC Intelligent Solutions','EvolutionIQ','Senior Software Engineer','Thanks for your application to the Senior Software Engineer position. We appreciate your interest in an opportunity here at EvolutionIQ.'),
])
def test_explicit_body_employer_or_company_formatting(records,company,saved,role,body):
    _,_,_,job,receipt=records
    rid=job(saved,role,'https://jobs.test/job')
    _,combined,_=plan(records,[receipt(company,role,body)])
    assert rid in combined


@pytest.mark.parametrize('company,role,url,title',[
    ('Coretelligent','AI Architecture Lead','https://job-boards.greenhouse.io/embed/job_app?for=coretelligent&token=5487133008','AI Architecture Delivery Lead'),
    ('WEKA','Tech Lead - AI Inference','https://job-boards.greenhouse.io/embed/job_app?for=wekatest&token=5085240007','Sr Staff Software Engineer - AI Inference'),
    ('EliseAI','Job Recommendations | Jobright AI','https://jobs.ashbyhq.com/eliseai/efc949ef-22ce-401c-8161-091e387e776d/application','Staff Software Engineer'),
])
def test_verified_posting_title_recovers_stale_sheet_title(records,company,role,url,title):
    from mailcheck.sourcing_postings import posting_key
    _,_,_,job,receipt=records
    rid=job(company,role,url)
    _,combined,evidence=plan(records,[receipt(company,title)],{posting_key(url):{'title':title,'company':company,'url':url}})
    assert rid in combined
    assert evidence[rid]['rule']=='posting_title'


def test_company_only_rename_matches_explicit_employer_evidence(records):
    _,_,_,job,receipt=records
    rid=job('Pure Storage','Principal Software Engineer','https://jobs.test/job')
    _,combined,_=plan(records,[receipt('Everpure',None,'Thanks for your interest in Everpure (formerly Pure Storage). Your resume will be reviewed.')])
    assert rid in combined


def test_distinct_ids_with_same_company_and_title_share_confirmation(records):
    _,_,_,job,receipt=records
    a=job('Dragos','Engineer','https://job-boards.greenhouse.io/dragos/jobs/5477258008')
    b=job('Dragos','Engineer','https://job-boards.greenhouse.io/dragos/jobs/5364876008')
    _,combined,_=plan(records,[receipt('Dragos','Engineer')])
    assert set(combined)=={a,b}


def test_exact_job_identity_extends_date_window(records):
    _,_,_,job,receipt=records
    url='https://job-boards.greenhouse.io/acme/jobs/5477258008'
    rid=job('Acme','Engineer',url,'2026-11-01')
    _,combined,evidence=plan(records,[receipt('Acme','Engineer',f'Your application has been received. Application: {url}?utm_source=email')])
    assert rid in combined
    assert evidence[rid]['rule']=='job_identity'


def test_missing_company_can_be_recovered_from_exact_posting_link(records):
    _,_,_,job,receipt=records
    url='https://job-boards.greenhouse.io/acme/jobs/5477258008'
    rid=job('Acme','Engineer',url)
    _,combined,_=plan(records,[receipt(None,'Engineer',f'Your application for Engineer has been received. {url}')])
    assert rid in combined


def test_reapplication_and_other_mailbox_are_not_new_fallback_credits(records):
    conn,_,_,job,receipt=records
    rid=job('WisdomAI','Engineer','https://jobs.test/job')
    other=db.add_account(conn,label='other',email='other@example.test');conn.commit()
    for r in [receipt('Wisdom AI','Engineer','You have applied again. This application has overwritten the previous one.'),receipt('Wisdom AI','Engineer',account_id=other)]:
        _,combined,_=plan(records,[r])
        assert rid not in combined


def test_manual_verification_persists_proof_and_is_idempotent(records,monkeypatch):
    from mailcheck import sourcing_verification as verification
    conn,_,tab_id,job,receipt=records
    rid=job('WisdomAI','Engineer','https://jobs.test/job')
    r=receipt('Wisdom AI','Engineer')
    monkeypatch.setattr(verification.payments,'today',lambda:date(2026,11,23))
    tab=sheets.owned(conn,tab_id,{'role':'admin','bidder_id':None})
    original_revision=str(tab['revision'])
    first=verification.verify(conn,tab,'verify-1',original_revision,'2026-11-23')
    assert len(first['verification']['fallback_matches'])==1
    proof=dict(conn.execute('SELECT * FROM sourcing_match_evidence WHERE row_id=?',(rid,)).fetchone())
    assert proof['rule']=='company_alias' and proof['message_id']==r['message_id']
    tab=sheets.owned(conn,tab_id,{'role':'admin','bidder_id':None})
    again=verification.verify(conn,tab,'verify-1',original_revision,'2026-11-23')
    assert again['revision']==first['revision']
    assert dict(conn.execute('SELECT * FROM sourcing_match_evidence WHERE row_id=?',(rid,)).fetchone())==proof


def test_scoped_global_check_can_add_explicit_historical_identity_without_network(records,monkeypatch):
    from mailcheck import sourcing_verification as verification
    from mailcheck import sourcing_postings
    conn,_,_,job,receipt=records
    url='https://job-boards.greenhouse.io/acme/jobs/123456'
    rid=job('Acme','Engineer',url,'2026-11-01')
    receipt('Acme','Engineer',f'Your application has been received. {url}')
    monkeypatch.setattr(sourcing_postings,'fetch_posting',lambda *_:pytest.fail('A passive report must not fetch posting metadata'))
    result=verification.verify_all(conn,refresh_since=date(2026,11,23),refresh_until=date(2026,11,29),week_only=True,sample=False)
    assert result['fallback_checked']==1
    assert conn.execute('SELECT rule FROM sourcing_match_evidence WHERE row_id=?',(rid,)).fetchone()[0]=='job_identity'


def test_repeated_alias_receipts_do_not_count_twice(records):
    _,_,_,job,receipt=records
    rid=job('WisdomAI','Engineer','https://jobs.test/job')
    a=receipt('Wisdom AI','Engineer',stamp='2026-11-23T15:00:00+00:00')
    b=receipt('Wisdom AI','Engineer',stamp='2026-11-23T16:00:00+00:00')
    _,combined,_=plan(records,[a,b])
    assert set(combined)=={rid}
    assert combined[rid][1]==a['message_id']


def test_matching_company_and_role_share_confirmation_even_with_different_identity(records):
    _,_,_,job,receipt=records
    job('Acme','Engineer','https://job-boards.greenhouse.io/acme/jobs/123456',checked=True)
    wrong=job('Acme','Engineer','https://job-boards.greenhouse.io/acme/jobs/789012')
    r=receipt('Acme','Engineer','Your application for Engineer at Acme has been received. https://job-boards.greenhouse.io/acme/jobs/123456')
    _,combined,_=plan(records,[r])
    assert wrong in combined


def test_exact_verified_qualifier_resolves_different_ats_ids(records):
    from mailcheck.sourcing_postings import posting_key
    _,_,_,job,receipt=records
    a='https://job-boards.greenhouse.io/robotsandpencils/jobs/5349912008'
    b='https://job-boards.greenhouse.io/robotsandpencils/jobs/5486500008'
    old=job('Robots & Pencils','Staff AI Developer',a,'2026-11-19')
    canada=job('Robots & Pencils','Staff AI Developer',b)
    r=receipt('Robots and Pencils','Staff AI Developer - Canada')
    _,combined,_=plan(records,[r],{posting_key(a):{'title':'Staff AI Developer','company':'Robots and Pencils'},posting_key(b):{'title':'Staff AI Developer - Canada','company':'Robots and Pencils'}})
    assert canada in combined and old not in combined


def test_company_only_matches_do_not_need_posting_title_requests(records,monkeypatch):
    from mailcheck.sourcing_fallbacks import prepare_postings
    from mailcheck.sourcing_postings import cached_postings,posting_key
    from mailcheck import sourcing_postings
    conn,_,_,job,receipt=records
    url='https://job-boards.greenhouse.io/acme/jobs/123456'
    rid=job('Acme','Outdated Jobright heading',url)
    second=job('Acme','Data Scientist','https://job-boards.greenhouse.io/acme/jobs/789012')
    r=receipt('Acme',None,'Your application for Staff Software Engineer at Acme has been received.')
    monkeypatch.setattr(sourcing_postings,'fetch_posting',lambda link:pytest.fail('Company-only match should not fetch posting titles'))
    prepare_postings(conn,since=date(2026,11,23),until=date(2026,11,23))
    facts=cached_postings(conn,[posting_key(url)])
    assert not facts
    assert set(plan(records,[r],facts)[1])=={rid,second}


def test_labelled_uuid_is_a_historical_job_reference(records):
    _,_,_,job,receipt=records
    uid='efc949ef-22ce-401c-8161-091e387e776d'
    rid=job('Acme','Engineer','https://jobs.ashbyhq.com/acme/'+uid,'2026-11-01')
    r=receipt('Acme','Engineer','Your application for Engineer at Acme has been received. Job ID: '+uid)
    _,combined,evidence=plan(records,[r])
    assert rid in combined
    assert evidence[rid]['rule']=='job_identity'


def test_read_only_diagnostic_includes_additive_rules(records,monkeypatch):
    from tools.explain_application_matches import explain
    from mailcheck import payments
    conn,_,_,job,receipt=records
    rid=job('WisdomAI','Engineer','https://jobs.test/job')
    receipt('Wisdom AI','Engineer')
    monkeypatch.setattr(payments,'today',lambda:date(2026,11,23))
    path=conn.execute('PRAGMA database_list').fetchone()[2]
    result=explain(path,'person@example.test','WisdomAI')
    row=next(row for row in result['rows'] if row['id']==rid)
    assert row['would_add_check'] and row['matching_rule']=='company_alias'


def test_metadata_scope_is_applied_before_busy_other_mailbox_limit(records,monkeypatch):
    from mailcheck.sourcing_fallbacks import prepare_postings
    import mailcheck.sourcing_fallbacks as fallback
    conn,account,_,job,receipt=records
    url='https://job-boards.greenhouse.io/acme/jobs/123456'
    job('Acme','Stale heading',url)
    receipt('Acme','Staff Engineer')
    other=db.add_account(conn,label='busy',email='busy@example.test')
    conn.executemany("INSERT INTO application_receipts(account_id,message_id,received_at,category,company,role) VALUES(?,?,'2026-11-23T16:00:00+00:00','application_ack','Other','Engineer')",[(other,f'busy-{i}') for i in range(1001)])
    conn.commit()
    selected=[]
    monkeypatch.setattr(fallback,'warm_postings',lambda _,urls:selected.extend(urls))
    prepare_postings(conn,since=date(2026,11,23),until=date(2026,11,23),accounts={account})
    assert url in selected
