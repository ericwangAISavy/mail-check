from datetime import datetime, timezone
from mailcheck.pipeline_tracking import actions_for


def test_ended_is_attendance_not_followup():
    actions = actions_for({'id':'x','status':'Active','timezone':'UTC'}, [{'id':1,'provider_state':'Scheduled','start_at':'2026-10-20T10:00:00Z','end_at':'2026-10-20T11:00:00Z','attendance':'Unconfirmed'}], [], [], [], now=datetime(2026,10,31,tzinfo=timezone.utc))
    assert [a['kind'] for a in actions] == ['attendance']


def test_human_response_clears_clock_automated_ack_does_not():
    opp={'id':'x','status':'Active','timezone':'America/Chicago'}
    contacts=[{'id':'c','at':'2026-10-20T10:00:00Z','expects_reply':True}]
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    ack={'id':1,'occurred_at':'2026-10-29T10:00:00Z','from_addr':'no-reply@ats.com','category':'application_ack'}
    assert actions_for(opp,[],[ack],[],contacts,now=now)[0]['kind']=='followup'
    response=dict(ack,id=2,from_addr='human@example.com',category='interview_invite')
    assert [a['kind'] for a in actions_for(opp,[],[ack,response],[],contacts,now=now)]==['review']


def test_terminal_and_hold_suppress_inactivity_but_keep_explicit_tasks():
    contacts=[{'id':'c','at':'2026-10-20T10:00:00Z','expects_reply':True}]
    task={'id':'t','title':'Decision','kind':'task','responsibility':'you','due_at':'2026-10-31','state':'open'}
    for status in ('On hold','Rejected','Accepted'):
        actions=actions_for({'id':'x','status':status,'timezone':'UTC'},[],[],[task],contacts,now=datetime(2026,10,31,tzinfo=timezone.utc))
        assert [a['id'] for a in actions]==['t']


def test_date_only_local_day_includes_dst_boundary():
    from mailcheck.pipeline_tracking import due_instant
    assert due_instant('2026-11-01','America/Chicago').astimezone(timezone.utc)==datetime(2026,11,2,6,tzinfo=timezone.utc)


def test_explicit_deadline_survives_hold_and_upcoming():
    now=datetime(2026,10,31,tzinfo=timezone.utc)
    for status,events in [('On hold',[]),('Active',[{'id':1,'provider_state':'Scheduled','start_at':'2026-11-05T10:00:00Z','end_at':'2026-11-05T11:00:00Z','attendance':'Unconfirmed'}])]:
        actions=actions_for({'id':'x','status':status,'timezone':'UTC','response_due':'2026-10-29'},events,[],[],[],now=now)
        assert any(a['kind']=='followup' and not a['suggested'] for a in actions)
