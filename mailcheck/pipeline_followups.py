"""Compatibility follow-up projection from the pipeline's shared action engine."""
import uuid
from datetime import datetime, timedelta, timezone

from . import interview_pipeline as pipeline
from .pipeline_tracking import actions_for, instant


def list_followups(conn,account_id=None,now=None):
    stamp=instant(now.isoformat()) if isinstance(now,datetime) else instant(now)
    stamp=stamp or datetime.now(timezone.utc)
    cache=pipeline._read_cache(conn)
    items=[]
    for identity,record in cache['opps'].items():
        if record['account_id'] not in cache['accounts'] or record['redirect_id'] or record['archived']:
            continue
        if account_id is not None and record['account_id']!=account_id:
            continue
        data=pipeline.detail(conn,identity,_cache=cache)
        opp=data['opportunity']
        actions=actions_for(opp,data['events'],data['messages'],
            [t for t in data['tasks'] if t['kind']!='recommendation'],data['contacts'],
            now=stamp,business_days=cache['thresholds'][opp['account_id']])
        controls={t['id']:t for t in data['tasks'] if t['kind']=='recommendation'}
        for action in actions:
            if action['kind']!='followup':
                continue
            control=controls.get(action['id'])
            status='suggested'
            snoozed=None
            if control and control['state'] in {'done','dismissed'}:
                status='dismissed'
            elif control and control['state']=='snoozed' and control['snoozed_until'] and instant(control['snoozed_until'])>stamp:
                status='snoozed';snoozed=control['snoozed_until']
            # The pipeline never guesses a reply recipient from a domain or
            # silently equates a manual external log with provider delivery.
            anchors=[instant(c['at']) for c in data['contacts'] if c['expects_reply']]
            anchors.extend(instant(e.get('end_at') or e['start_at']) for e in data['events'] if e['attendance']=='Attended')
            anchor=max((value for value in anchors if value and value<=stamp),default=None)
            elapsed=0
            if anchor:
                from zoneinfo import ZoneInfo
                local_start=anchor.astimezone(ZoneInfo(opp['timezone'])).date()
                local_end=stamp.astimezone(ZoneInfo(opp['timezone'])).date()
                elapsed=sum((local_start+timedelta(days=i)).weekday()<5 for i in range(1,(local_end-local_start).days+1))
            items.append(dict(id=f"pipeline:{identity}:{action['id']}",account_id=opp['account_id'],
                account_label=opp['account_label'],company=opp['company'],role=opp['role'],
                last_interview_at=max((e['start_at'] for e in data['events'] if e['attendance']=='Attended'),default=None),
                last_contact_at=anchor.isoformat() if anchor else None,elapsed_business_days=elapsed,status=status,
                reason=action['reason']+' Open the opportunity to review contact and evidence.',
                target_message_pk=None,snoozed_until=snoozed,pipeline_id=identity))
    return dict(items=items,accounts=[dict(id=a['id'],label=a['label'],email=a['email']) for a in cache['accounts'].values()],threshold_business_days=3)


def update_state(conn,key,body):
    parts=key.split(':',2)
    if len(parts)!=3 or parts[0]!='pipeline':
        raise ValueError('Legacy reminders have been replaced. Reload the interview pipeline.')
    _,identity,task_id=parts
    current=pipeline.detail(conn,identity)['opportunity']
    state={'restore':'open','dismiss':'dismissed','snooze':'snoozed'}[body.action]
    payload=dict(operation=str(uuid.uuid4()),revision=current['revision'],state=state)
    if state=='snoozed':
        payload['snoozed_until']=(datetime.now(timezone.utc)+timedelta(days=body.days)).isoformat()
    pipeline.update_task(conn,identity,task_id,payload)
