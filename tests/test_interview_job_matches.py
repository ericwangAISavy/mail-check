import sqlite3
import pytest
from mailcheck import db, native_sourcing, payments, sourcing_activity


def fixture():
    c = sqlite3.connect(':memory:')
    c.row_factory = sqlite3.Row
    for schema in (db.SCHEMA, payments.SCHEMA, native_sourcing.SCHEMA, sourcing_activity.SCHEMA):
        c.executescript(schema)
    for i in (1, 2):
        c.execute("INSERT INTO accounts(id,label,email,created_at) VALUES(?,?,?,'2020')", (i, f'Account {i}', f'{i}@example.com'))
        c.execute("INSERT INTO bidders(id,name,created_at) VALUES(?,?,'2020')", (i, f'Bidder {i}'))
        c.execute("INSERT INTO native_books(id,bidder_id,title) VALUES(?,?,'History')", (i,i))
        c.execute("INSERT INTO native_tabs(id,book_id,account_id,account_label,title,updated_at,archived) VALUES(?,?,1,'Account 1','Jobs',0,1)", (i,i))
        for kind in ('company','role','link','check'):
            c.execute("INSERT INTO native_columns(id,tab_id,position,title,kind) VALUES(?,?,0,?,?)", (f'{i}-{kind}',i,kind,kind))
    return c


def add(c, name, tab=1, company='Acme', role='Backend Engineer', link='https://jobs.example.com/42?job=7#apply', checked='true', day='2020-01-01'):
    c.execute('INSERT INTO native_rows VALUES(?,?,0,?)', (name,tab,day))
    for kind,value in zip(('company','role','link','check'), (company,role,link,checked)):
        c.execute('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)', (name,f'{tab}-{kind}',value))


def match(c, **kwargs):
    from mailcheck.interview_job_matches import match_jobs
    return match_jobs(c, {'company':'Acme','role':'Backend Engineer','start_at':'2025-01-01T12:00:00Z'}, [{'account_id':1,'source_received_at':'2024-12-01T12:00:00Z'}], **kwargs)


def test_history_multiple_bidders_archived_unchecked_and_pagination():
    c=fixture()
    add(c,'a'); add(c,'b',tab=2); add(c,'c',checked='false')
    add(c,'future',day='2099-01-01')
    first=match(c,limit=1)
    assert first['total']==3
    all_rows=first['matches']
    while first['next_cursor']:
        first=match(c,limit=1,cursor=first['next_cursor']); all_rows+=first['matches']
    assert {r['row_id'] for r in all_rows}=={'a','b','c'}
    assert {r['bidder_name'] for r in all_rows}=={'Bidder 1','Bidder 2'}
    assert all(r['archived'] for r in all_rows)
    assert next(r for r in all_rows if r['row_id']=='c')['applied'] is False


def test_generic_roles_and_account_isolation():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company='Unrelated')
    assert match(c)['total']==0
    assert match_jobs(c, {'role':'Engineer'}, [{'account_id':1}])['total']==0
    assert match_jobs(c, {'company':'Acme'}, [])['total']==0
    assert match_jobs(c, {'company':'Acme'}, [{'account_id':2}])['total']==0


def test_exact_url_preserves_functional_parameters_and_unknown_dates():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company='Other',day=None)
    result=match_jobs(c, {}, [{'account_id':1,'source_subject':'Job https://jobs.example.com/42?job=7&utm_source=mail#apply'}])
    assert result['total']==1
    assert result['matches'][0]['confidence']=='possible'
    assert result['matches'][0]['link']=='https://jobs.example.com/42?job=7#apply'
    with pytest.raises(ValueError):
        match(c,cursor='bad')


def test_source_evidence_never_crosses_accounts_and_booking_description_matches():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company='Other',role='Other')
    c.execute("INSERT INTO calendar_analysis_tasks(account_id,external_id,version,booking,start_at,last_seen) VALUES(1,'native:42','v',?,'2025',0)", ('{"description":"https://jobs.example.com/42?job=7#apply"}',))
    assert match_jobs(c, {}, [{'account_id':1,'external_message_id':'native:42'}])['total']==1
    assert match_jobs(c, {}, [{'account_id':1,'external_message_id':'different'}, {'account_id':2,'source_subject':'https://jobs.example.com/42?job=7#apply'}])['total']==0


def test_confirmed_completion_overrides_future_work_date_and_role_conflict_is_possible():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',day='2099-01-01',role='Accountant')
    c.execute("INSERT INTO sourcing_check_activity(row_id,bidder_id,source,confirmed_at) VALUES('a',1,'mail','2020-01-02T10:00:00Z')")
    result=match_jobs(c, {'company':'Acme','role':'Backend Engineer'}, [{'account_id':1,'source_subject':'https://jobs.example.com/42?job=7#apply'}])
    assert result['total']==1
    assert result['matches'][0]['application_date']=='2020-01-02'
    assert result['matches'][0]['confidence']=='possible'


def test_cursor_validation_and_unsafe_urls():
    import base64
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',link='https://user:password@example.com/42')
    assert match(c)['total']==0
    for cursor in ('!', 'x'*3000, base64.urlsafe_b64encode(b'{}').decode(), base64.urlsafe_b64encode(b'[1,0,[],"a"]').decode()):
        with pytest.raises(ValueError):
            match(c,cursor=cursor)


def test_retained_description_scoped_to_source_id():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company='Other',role='Other')
    c.execute('CREATE TABLE IF NOT EXISTS interview_source_details(source_id INTEGER PRIMARY KEY,description TEXT NOT NULL)')
    c.execute("INSERT INTO interview_source_details VALUES(7,'https://jobs.example.com/42?job=7#apply')")
    assert match_jobs(c, {}, [{'id':7,'account_id':1}])['total']==1


def test_confirmation_after_invitation_excluded_even_with_older_work_date():
    c=fixture(); add(c,'a')
    c.execute("INSERT INTO sourcing_check_activity(row_id,bidder_id,source,confirmed_at) VALUES('a',1,'mail','2025-01-02T10:00:00Z')")
    assert match(c)['total']==0


def test_sparse_missing_check_column_keeps_saved_job():
    c=fixture(); add(c,'a')
    c.execute("DELETE FROM native_cells WHERE column_id='1-check'")
    c.execute("DELETE FROM native_columns WHERE id='1-check'")
    result=match(c)
    assert result['total']==1
    assert result['matches'][0]['applied'] is False


def test_company_only_native_title_is_possible_and_returns_multiple_history():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a'); add(c,'b',tab=2)
    result=match_jobs(c, {'company':'Acme'}, [{'account_id':1,'source_subject':'Acme recruiter screen'}])
    assert result['total']==2
    assert all(row['confidence']=='possible' for row in result['matches'])


@pytest.mark.parametrize('company',['Unknown','Confidential','Company','Client','Recruitment','Staffing'])
def test_generic_companies_do_not_match_without_explicit_url(company):
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company=company)
    assert match_jobs(c, {'company':company,'role':'Backend Engineer'}, [{'account_id':1}])['total']==0


def test_unicode_company_names_and_query_order_match():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company='株式会社テスト',link='https://jobs.example.com/42?z=1&job=7#apply')
    assert match_jobs(c, {'company':'株式会社テスト','role':'Backend Engineer'}, [{'account_id':1}])['total']==1
    assert match_jobs(c, {}, [{'account_id':1,'source_subject':'https://jobs.example.com/42?job=7&z=1#apply'}])['total']==1


def test_observed_date_cannot_turn_unchecked_future_work_into_past_application():
    c=fixture(); add(c,'a',day='2099-01-01',checked='false')
    c.execute("INSERT INTO sourcing_check_activity(row_id,bidder_id,source,detected_at) VALUES('a',1,'observed','2020-01-02T10:00:00Z')")
    assert match(c)['total']==0


def test_long_urls_rejected():
    c=fixture();add(c,'a',link='https://jobs.example.com/'+('x'*4000))
    assert match(c)['total']==0


def test_explicit_url_with_unrelated_company_is_possible():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture(); add(c,'a',company='Other Corp')
    result=match_jobs(c, {'company':'Acme','role':'Backend Engineer'}, [{'account_id':1,'source_subject':'https://jobs.example.com/42?job=7#apply'}])
    assert result['total']==1
    assert result['matches'][0]['confidence']=='possible'


def test_shared_generic_role_with_conflicting_specialty_is_possible():
    c=fixture();add(c,'a',role='Frontend Engineer')
    result=match(c)
    assert result['total']==1
    assert result['matches'][0]['confidence']=='possible'


def test_generic_software_role_does_not_conflict_with_specialty():
    c=fixture();add(c,'a',role='Software Engineer')
    assert match(c)['matches'][0]['confidence']=='strong'


def test_matched_link_keeps_original_destination_query_order_and_tracking():
    c=fixture()
    original='https://jobs.example.com/42?z=2&step=b&step=a&notit=1&utm_source=mail#apply'
    add(c,'a',link=original)
    assert match(c)['matches'][0]['link']==original


def test_repeated_query_value_order_is_not_treated_as_identical_url():
    from mailcheck.interview_job_matches import match_jobs
    c=fixture();add(c,'a',company='Other',role='Other',link='https://jobs.example.com/42?step=b&step=a')
    result=match_jobs(c, {}, [{'account_id':1,'source_subject':'https://jobs.example.com/42?step=a&step=b'}])
    assert result['total']==0


def test_extreme_date_does_not_crash_matching():
    c=fixture();add(c,'a',day='0001-01-01T00:00:00Z')
    assert match(c)['total']==1
