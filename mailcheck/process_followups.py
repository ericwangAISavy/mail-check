"""Process-local reply targets and delivery-backed follow-up state. No mail mutations."""
import json
from datetime import datetime,timezone

def _instant(value):
    if not value:return None
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError,TypeError):return None

def decorate(conn,processes,now):
    now=_instant(now.isoformat())
    messages={r['id']:dict(r) for r in conn.execute('SELECT id,account_id,message_id,thread_id,references_json,from_addr,COALESCE(date_utc,fetched_at) AS contact_at FROM messages')}
    from .interview_processes import organization_domains
    own={r[0] for r in conn.execute('SELECT email FROM accounts')}
    sources={}
    for row in conn.execute('SELECT event_id,account_id,message_pk FROM interview_sources WHERE message_pk IS NOT NULL'):
        sources.setdefault((row['event_id'],row['account_id']),set()).add(row['message_pk'])
    delivered={}
    # Identity guards prevent a reused message PK or another account's send from counting.
    for row in conn.execute('''SELECT r.message_pk,r.sent_at FROM mail_replies r JOIN messages m
        ON m.id=r.message_pk AND m.account_id=r.account_id AND m.message_id=r.original_message_id
        WHERE r.status='sent' AND r.error='' AND r.sent_at IS NOT NULL'''):
        stamp=_instant(row['sent_at'])
        if stamp and stamp<=now:delivered[row['message_pk']]=max(stamp,delivered.get(row['message_pk'],stamp))
    for process in processes:
        aid=process['account_id']
        pks={int(m['id'].split(':',1)[1]) for m in process['milestones'] if m['kind']=='message'}
        for event in process['events']:pks.update(sources.get((event['id'],aid),set()))
        for m in messages.values():
            if m['account_id']==aid and process['organization'] and organization_domains([],m['from_addr'],own_emails=own)==[process['organization']]:pks.add(m['id'])
        seeds=[m for pk,m in messages.items() if pk in pks and m['account_id']==aid]
        threads={m['thread_id'] for m in seeds if m['thread_id']}
        identifiers={m['message_id'] for m in seeds}
        for m in messages.values():
            if m['account_id']!=aid:continue
            try:refs=json.loads(m['references_json'] or '[]')
            except (ValueError,TypeError):refs=[]
            if m['thread_id'] in threads or isinstance(refs,list) and any(ref in identifiers for ref in refs):pks.add(m['id'])
        relevant=[m for pk,m in messages.items() if pk in pks and m['account_id']==aid and _instant(m['contact_at']) and _instant(m['contact_at'])<=now]
        relevant.sort(key=lambda m:(_instant(m['contact_at']),m['id']),reverse=True)
        # Prefer a human recipient when an automated confirmation shares the process.
        candidates=[m for m in relevant if m['from_addr'] and not any(word in m['from_addr'].casefold() for word in ('no-reply','noreply','do-not-reply','donotreply'))]
        target=next(iter(candidates or relevant),None)
        activity=[_instant(m['contact_at']) for m in relevant]
        activity += [_instant(e.get('end_at') or e.get('start_at')) for e in process['events'] if e.get('status')!='Cancelled']
        anchor=max((stamp for stamp in activity if stamp),default=now)
        sent=max((delivered[m['id']] for m in relevant if m['id'] in delivered and delivered[m['id']]>=anchor),default=None)
        process['follow_up']={'target_message_pk':target['id'] if target else None,'status':'sent' if sent else 'ready' if target else 'unavailable','sent_at':sent.isoformat() if sent else None}
