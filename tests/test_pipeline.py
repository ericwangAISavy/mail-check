import sqlite3
import uuid
import pytest
from mailcheck import interview_pipeline as p


def operation(**values): return dict(operation=str(uuid.uuid4()),**values)

@pytest.fixture
def conn():
    c=sqlite3.connect(':memory:'); c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE accounts(id INTEGER PRIMARY KEY,label TEXT,email TEXT,enabled INTEGER);INSERT INTO accounts VALUES(1,'A','a@example.com',1);INSERT INTO accounts VALUES(2,'B','b@example.com',1);
CREATE TABLE messages(id INTEGER PRIMARY KEY,account_id INTEGER,subject TEXT,date_utc TEXT,fetched_at TEXT,from_addr TEXT);
CREATE TABLE classifications(id INTEGER PRIMARY KEY,message_pk INTEGER,created_at TEXT,category TEXT,summary TEXT,company TEXT,role TEXT);
CREATE TABLE interview_events(id INTEGER PRIMARY KEY,company TEXT,role TEXT,start_at TEXT,end_at TEXT,stage TEXT,status TEXT,meeting_url TEXT,location TEXT);
CREATE TABLE interview_sources(event_id INTEGER,account_id INTEGER); CREATE TABLE interview_event_removals(event_id INTEGER);
INSERT INTO messages VALUES(1,2,'Foreign','2026-10-01','2026-10-01','x@example.com');
INSERT INTO interview_events VALUES(1,'Acme','Engineer','2026-10-01T10:00:00Z','2026-10-01T11:00:00Z','Technical','Scheduled',NULL,NULL);INSERT INTO interview_sources VALUES(1,1);''')
    c.executescript(p.SCHEMA); return c


def test_identity_replay_and_revision(conn):
    body=operation(account_id=1,company='Acme',role='Engineer')
    first=p.create(conn,body)
    assert p.create(conn,body)==first
    assert p.create(conn,operation(account_id=1,company='Acme',role='Engineer'))['id']!=first['id']
    updated=p.update(conn,first['id'],operation(revision=1,changes={'status':'Rejected'}))
    assert updated['revision']==2
    with pytest.raises(FileExistsError): p.update(conn,first['id'],operation(revision=1,changes={'role':'Manager'}))
    with pytest.raises(ValueError): p.create(conn,dict(body,company='Other'))


def test_evidence_attendance_and_reschedule(conn):
    o=p.create(conn,operation(account_id=1,company='Acme'))
    with pytest.raises(LookupError): p.evidence(conn,o['id'],operation(revision=1,action='link',kind='message',source_id=1))
    o=p.evidence(conn,o['id'],operation(revision=1,action='link',kind='event',source_id=1))
    assert o['next_action']['kind']=='attendance'
    o=p.attendance(conn,o['id'],operation(revision=o['revision'],event_id=1,start_at='2026-10-01T10:00:00Z',attendance='Attended'))
    conn.execute("UPDATE interview_events SET start_at='2026-11-02T10:00:00Z',end_at='2026-11-02T11:00:00Z' WHERE id=1")
    e=p.detail(conn,o['id'])['events'][0]
    assert e['attendance_needs_review'] and e['attendance']=='Unconfirmed'
    assert conn.execute('SELECT attendance FROM pipeline_attendance').fetchone()[0]=='Attended'


def test_split_merge_and_history(conn):
    o=p.create(conn,operation(account_id=1,company='Acme'))
    o=p.evidence(conn,o['id'],operation(revision=1,action='link',kind='event',source_id=1))
    new=p.split(conn,o['id'],operation(revision=o['revision'],company='Acme',event_ids=[1]))
    assert p.detail(conn,o['id'])['events']==[]
    result=p.merge(conn,o['id'],operation(revision=3,source_id=new['id'],source_revision=1))
    assert result['id']==o['id']
    assert p.detail(conn,new['id'])['opportunity']['redirect_id']==o['id']
    assert len(p.detail(conn,o['id'])['history'])>=4


def test_reads_are_readonly_and_review_dismissal_persists(conn):
    before=conn.total_changes
    result=p.review(conn); p.list_data(conn)
    assert conn.total_changes==before
    key=result['items'][0]['key']
    p.review_action(conn,operation(action='dismiss',key=key))
    assert all(i['key']!=key for i in p.review(conn)['items'])


def test_synthetic_dismiss_and_snooze_are_stable(conn):
    o=p.create(conn,operation(account_id=1,company='Acme'))
    o=p.evidence(conn,o['id'],operation(revision=1,action='link',kind='event',source_id=1))
    action=o['next_action']['id']
    o=p.update_task(conn,o['id'],action,operation(revision=2,state='dismissed'))
    assert not o['actions']
    o=p.update_task(conn,o['id'],action,operation(revision=3,state='snoozed',snoozed_until='2099-01-01T00:00:00Z'))
    assert not o['actions']
    o=p.update_task(conn,o['id'],action,operation(revision=4,state='open'))
    assert o['next_action']['id']==action


def test_disabled_account_and_removed_provider(conn):
    o=p.create(conn,operation(account_id=1,company='Acme'))
    o=p.evidence(conn,o['id'],operation(revision=1,action='link',kind='event',source_id=1))
    conn.execute('INSERT INTO interview_event_removals VALUES(1)')
    d=p.detail(conn,o['id'])
    assert d['events'][0]['provider_state']=='Removed from provider'
    assert d['opportunity']['status']=='Active'
    assert not d['opportunity']['actions']
    conn.execute('UPDATE accounts SET enabled=0 WHERE id=1')
    with pytest.raises(LookupError): p.detail(conn,o['id'])
    assert p.list_data(conn)['opportunities']==[]


def test_merge_conflicts_and_split_rollback(conn):
    a=p.create(conn,operation(account_id=1,company='Acme'))
    b=p.create(conn,operation(account_id=1,company='Acme'))
    b=p.update(conn,b['id'],operation(revision=1,changes={'status':'Rejected'}))
    with pytest.raises(ValueError): p.merge(conn,a['id'],operation(revision=1,source_id=b['id'],source_revision=2))
    before=conn.execute('SELECT count(*) FROM pipeline_opportunities').fetchone()[0]
    with pytest.raises(ValueError): p.split(conn,a['id'],operation(revision=1,company='New',event_ids=[99]))
    assert conn.execute('SELECT count(*) FROM pipeline_opportunities').fetchone()[0]==before


def test_list_read_queries_do_not_grow_with_opportunities(conn):
    def queries():
        trace=[];conn.set_trace_callback(trace.append)
        p.list_data(conn)
        conn.set_trace_callback(None)
        return len(trace)
    p.create(conn,operation(account_id=1,company='Acme'))
    initial=queries()
    for i in range(10): p.create(conn,operation(account_id=1,company='Acme',role=str(i)))
    assert queries()==initial


def test_message_metadata_only_and_revocation(conn):
    conn.execute('ALTER TABLE messages ADD COLUMN body_text TEXT')
    conn.execute("INSERT INTO messages(id,account_id,subject,date_utc,fetched_at,from_addr,body_text) VALUES(2,1,'Owned','2026-10-01T10:00:00Z','2026-10-01T10:00:00Z','human@example.com','PRIVATE BODY')")
    o=p.create(conn,operation(account_id=1,company='Acme'))
    o=p.evidence(conn,o['id'],operation(revision=1,action='link',kind='message',source_id=2))
    assert 'PRIVATE BODY' not in conn.execute("SELECT snapshot FROM pipeline_links WHERE kind='message'").fetchone()[0]
    queries=[];conn.set_trace_callback(queries.append)
    p.list_data(conn)
    conn.set_trace_callback(None)
    assert not any('m.*' in q or 'SELECT * FROM messages' in q for q in queries)
    conn.execute('UPDATE messages SET account_id=2 WHERE id=2')
    assert p.detail(conn,o['id'])['messages']==[]
    assert not p.list_data(conn)['opportunities'][0]['actions']


def test_native_shared_event_requires_each_profile_confirmation(conn):
    conn.execute('INSERT INTO interview_sources VALUES(1,2)')
    a=p.create(conn,operation(account_id=1,company='Acme'))
    a=p.evidence(conn,a['id'],operation(revision=1,action='link',kind='event',source_id=1))
    assert any(i['key']=='event:2:1' for i in p.review(conn)['items'])
    conn.execute('DELETE FROM interview_sources WHERE account_id=1')
    assert p.detail(conn,a['id'])['events']==[]
    assert p.list_data(conn)['opportunities'][0]['next_interview'] is None


def test_sync_receipts_preserve_success_on_partial_failure(conn):
    p.note_calendar_sync(conn,1)
    success=p.sync_status(conn,1)['calendar']['last_success']
    assert success
    p.note_calendar_sync(conn,1,errors=['Partial provider response'])
    status=p.sync_status(conn,1)['calendar']
    assert status['last_success']==success
    assert status['error']=='Partial provider response'
    p.note_calendar_sync(conn,1)
    assert p.sync_status(conn,1)['calendar']['error'] is None
    o=p.create(conn,operation(account_id=1,company='Acme'))
    assert o['sync_freshness']['calendar']['last_success']


def test_exact_company_role_suggestion_is_not_confirmed_link(conn):
    o=p.create(conn,operation(account_id=1,company='Acme',role='Engineer'))
    before=conn.total_changes
    item=next(i for i in p.review(conn)['items'] if i['key']=='event:1:1')
    assert item['suggested_opportunities']==[]
    assert item['company'] is None
    assert conn.total_changes==before
    assert p.detail(conn,o['id'])['events']==[]


def test_synthetic_controls_are_scoped_and_merge_preserves_promises(conn):
    a=p.create(conn,operation(account_id=1,company='Acme'))
    b=p.create(conn,operation(account_id=1,company='Acme'))
    for o in (a,b):
        o=p.evidence(conn,o['id'],operation(revision=1,action='link',kind='event',source_id=1))
        p.update_task(conn,o['id'],o['next_action']['id'],operation(revision=2,state='dismissed'))
    assert conn.execute('SELECT count(*) FROM pipeline_tasks').fetchone()[0]==2
    b=p.update(conn,b['id'],operation(revision=3,changes={'response_due':'2026-11-09','stage':'Technical Interview'}))
    a=p.merge(conn,a['id'],operation(revision=3,source_id=b['id'],source_revision=4))
    assert a['response_due']=='2026-11-09' and a['stage']=='Technical Interview'
    assert conn.execute('SELECT count(*) FROM pipeline_tasks').fetchone()[0]==1


def test_replay_revalidates_account_and_source(conn):
    body=operation(account_id=1,company='Acme')
    a=p.create(conn,body)
    link=operation(revision=1,action='link',kind='event',source_id=1)
    p.evidence(conn,a['id'],link)
    conn.execute('DELETE FROM interview_sources WHERE account_id=1')
    replay=p.evidence(conn,a['id'],link)
    assert replay['actions']==[]
    conn.execute('UPDATE accounts SET enabled=0 WHERE id=1')
    conn.commit()
    with pytest.raises(LookupError): p.create(conn,body)
    with pytest.raises(LookupError): p.evidence(conn,a['id'],link)


def test_activation_checks_all_legacy_controls(conn):
    conn.execute('CREATE TABLE agent_followup_state(id TEXT,status TEXT,snoozed_until TEXT,updated_at TEXT)')
    conn.execute("INSERT INTO agent_followup_state VALUES('old','dismissed',NULL,NULL)")
    for i in range(201):
        conn.execute('INSERT INTO interview_events(id,company) VALUES(?,?)',(i+2,'Booking'))
        conn.execute('INSERT INTO interview_sources VALUES(?,1)',(i+2,))
    with pytest.raises(ValueError): p.activate(conn,operation())
    p.review_action(conn,operation(action='dismiss',key='legacy:agent_followup_state:None:old'))
    assert p.activate(conn,operation())['activated']


@pytest.mark.parametrize('changes',[{'company':None},{'company':{}},{'role':[]},{'pinned':1},{'archived':'false'},{'timezone':None},{'response_due':{}}])
def test_invalid_update_values_are_validation_errors(conn,changes):
    a=p.create(conn,operation(account_id=1,company='Acme'))
    with pytest.raises(ValueError): p.update(conn,a['id'],operation(revision=1,changes=changes))


def test_contact_requires_past_aware_time_and_deadline_can_clear(conn):
    a=p.create(conn,operation(account_id=1,company='Acme'))
    assert a['timezone']=='America/Chicago'
    for at in ('2026-10-01T10:00:00','2099-01-01T00:00:00Z'):
        with pytest.raises(ValueError): p.add_contact(conn,a['id'],operation(revision=1,at=at,expects_reply=True,note='sent'))
    a=p.update(conn,a['id'],operation(revision=1,changes={'response_due':'2026-10-01'}))
    a=p.update(conn,a['id'],operation(revision=2,changes={'response_due':None}))
    assert a['response_due'] is None


def test_review_queries_do_not_grow_per_calendar_booking(conn):
    for i in range(50):
        conn.execute('INSERT INTO interview_events(id,company) VALUES(?,?)',(i+2,'Booking'))
        conn.execute('INSERT INTO interview_sources VALUES(?,1)',(i+2,))
    statements=[];conn.set_trace_callback(statements.append)
    try: result=p.review(conn,limit=50)
    finally: conn.set_trace_callback(None)
    assert result['total']>=50
    assert len(statements)<20
