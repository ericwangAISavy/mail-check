from datetime import datetime,timezone
import json

from mailcheck import db
from mailcheck.profile_outcomes import report


NOW=datetime(2026,12,5,18,tzinfo=timezone.utc)


def setup(tmp_path):
    conn=db.connect(tmp_path/'quality.db')
    aid=db.add_account(conn,label='Profile',email='profile@example.test')
    return conn,aid


def receipt(conn,aid,key,kind,stamp,company='Acme',role='Engineer',refs=()):
    conn.execute('''INSERT INTO application_receipts(account_id,message_id,received_at,category,company,role,job_refs)
        VALUES(?,?,?,?,?,?,?)''',(aid,key,stamp,kind,company,role,json.dumps(list(refs))))


def test_distinct_cohort_outcomes_cannot_exceed_applications(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        for key,company in [('a','Acme'),('duplicate','ACME, Inc.')]:
            receipt(conn,aid,key,'application_ack','2026-11-01T16:00:00Z',company=company)
        for i in range(4):receipt(conn,aid,f'i{i}','interview_invite','2026-11-05T16:00:00Z')
        for i in range(2):receipt(conn,aid,f'r{i}','rejection','2026-11-10T16:00:00Z')
        data=report(conn,as_of=NOW,history_since='2026-11-01')
        profile=data['accounts'][0];day=profile['daily']['2026-11-01']
        assert day['applications']==1
        assert day['windows']['14']=={'eligible':1,'interview':1,'rejection':1,'answered':1}
        assert profile['duplicates']==1
        assert '2026-11-05' not in profile['daily']
    finally:conn.close()


def test_fixed_followup_and_recent_cohorts_are_not_misrepresented_as_failures(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        receipt(conn,aid,'old','application_ack','2026-11-01T16:00:00Z')
        receipt(conn,aid,'late','interview_invite','2026-11-20T16:00:00Z')
        receipt(conn,aid,'recent','application_ack','2026-12-04T16:00:00Z',company='Recent')
        data=report(conn,as_of=NOW,history_since='2026-11-01')
        daily=data['accounts'][0]['daily']
        assert daily['2026-11-01']['windows']['14']['interview']==0
        assert daily['2026-11-01']['windows']['30']['interview']==1
        assert daily['2026-12-04']['windows']['14']['eligible']==0
        assert daily['2026-12-04']['applications']==1
    finally:conn.close()


def test_ambiguous_outcomes_and_other_profiles_are_excluded_from_rates(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        other=db.add_account(conn,label='Other',email='other@example.test')
        receipt(conn,aid,'a','application_ack','2026-11-01T16:00:00Z',refs=['12345'])
        receipt(conn,aid,'b','application_ack','2026-11-01T17:00:00Z',refs=['67890'])
        receipt(conn,aid,'ambiguous','interview_invite','2026-11-02T16:00:00Z')
        receipt(conn,aid,'exact','rejection','2026-11-03T16:00:00Z',refs=['12345'])
        receipt(conn,other,'unlinked','interview_invite','2026-11-03T16:00:00Z')
        data=report(conn,as_of=NOW,history_since='2026-11-01')
        profiles={a['id']:a for a in data['accounts']}
        assert profiles[aid]['unmatched']['interview']==1
        assert profiles[aid]['daily']['2026-11-01']['windows']['14']['interview']==0
        assert profiles[aid]['daily']['2026-11-01']['windows']['14']['rejection']==1
        assert profiles[other]['unmatched']['interview']==1
    finally:conn.close()


def test_exact_reference_beats_newer_application_and_conflicting_roles(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        receipt(conn,aid,'old','application_ack','2026-11-01T16:00:00Z',refs=['12345'])
        receipt(conn,aid,'new','application_ack','2026-11-02T16:00:00Z',refs=['67890'])
        receipt(conn,aid,'exact','interview_invite','2026-11-03T16:00:00Z',refs=['12345'])
        receipt(conn,aid,'wrong-role','rejection','2026-11-03T16:00:00Z',role='Designer',refs=['12345'])
        receipt(conn,aid,'before','rejection','2026-10-31T16:00:00Z')
        p=report(conn,as_of=NOW,history_since='2026-11-01')['accounts'][0]
        assert p['daily']['2026-11-01']['windows']['14']['interview']==1
        assert p['daily']['2026-11-02']['windows']['14']['interview']==0
        assert p['unmatched']['rejection']==2
    finally:conn.close()


def test_cohort_maturity_requires_complete_chicago_day_and_history(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        receipt(conn,aid,'early','application_ack','2026-11-19T16:00:00Z')
        receipt(conn,aid,'mature','application_ack','2026-11-20T16:00:00Z')
        receipt(conn,aid,'partial','application_ack','2026-11-21T16:00:00Z')
        p=report(conn,as_of=NOW,history_since='2026-11-20')['accounts'][0]
        assert p['daily']['2026-11-19']['windows']['14']['eligible']==0
        assert p['daily']['2026-11-20']['windows']['14']['eligible']==1
        assert p['daily']['2026-11-21']['windows']['14']['eligible']==0
        assert report(conn,as_of=NOW,account='missing')['accounts']==[]
    finally:conn.close()


def test_upgrade_backfills_retained_outcome_references_once(tmp_path):
    from mailcheck.models import NormalizedMessage,Classification
    path=tmp_path/'quality.db'
    conn,aid=setup(tmp_path)
    pk=db.upsert_message(conn,NormalizedMessage(account_id=aid,account_label='Profile',message_id='outcome',
        uid='outcome',folder='INBOX',from_addr='recruiter@example.test',from_name='Recruiter',
        subject='Interview Job ID: 12345',date_utc=datetime(2026,11,3,16,tzinfo=timezone.utc),body='Job ID: 12345'))
    db.save_classification(conn,pk,Classification('interview_invite',company='Acme',role='Engineer'),'model','v1')
    conn.execute("UPDATE application_receipts SET job_refs='[]'")
    conn.execute('PRAGMA user_version=55');conn.commit();conn.close()
    conn=db.connect(path)
    try:
        assert json.loads(conn.execute('SELECT job_refs FROM application_receipts').fetchone()[0])==['12345']
    finally:conn.close()


def test_profile_colors_do_not_change_when_filtered(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        db.add_account(conn,label='Alpha',email='alpha@example.test')
        all_profiles=report(conn,as_of=NOW)['accounts']
        slot=next(p['color_slot'] for p in all_profiles if p['id']==aid)
        assert slot==1
        assert report(conn,as_of=NOW,account='Profile')['accounts'][0]['color_slot']==slot
    finally:conn.close()


def test_reply_before_precise_confirmation_is_never_counted(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        receipt(conn,aid,'a','application_ack','2026-11-01T16:00:00.000200Z',refs=['12345'])
        receipt(conn,aid,'b','application_ack','2026-11-01T16:00:00.000100Z',refs=['67890'])
        receipt(conn,aid,'reply','interview_invite','2026-11-01T16:00:00.000150Z',refs=['12345'])
        p=report(conn,as_of=NOW)['accounts'][0]
        assert p['daily']['2026-11-01']['windows']['14']['interview']==0
        assert p['unmatched']['interview']==1
    finally:conn.close()


def test_damaged_receipt_metadata_does_not_crash_reporting(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        receipt(conn,aid,'ack','application_ack','2026-11-01T16:00:00Z')
        receipt(conn,aid,'reply','interview_invite','2026-11-02T16:00:00Z')
        conn.execute("UPDATE application_receipts SET job_refs='bad' WHERE message_id='ack'")
        conn.execute("UPDATE application_receipts SET job_refs='[null,[],123]' WHERE message_id='reply'")
        receipt(conn,aid,'invalid-time','application_ack','2026-11-01T24:00:00Z')
        p=report(conn,as_of=NOW)['accounts'][0]
        assert p['daily']['2026-11-01']['applications']==1
        assert p['daily']['2026-11-01']['windows']['14']['interview']==1
    finally:conn.close()


def test_repeated_reply_after_reapplication_does_not_guess_the_newest_application(tmp_path):
    conn,aid=setup(tmp_path)
    try:
        receipt(conn,aid,'first','application_ack','2026-11-01T16:00:00Z')
        receipt(conn,aid,'invite','interview_invite','2026-11-02T16:00:00Z')
        receipt(conn,aid,'second','application_ack','2026-11-03T16:00:00Z')
        receipt(conn,aid,'reminder','interview_invite','2026-11-04T16:00:00Z')
        p=report(conn,as_of=NOW)['accounts'][0]
        assert p['daily']['2026-11-01']['windows']['14']['interview']==1
        assert p['daily']['2026-11-03']['windows']['14']['interview']==0
        assert p['unmatched']['interview']==1
    finally:conn.close()
