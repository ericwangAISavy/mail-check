"""Semantic enrichment of saved email calendar invitations, across providers."""
from collections import OrderedDict
from datetime import datetime,timezone
import json
import threading
import time

from .calendar_events import CalendarBooking
from .calendar_content import SOURCE_LIMIT

PREFIX='email-event:'
_scans=OrderedDict()
_scan_lock=threading.Lock()


def event(conn,task):
    if not task['external_id'].startswith(PREFIX):return None
    identity=task['external_id'][len(PREFIX):]
    if not identity.isdigit():return None
    return conn.execute('''SELECT e.* FROM interview_events e WHERE e.id=? AND e.extraction_rank=2
        AND NOT EXISTS(SELECT 1 FROM interview_event_removals r WHERE r.event_id=e.id)
        AND EXISTS(SELECT 1 FROM interview_sources s JOIN accounts a ON a.id=s.account_id
            WHERE s.event_id=e.id AND s.account_id=? AND a.enabled=1
            AND s.external_message_id NOT LIKE 'graph-event:%')''',(int(identity),task['account_id'])).fetchone()


def enqueue_events(conn,event_ids,*,missing_only=False):
    from .calendar_queue import enqueue,payload_version
    added=0
    for identity in event_ids:
        row=conn.execute('''SELECT e.*,s.account_id,s.source_subject,m.body_text,m.interview_text
            FROM interview_events e JOIN interview_sources s ON s.event_id=e.id
            JOIN accounts a ON a.id=s.account_id LEFT JOIN messages m ON m.id=s.message_pk
            WHERE e.id=? AND e.extraction_rank=2 AND a.enabled=1 AND e.start_at IS NOT NULL
            AND s.external_message_id NOT LIKE 'graph-event:%'
            AND NOT EXISTS(SELECT 1 FROM interview_event_removals r WHERE r.event_id=e.id)
            ORDER BY s.id DESC LIMIT 1''',(identity,)).fetchone()
        if row is None:continue
        external=PREFIX+str(identity)
        if missing_only and conn.execute('SELECT 1 FROM calendar_analysis_tasks WHERE account_id=? AND external_id=?',
                (row['account_id'],external)).fetchone():continue
        def stamp(value):
            if not value:return None
            result=datetime.fromisoformat(value.replace('Z','+00:00'))
            return result.replace(tzinfo=result.tzinfo or timezone.utc)
        booking=CalendarBooking(provider_id=external,uid=row['calendar_uid'] or '',
            title=row['source_subject'] or row['company'] or 'Interview invitation',
            start=stamp(row['start_at']),end=stamp(row['end_at']),timezone=row['timezone'] or 'UTC',
            recurrence_id=row['recurrence_id'],cancelled=row['status']=='Cancelled',
            location=row['location'],meeting_url=row['meeting_url'],meeting_platform=row['meeting_platform'],
            organizer_name=row['organizer_name'],organizer_email=row['organizer_email'],
            participants=json.loads(row['participants']),updated_at=stamp(row['revision_at']),
            description='\n\n'.join(part for part in [row['notes'],row['interview_text'] or row['body_text']] if part)[:SOURCE_LIMIT])
        _,version=payload_version(booking,SOURCE_LIMIT)
        previous=conn.execute('SELECT version,state FROM calendar_analysis_tasks WHERE account_id=? AND external_id=?',
            (row['account_id'],external)).fetchone()
        if previous and previous['version']==version and previous['state']=='done':continue
        enqueue(conn,row['account_id'],booking,cached=False,max_chars=SOURCE_LIMIT,commit=False)
        added+=1
    return added


def backfill(conn,*,limit=25):
    """At most one bounded discovery pass per workspace per minute."""
    path=conn.execute('PRAGMA database_list').fetchone()[2]
    now=time.monotonic()
    with _scan_lock:
        if path in _scans and now-_scans[path]<60:return 0
        _scans[path]=now
        _scans.move_to_end(path)
        while len(_scans)>128:_scans.popitem(last=False)
    ids=[row[0] for row in conn.execute('''SELECT e.id FROM interview_events e
        WHERE e.extraction_rank=2 AND e.start_at IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM interview_event_removals r WHERE r.event_id=e.id)
        AND EXISTS(SELECT 1 FROM interview_sources s JOIN accounts a ON a.id=s.account_id
            WHERE s.event_id=e.id AND a.enabled=1 AND s.external_message_id NOT LIKE 'graph-event:%')
        AND NOT EXISTS(SELECT 1 FROM calendar_analysis_tasks t WHERE t.external_id=? || e.id)
        ORDER BY e.start_at DESC,e.id LIMIT ?''',(PREFIX,limit))]
    if not ids:return 0
    owned=not conn.in_transaction
    try:
        if owned:conn.execute('BEGIN IMMEDIATE')
        added=enqueue_events(conn,ids,missing_only=True)
        if owned:conn.commit()
        return added
    except BaseException:
        if owned:conn.rollback()
        with _scan_lock:_scans.pop(path,None)
        raise


def apply(conn,task,result):
    """Change semantic fields only; never promote email events to native rank."""
    from . import db
    row=event(conn,task)
    if row is None:return None,False
    manual=set(json.loads(row['manual_fields']))
    review=not result.is_interview_event or result.ambiguous or result.confidence<.8 or not result.company or not result.role
    if result.is_interview_event:
        reasons=[part.strip() for part in (row['review_reason'] or '').split(';') if part.strip()
            and not part.strip().startswith(('Company unknown','Low-confidence','Calendar detail analysis','Uncertain calendar analysis','Verify missing or uncertain calendar details'))]
        review=review or bool(reasons)
        if review:reasons.append('Verify missing or uncertain calendar details')
        wanted=dict(company=result.company,role=result.role,interviewers=json.dumps(result.interviewers),
            confidence=result.confidence,needs_review=int(review),review_reason='; '.join(dict.fromkeys(reasons)) or None)
        if result.stage!='Other' or row['stage']=='Other':wanted['stage']=result.stage
    else:
        wanted=dict(needs_review=1,review_reason='Email invitation analysis needs review; retry analysis or correct event details.')
    changes={key:value for key,value in wanted.items() if key not in manual and row[key]!=value}
    if changes:
        conn.execute('UPDATE interview_events SET '+','.join(key+'=?' for key in changes)+',updated_at=? WHERE id=?',
            (*changes.values(),db._now(),row['id']))
    unresolved=not result.is_interview_event or result.ambiguous or result.confidence<.8
    return (dict(id=row['id'],company=changes.get('company',row['company']),status=row['status'],start_at=row['start_at']) if changes else None),unresolved
