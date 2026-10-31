"""Pure, conservative recommendations from explicitly linked local evidence."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def instant(value):
    if not value:
        return None
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result


def due_instant(value, zone='UTC'):
    if not value:
        return None
    if len(value) == 10:
        return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(zone)) + timedelta(days=1)
    return instant(value)


def actions_for(opp, events, messages, tasks, contacts, *, now=None, business_days=3):
    now = now or datetime.now(timezone.utc)
    zone = opp.get('timezone') or 'UTC'
    actions = []
    def add(id, title, kind, responsibility='you', due_at=None, reason='', suggested=False, **extra):
        actions.append(dict(id=id,title=title,kind=kind,responsibility=responsibility,due_at=due_at,state='open',reason=reason,suggested=suggested,**extra))
    for task in tasks:
        if task['state'] == 'open' or task['state'] == 'snoozed' and task.get('snoozed_until') and instant(task['snoozed_until']) <= now:
            add(task['id'], task['title'],task['kind'],task['responsibility'],task.get('due_at'),'Explicit task')
    anchors = [(instant(c['at']),f"contact:{c['id']}") for c in contacts if c['expects_reply']]
    upcoming = False
    for event in events:
        if event['provider_state'] != 'Scheduled' or not event.get('start_at'):
            continue
        start = instant(event['start_at'])
        end = instant(event.get('end_at')) or start
        if end >= now:
            upcoming = True
            add(f"meeting:{event['id']}:{event['start_at']}",'Prepare for interview','meeting','you',event['start_at'],'Confirmed booking')
        elif event['attendance'] == 'Unconfirmed' or event.get('attendance_needs_review'):
            add(f"attendance:{event['id']}:{event['start_at']}",'Record attendance','attendance',reason='Ended booking; attendance is unconfirmed')
        elif event['attendance'] == 'Attended':
            anchors.append((end,f"attendance:{event['id']}:{event['start_at']}"))
    # Inbound intent remains reviewable: classification never confirms an outcome.
    human = [m for m in messages if m.get('category') not in {'application_ack','application_confirmation','application_acknowledgement','job_alert','newsletter','automated_notification'} and not any(s in (m.get('from_addr') or '').lower() for s in ('no-reply','noreply','donotreply'))]
    anchor = max(anchors, default=None)
    newer = [m for m in human if not anchor or instant(m.get('occurred_at')) and instant(m['occurred_at']) > anchor[0]]
    if newer:
        m = max(newer,key=lambda m: m.get('occurred_at') or '')
        add(f"review:message:{m['id']}",'Review employer update','review','unknown',reason='Linked human inbound requires review',target_message_pk=m['id'])
    terminal = opp['status'] in {'Accepted','Rejected','Withdrawn','Offer declined','Role closed'}
    deadline = opp.get('response_due')
    if not terminal and deadline and due_instant(deadline,zone) <= now:
        add(f'followup:{deadline}','Follow up','followup','you',deadline,'Confirmed employer deadline passed')
    if not terminal and opp['status'] != 'On hold' and not newer and not upcoming and not deadline:
        eligible = False
        if anchor:
            day = anchor[0].astimezone(ZoneInfo(zone))
            remaining = business_days
            while remaining:
                day += timedelta(days=1)
                remaining -= day.weekday() < 5
            eligible = now >= day
        if eligible:
            add(f"followup:{deadline or anchor[1]}",'Follow up' if deadline else 'Suggested follow-up','followup','you',deadline,'Confirmed employer deadline passed' if deadline else f'{business_days} weekdays since confirmed attendance/contact',not bool(deadline))
    def order(a):
        due = due_instant(a.get('due_at'),zone)
        return (0 if due and due <= now else 1 if due else 2 if a['kind'] in {'attendance','review'} else 3, due or datetime.max.replace(tzinfo=timezone.utc),a['id'])
    return sorted(actions,key=order)
