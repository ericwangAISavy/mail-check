"""Persistent interview opportunities. Source collectors are never called here."""
import hashlib
import json
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from .pipeline_tracking import actions_for, instant, due_instant

SCHEMA = '''
CREATE TABLE IF NOT EXISTS pipeline_opportunities (
 id TEXT PRIMARY KEY, account_id INTEGER NOT NULL REFERENCES accounts(id), revision INTEGER NOT NULL DEFAULT 1,
 company TEXT NOT NULL, role TEXT NOT NULL DEFAULT '', job_url TEXT NOT NULL DEFAULT '', application_ref TEXT NOT NULL DEFAULT '',
 status TEXT NOT NULL DEFAULT 'Active', stage TEXT NOT NULL DEFAULT 'Not confirmed', pinned INTEGER NOT NULL DEFAULT 0,
 archived INTEGER NOT NULL DEFAULT 0, timezone TEXT NOT NULL DEFAULT 'America/Chicago', response_due TEXT, redirect_id TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_links (opportunity_id TEXT NOT NULL REFERENCES pipeline_opportunities(id),kind TEXT NOT NULL,source_id INTEGER NOT NULL,snapshot TEXT NOT NULL,PRIMARY KEY(opportunity_id,kind,source_id));
CREATE TABLE IF NOT EXISTS pipeline_attendance (opportunity_id TEXT NOT NULL,event_id INTEGER NOT NULL,start_at TEXT NOT NULL,attendance TEXT NOT NULL,recorded_at TEXT NOT NULL,PRIMARY KEY(opportunity_id,event_id,start_at));
CREATE TABLE IF NOT EXISTS pipeline_tasks (id TEXT NOT NULL,opportunity_id TEXT NOT NULL,title TEXT NOT NULL,kind TEXT NOT NULL,responsibility TEXT NOT NULL,due_at TEXT,state TEXT NOT NULL DEFAULT 'open',snoozed_until TEXT,PRIMARY KEY(opportunity_id,id));
CREATE TABLE IF NOT EXISTS pipeline_contacts (id TEXT PRIMARY KEY,opportunity_id TEXT NOT NULL,at TEXT NOT NULL,expects_reply INTEGER NOT NULL,note TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_history (id INTEGER PRIMARY KEY,opportunity_id TEXT NOT NULL,at TEXT NOT NULL,kind TEXT NOT NULL,data TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_operations (operation TEXT PRIMARY KEY,fingerprint TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_review_decisions (key TEXT PRIMARY KEY,action TEXT NOT NULL,at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS pipeline_sync_state (account_id INTEGER NOT NULL,kind TEXT NOT NULL,last_success TEXT,last_attempt TEXT NOT NULL,error TEXT,PRIMARY KEY(account_id,kind));
CREATE TABLE IF NOT EXISTS pipeline_settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_pipeline_links_source ON pipeline_links(kind,source_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_history_opportunity ON pipeline_history(opportunity_id,id);
'''
STATUSES = {'Active','On hold','Offer received','Accepted','Rejected','Withdrawn','Offer declined','Role closed'}
from .interviews import STAGES as INTERVIEW_STAGES
STAGES = set(INTERVIEW_STAGES) | {'Not confirmed'}

def _now(): return datetime.now(timezone.utc).isoformat()
def _rows(conn, sql, args=()): return [dict(r) for r in conn.execute(sql,args)]
def _account(conn, id):
    row=conn.execute('SELECT * FROM accounts WHERE id=? AND enabled=1',(id,)).fetchone()
    if not row: raise LookupError('Enabled profile not found')
    return dict(row)
def _opp(conn,id):
    row=conn.execute('SELECT * FROM pipeline_opportunities WHERE id=?',(id,)).fetchone()
    if not row: raise LookupError('Opportunity not found')
    value=dict(row); _account(conn,value['account_id']); return value

def _history(conn,id,kind,data): conn.execute('INSERT INTO pipeline_history(opportunity_id,at,kind,data) VALUES(?,?,?,?)',(id,_now(),kind,json.dumps(data)))
def _mutate(conn,body,scope,fn):
    try: operation=str(uuid.UUID(body['operation']))
    except (KeyError,ValueError,TypeError,AttributeError): raise ValueError('operation must be a UUID')
    fingerprint=hashlib.sha256(json.dumps([scope,body],sort_keys=True).encode()).hexdigest()
    with conn:
        # Acquire write lock before revision checks, including concurrent admins.
        conn.execute('UPDATE pipeline_settings SET value=value WHERE key=?',('activated',))
        prior=conn.execute('SELECT * FROM pipeline_operations WHERE operation=?',(operation,)).fetchone()
        if prior:
            if prior['fingerprint'] != fingerprint: raise ValueError('Operation reused with different content')
            result=json.loads(prior['result'])
            # Replays never return stale cached private source-derived fields.
            if isinstance(scope,list): _opp(conn,scope[1])
            if body.get('account_id') is not None: _account(conn,body['account_id'])
            if result.get('opportunity'):
                return {'opportunity':detail(conn,result['opportunity']['id'])['opportunity']}
            if result.get('id'): return detail(conn,result['id'])['opportunity']
            if body.get('key','').split(':')[0] in {'event','message'}:
                parts=body['key'].split(':'); _account(conn,int(parts[1]))
            return result
        result=fn()
        conn.execute('INSERT INTO pipeline_operations VALUES(?,?,?)',(operation,fingerprint,json.dumps(result)))
        return result

def _revision(conn,id,body):
    opp=_opp(conn,id)
    if opp['redirect_id']: raise FileExistsError('Opportunity was merged; reload redirect')
    if type(body.get('revision')) is not int or opp['revision'] != body['revision']: raise FileExistsError('Opportunity changed; reload before editing')
    return opp

def _touch(conn,id,kind,body):
    conn.execute('UPDATE pipeline_opportunities SET revision=revision+1,updated_at=? WHERE id=?',(_now(),id)); _history(conn,id,kind,body)
    return detail(conn,id)['opportunity']

def _validate_fields(changes):
    bounds={'company':300,'role':500,'job_url':4000,'application_ref':500,'timezone':100,'status':100,'stage':100}
    for key,maximum in bounds.items():
        if key in changes and (not isinstance(changes[key],str) or len(changes[key])>maximum): raise ValueError(f'Invalid {key}')
    if 'company' in changes and not changes['company'].strip(): raise ValueError('Company is required')
    for key in ('pinned','archived'):
        if key in changes and type(changes[key]) is not bool: raise ValueError(f'{key} must be boolean')
    if 'response_due' in changes and changes['response_due'] is not None:
        value=changes['response_due']
        if not isinstance(value,str) or not value or len(value)>100: raise ValueError('Invalid response_due')
        due_instant(value)


def _insert(conn,body):
    _account(conn,body['account_id']); zone=body.get('timezone') or 'America/Chicago'
    try: ZoneInfo(zone)
    except Exception: raise ValueError('Invalid timezone')
    _validate_fields({k:body[k] for k in ('company','role','job_url','application_ref','timezone') if k in body})
    company=(body.get('company') or '').strip()
    if not company: raise ValueError('Company is required')
    id=str(uuid.uuid4()); now=_now()
    conn.execute('INSERT INTO pipeline_opportunities(id,account_id,company,role,job_url,application_ref,timezone,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(id,body['account_id'],company,body.get('role') or '',body.get('job_url') or '',body.get('application_ref') or '',zone,now,now))
    _history(conn,id,'created',body); return id

def create(conn,body): return _mutate(conn,body,'create',lambda: detail(conn,_insert(conn,body))['opportunity'])

def update(conn,id,body):
    def run():
        _revision(conn,id,body); changes=body.get('changes',{})
        allowed={'company','role','job_url','application_ref','status','stage','pinned','archived','timezone','response_due'}
        if not isinstance(changes,dict) or not changes or set(changes)-allowed: raise ValueError('Invalid changes')
        _validate_fields(changes)
        if 'status' in changes and changes['status'] not in STATUSES: raise ValueError('Invalid status')
        if 'stage' in changes and changes['stage'] not in STAGES: raise ValueError('Invalid stage')
        if 'company' in changes and not str(changes['company']).strip(): raise ValueError('Company is required')
        if 'timezone' in changes:
            try: ZoneInfo(changes['timezone'])
            except Exception: raise ValueError('Invalid timezone')
        if changes.get('response_due'): due_instant(changes['response_due'])
        for key,value in changes.items(): conn.execute(f'UPDATE pipeline_opportunities SET {key}=? WHERE id=?',(value,id))
        return _touch(conn,id,'updated',changes)
    return _mutate(conn,body,['update',id],run)

def _source(conn,opp,kind,id):
    if kind=='message': rows=_rows(conn,'SELECT id,account_id,subject,date_utc,fetched_at,from_addr FROM messages WHERE id=? AND account_id=?',(id,opp['account_id']))
    elif kind=='event': rows=_rows(conn,'SELECT e.* FROM interview_events e WHERE e.id=? AND EXISTS(SELECT 1 FROM interview_sources s WHERE s.event_id=e.id AND s.account_id=?)',(id,opp['account_id']))
    else: raise ValueError('Invalid evidence kind')
    if not rows: raise LookupError('Evidence not found in opportunity profile')
    return rows[0]

def _link(conn,opp,kind,id):
    source=_source(conn,opp,kind,id)
    allowed={'id','account_id','subject','date_utc','fetched_at','from_addr'} if kind=='message' else {'id','company','role','stage','status','start_at','end_at','timezone','meeting_url','location'}
    source={k:v for k,v in source.items() if k in allowed}
    conn.execute('INSERT OR IGNORE INTO pipeline_links VALUES(?,?,?,?)',(opp['id'],kind,id,json.dumps(source)))

def evidence(conn,id,body):
    def run():
        opp=_revision(conn,id,body); kind=body['kind']; source_id=body['source_id']
        if kind not in {'event','message'}: raise ValueError('Invalid evidence kind')
        if body['action']=='link': _link(conn,opp,kind,source_id)
        elif body['action']=='unlink': conn.execute('DELETE FROM pipeline_links WHERE opportunity_id=? AND kind=? AND source_id=?',(id,kind,source_id))
        else: raise ValueError('Invalid evidence action')
        return _touch(conn,id,'evidence',body)
    return _mutate(conn,body,['evidence',id],run)

def attendance(conn,id,body):
    def run():
        opp=_revision(conn,id,body); source=_source(conn,opp,'event',body['event_id'])
        if not conn.execute("SELECT 1 FROM pipeline_links WHERE opportunity_id=? AND kind='event' AND source_id=?",(id,body['event_id'])).fetchone(): raise ValueError('Link event before recording attendance')
        if source['start_at'] != body['start_at']: raise FileExistsError('Booking moved; review current occurrence')
        if body['attendance'] not in {'Unconfirmed','Attended','Did not attend'}: raise ValueError('Invalid attendance')
        conn.execute('INSERT OR REPLACE INTO pipeline_attendance VALUES(?,?,?,?,?)',(id,body['event_id'],body['start_at'],body['attendance'],_now()))
        return _touch(conn,id,'attendance',body)
    return _mutate(conn,body,['attendance',id],run)

def add_task(conn,id,body):
    def run():
        opp=_revision(conn,id,body)
        if not body.get('title','').strip(): raise ValueError('Task title required')
        if body.get('due_at'): due_instant(body['due_at'],opp['timezone'])
        responsibility=body.get('responsibility') or 'you'
        if responsibility not in {'you','employer','unknown'}: raise ValueError('Invalid responsibility')
        conn.execute('INSERT INTO pipeline_tasks(id,opportunity_id,title,kind,responsibility,due_at) VALUES(?,?,?,?,?,?)',(str(uuid.uuid4()),id,body['title'],body.get('kind') or 'task',responsibility,body.get('due_at')))
        return _touch(conn,id,'task_added',body)
    return _mutate(conn,body,['task',id],run)

def update_task(conn,id,task_id,body):
    def run():
        _revision(conn,id,body)
        if body.get('state') not in {'open','done','dismissed','snoozed'}: raise ValueError('Invalid task state')
        if body['state']=='snoozed':
            if not body.get('snoozed_until'): raise ValueError('Snooze time required')
            instant(body['snoozed_until'])
        task=conn.execute('SELECT 1 FROM pipeline_tasks WHERE id=? AND opportunity_id=?',(task_id,id)).fetchone()
        if not task:
            action=next((a for a in detail(conn,id)['opportunity']['actions'] if a['id']==task_id),None)
            if not action: raise LookupError('Action not found')
            conn.execute('INSERT INTO pipeline_tasks(id,opportunity_id,title,kind,responsibility,due_at) VALUES(?,?,?,?,?,?)',(task_id,id,action['title'],'recommendation',action['responsibility'],action.get('due_at')))
        conn.execute('UPDATE pipeline_tasks SET state=?,snoozed_until=? WHERE id=? AND opportunity_id=?',(body['state'],body.get('snoozed_until'),task_id,id))
        return _touch(conn,id,'task_updated',body)
    return _mutate(conn,body,['task_update',id,task_id],run)

def add_contact(conn,id,body):
    def run():
        _revision(conn,id,body)
        try: at=datetime.fromisoformat(body['at'].replace('Z','+00:00'))
        except (ValueError,TypeError,AttributeError,KeyError): raise ValueError('Invalid contact time')
        if at.tzinfo is None or at.utcoffset() is None or at>datetime.now(timezone.utc): raise ValueError('Contact time must be timezone-aware and not in the future')
        if type(body.get('expects_reply')) is not bool: raise ValueError('expects_reply must be explicit')
        conn.execute('INSERT INTO pipeline_contacts VALUES(?,?,?,?,?)',(str(uuid.uuid4()),id,body['at'],body['expects_reply'],body.get('note') or ''))
        return _touch(conn,id,'external_contact',body)
    return _mutate(conn,body,['contact',id],run)

def add_note(conn,id,body):
    def run():
        _revision(conn,id,body)
        if not body.get('text','').strip(): raise ValueError('Note required')
        return _touch(conn,id,'note',{'text':body['text']})
    return _mutate(conn,body,['note',id],run)

def _read_cache(conn):
    """One bounded set of SQL reads for a worklist, independent of opportunity count."""
    cache={}
    for key,sql in {
        'opps':'SELECT * FROM pipeline_opportunities',
        'accounts':'SELECT * FROM accounts WHERE enabled=1',
        'links':'SELECT * FROM pipeline_links',
        'attendance':'SELECT * FROM pipeline_attendance',
        'tasks':'SELECT * FROM pipeline_tasks',
        'contacts':'SELECT * FROM pipeline_contacts',
        'events':"SELECT DISTINCT e.* FROM interview_events e JOIN pipeline_links l ON l.kind='event' AND l.source_id=e.id",
        'messages':"SELECT DISTINCT m.id,m.account_id,m.subject,m.date_utc,m.fetched_at,m.from_addr FROM messages m JOIN pipeline_links l ON l.kind='message' AND l.source_id=m.id",
        'sources':"SELECT s.event_id,s.account_id FROM interview_sources s JOIN pipeline_links l ON l.kind='event' AND l.source_id=s.event_id",
        'classes':"SELECT c.* FROM classifications c WHERE c.id=(SELECT c2.id FROM classifications c2 WHERE c2.message_pk=c.message_pk ORDER BY c2.created_at DESC,c2.id DESC LIMIT 1) AND EXISTS(SELECT 1 FROM pipeline_links l WHERE l.kind='message' AND l.source_id=c.message_pk)",
        'removals':'SELECT event_id FROM interview_event_removals',
    }.items(): cache[key]=_rows(conn,sql)
    cache['opps']={r['id']:r for r in cache['opps']}; cache['accounts']={r['id']:r for r in cache['accounts']}
    cache['events']={r['id']:r for r in cache['events']}; cache['messages']={r['id']:r for r in cache['messages']}
    cache['classes']={r['message_pk']:r for r in cache['classes']}; cache['removals']={r['event_id'] for r in cache['removals']}
    cache['sync']={aid:{'mail':None,'calendar':None} for aid in cache['accounts']}
    for row in _rows(conn,'SELECT * FROM pipeline_sync_state'):
        cache['sync'].setdefault(row['account_id'],{})[row['kind']]={k:row[k] for k in ('last_success','last_attempt','error')}
    cache['calendar_removed']=set()
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interview_calendar_state'").fetchone():
        cache['calendar_removed']={(r['event_id'],r['account_id']) for r in _rows(conn,"SELECT s.event_id,s.account_id FROM interview_sources s JOIN interview_calendar_state c ON c.source_id=s.id GROUP BY s.event_id,s.account_id HAVING MAX(c.present)=0")}
    from .followups import _threshold
    cache['thresholds']={aid:_threshold(conn,aid) for aid in cache['accounts']}
    return cache

def detail(conn,id,_cache=None):
    cache=_cache
    if cache:
        if id not in cache['opps']: raise LookupError('Opportunity not found')
        opp=dict(cache['opps'][id]); account=cache['accounts'].get(opp['account_id'])
        if not account: raise LookupError('Enabled profile not found')
    else:
        opp=_opp(conn,id); account=_account(conn,opp['account_id'])
    now=datetime.now(timezone.utc)
    events=[]; messages=[]
    for link in ([l for l in cache['links'] if l['opportunity_id']==id] if cache else _rows(conn,'SELECT * FROM pipeline_links WHERE opportunity_id=?',(id,))):
        try:
            if cache:
                source=(cache['events'] if link['kind']=='event' else cache['messages']).get(link['source_id'])
                allowed=source and (source.get('account_id')==opp['account_id'] if link['kind']=='message' else any(r['event_id']==source['id'] and r['account_id']==opp['account_id'] for r in cache['sources']))
                if not allowed: raise LookupError('Source missing')
            else: source=_source(conn,opp,link['kind'],link['source_id'])
            missing=False
        except LookupError:
            # A reassigned/revoked source is different from deleted historical evidence.
            # Never fall back to its old snapshot while a foreign live source exists.
            if cache:
                exists=(cache['events'] if link['kind']=='event' else cache['messages']).get(link['source_id'])
            else:
                table='interview_events' if link['kind']=='event' else 'messages'
                exists=conn.execute(f'SELECT 1 FROM {table} WHERE id=?',(link['source_id'],)).fetchone()
            if exists: continue
            source=json.loads(link['snapshot']); missing=True
        if link['kind']=='event':
            records=sorted([r for r in cache['attendance'] if r['opportunity_id']==id and r['event_id']==source['id']],key=lambda r:r['recorded_at'],reverse=True) if cache else _rows(conn,'SELECT * FROM pipeline_attendance WHERE opportunity_id=? AND event_id=? ORDER BY recorded_at DESC',(id,source['id']))
            current=next((a for a in records if a['start_at']==source.get('start_at')),None)
            start=instant(source.get('start_at')); end=instant(source.get('end_at')) or start
            removed=source['id'] in cache['removals'] if cache else conn.execute('SELECT 1 FROM interview_event_removals WHERE event_id=?',(source['id'],)).fetchone()
            if cache: removed=removed or (source['id'],opp['account_id']) in cache['calendar_removed']
            elif conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interview_calendar_state'").fetchone():
                state=conn.execute('SELECT MAX(c.present) FROM interview_sources s JOIN interview_calendar_state c ON c.source_id=s.id WHERE s.event_id=? AND s.account_id=?',(source['id'],opp['account_id'])).fetchone()
                removed=removed or state and state[0]==0
            provider='Removed from provider'  if missing or removed else 'Cancelled' if source.get('status') in {'Cancelled','Canceled'} else 'Scheduled'
            events.append(dict(id=source['id'],title=source.get('role') or source.get('company') or 'Interview booking',start_at=source.get('start_at'),end_at=source.get('end_at'),stage=source.get('stage') or 'Not confirmed',provider_state=provider,temporal='Upcoming' if start and start>now else 'In progress' if end and end>=now else 'Ended',attendance=current['attendance'] if current else 'Unconfirmed',attendance_needs_review=bool(records and not current),attendance_history=records,original_booking=json.loads(link['snapshot']).get('start_at'),meeting_url=source.get('meeting_url'),location=source.get('location')))
        else:
            cls=cache['classes'].get(source['id']) if cache else conn.execute('SELECT * FROM classifications WHERE message_pk=? ORDER BY created_at DESC,id DESC LIMIT 1',(source['id'],)).fetchone()
            messages.append(dict(id=source['id'],title=source.get('subject') or '(No subject)',occurred_at=source.get('date_utc') or source.get('fetched_at'),from_addr=source.get('from_addr'),category=cls['category'] if cls else None,summary=cls['summary'] if cls else None,source_missing=missing))
    tasks=[t for t in cache['tasks'] if t['opportunity_id']==id] if cache else _rows(conn,'SELECT * FROM pipeline_tasks WHERE opportunity_id=?',(id,))
    contacts=[c for c in cache['contacts'] if c['opportunity_id']==id] if cache else _rows(conn,'SELECT * FROM pipeline_contacts WHERE opportunity_id=? ORDER BY at',(id,))
    from .followups import _threshold
    actions=actions_for(opp,events,messages,[t for t in tasks if t['kind']!='recommendation'],contacts,business_days=cache['thresholds'][opp['account_id']] if cache else _threshold(conn,opp['account_id']))
    controls={t['id']:t for t in tasks if t['kind']=='recommendation'}
    actions=[a for a in actions if a['id'] not in controls or controls[a['id']]['state']=='open' or controls[a['id']]['state']=='snoozed' and instant(controls[a['id']]['snoozed_until'])<=now]
    upcoming=sorted([e for e in events if e['provider_state']=='Scheduled' and e['temporal'] in {'Upcoming','In progress'}],key=lambda e:e['start_at'])
    opp.update(account_label=account['label'],account_email=account['email'],pinned=bool(opp['pinned']),archived=bool(opp['archived']),actions=actions,next_action=actions[0] if actions else None,next_interview=upcoming[0] if upcoming else None,last_contact_at=max([c['at'] for c in contacts]+[m['occurred_at'] for m in messages if m['occurred_at']],default=None))
    history=[] if cache else _rows(conn,'SELECT * FROM pipeline_history WHERE opportunity_id=? ORDER BY id DESC LIMIT 100',(id,))
    for row in history: row['data']=json.loads(row['data'])
    sent=[]
    if not cache and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='mail_replies'").fetchone():
        sent=_rows(conn,"SELECT r.operation,r.message_pk,r.sent_at,r.status FROM mail_replies r JOIN pipeline_links l ON l.kind='message' AND l.source_id=r.message_pk WHERE l.opportunity_id=? AND r.account_id=? AND r.status='sent'",(id,opp['account_id']))
        for row in sent: row['label']='Sent through OfferPath'
    opp['sync_freshness']=cache['sync'].get(opp['account_id'],{}) if cache else sync_status(conn,opp['account_id'])
    return dict(opportunity=opp,events=events,messages=messages,tasks=tasks,contacts=contacts,history=history,sent=sent)

def list_data(conn,view='active',q='',account_id=None):
    if view not in {'active','attention','upcoming','closed','archived'}: raise ValueError('Invalid view')
    accounts=_rows(conn,'SELECT id,label,email FROM accounts WHERE enabled=1 ORDER BY label')
    values=[]
    cache=_read_cache(conn)
    for row in conn.execute('SELECT p.id FROM pipeline_opportunities p JOIN accounts a ON a.id=p.account_id WHERE a.enabled=1 AND p.redirect_id IS NULL ORDER BY p.pinned DESC,p.updated_at DESC'):
        opp=detail(conn,row['id'],_cache=cache)['opportunity']
        if account_id is not None and opp['account_id']!=account_id: continue
        if q.lower() not in ' '.join(str(opp[k] or '') for k in ('company','role','account_label','application_ref')).lower(): continue
        closed=opp['status'] in {'Accepted','Rejected','Withdrawn','Offer declined','Role closed'}
        if view=='archived' and not opp['archived'] or view!='archived' and opp['archived']: continue
        if view=='closed' and not closed or view not in {'closed','archived'} and closed: continue
        if view=='attention' and not opp['actions'] or view=='upcoming' and not opp['next_interview']: continue
        values.append(opp)
    return dict(opportunities=values,accounts=accounts,review_count=review(conn,account_id=account_id,limit=0)['total'],activated=is_activated(conn),legacy_available=True)

def is_activated(conn):
    row=conn.execute("SELECT value FROM pipeline_settings WHERE key='activated'").fetchone()
    return bool(row and row[0]=='true')

def review(conn,q='',account_id=None,limit=50,offset=0):
    """Read-only preview: each source remains distinct; no broad name/domain joins."""
    items=[]
    decided={r[0] for r in conn.execute('SELECT key FROM pipeline_review_decisions')}
    linked={(r[0],r[1],r[2]) for r in conn.execute('SELECT l.kind,l.source_id,p.account_id FROM pipeline_links l JOIN pipeline_opportunities p ON p.id=l.opportunity_id')}
    candidates=_rows(conn,"SELECT id,account_id,company,role FROM pipeline_opportunities WHERE redirect_id IS NULL AND archived=0")
    removed_events={r[0] for r in conn.execute('SELECT event_id FROM interview_event_removals')}
    accounts={a['id']:a for a in _rows(conn,'SELECT id,label,email FROM accounts WHERE enabled=1')}
    for kind,sql in [('event','SELECT e.id,e.company,e.role,e.start_at,s.account_id FROM interview_events e JOIN interview_sources s ON s.event_id=e.id GROUP BY e.id,s.account_id'),('message',"SELECT m.id,m.account_id,m.subject,m.date_utc,m.fetched_at,m.from_addr,c.company,c.role,c.category FROM messages m JOIN classifications c ON c.id=(SELECT id FROM classifications WHERE message_pk=m.id ORDER BY created_at DESC,id DESC LIMIT 1) WHERE c.category IN ('interview_invite','assessment','info_request','recruiter_outreach','offer','rejection')")]:
        for row in _rows(conn,sql):
            aid=row['account_id']; key=f'{kind}:{aid}:{row["id"]}'
            if aid not in accounts or account_id is not None and aid!=account_id or key in decided or (kind,row['id'],aid) in linked: continue
            title=(row.get('subject') if kind=='message' else row.get('role') or row.get('company')) or 'Unassigned calendar booking'
            if q.lower() not in (title+' '+(row.get('company') or '')).lower(): continue
            removed=kind=='event' and row['id'] in removed_events
            items.append(dict(key=key,kind=kind,account_id=aid,account_label=accounts[aid]['label'],title=title,occurred_at=row.get('start_at') or row.get('date_utc'),company=row.get('company') if kind=='message' else None,role=row.get('role'),reason='Removed evidence retained for reconciliation' if removed else 'Confirm opportunity and evidence; identity has not been inferred',legacy_key=None,legacy_pinned=False,legacy_hidden=bool(removed),suggested_opportunities=[{'id':o['id'],'reason':'Exact company and role text; confirm application attempt before linking'} for o in candidates if kind=='message' and o['account_id']==aid and row.get('company') and row.get('role') and o['company'].strip().casefold()==row['company'].strip().casefold() and o['role'].strip().casefold()==row['role'].strip().casefold()]))
    # Preserve legacy pin/hidden decisions as separate ambiguous migration records.
    for table,field in [('interview_process_pins','legacy_pinned'),('interview_process_removals','legacy_hidden')]:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone(): continue
        for row in _rows(conn,f'SELECT * FROM {table}'):
            key=f'legacy:{table}:{row["organization"]}'
            if key in decided or account_id is not None or q.lower() not in row['organization'].lower(): continue
            items.append(dict(key=key,kind='legacy',account_id=None,account_label='Choose profile',title=row['organization'],occurred_at=None,company=None,role=None,reason='Legacy visibility choice needs explicit opportunity mapping',legacy_key=row['organization'],legacy_pinned=field=='legacy_pinned',legacy_hidden=field=='legacy_hidden'))
    for table, label in [('interview_account_process_state','Legacy profile visibility choice'),('agent_followup_state','Legacy reminder control')]:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone(): continue
        for row in _rows(conn,f'SELECT * FROM {table}'):
            aid=row.get('account_id')
            if aid is not None and aid not in accounts or account_id is not None and aid!=account_id: continue
            if table=='interview_account_process_state' and not row.get('pinned') and not row.get('removed'): continue
            identifier=str(row.get('organization') or row.get('id'))
            key=f'legacy:{table}:{aid}:{identifier}'
            if key in decided or q.lower() not in identifier.lower(): continue
            items.append(dict(key=key,kind='legacy',account_id=aid,account_label=accounts[aid]['label'] if aid in accounts else 'Choose profile',title=identifier,occurred_at=row.get('updated_at'),company=None,role=None,reason=label+' retained; reconcile manually before enabling corresponding new reminders',legacy_key=identifier,legacy_pinned=bool(row.get('pinned')),legacy_hidden=bool(row.get('removed') or row.get('status')=='dismissed'),legacy_status=row.get('status'),snoozed_until=row.get('snoozed_until')))
    # Reconciliation controls must remain reachable before ordinary source pages.
    items.sort(key=lambda item:(item['kind']!='legacy',item.get('occurred_at') or '',item['key']))
    return dict(items=items[max(0,offset):max(0,offset)+max(0,min(limit,200))],total=len(items))

def review_action(conn,body):
    def run():
        key=body['key']; parts=key.split(':'); action=body['action']
        if action not in {'accept','dismiss','link'}: raise ValueError('Invalid review action')
        if action=='dismiss': result={}
        else:
            if len(parts)!=3 or parts[0] not in {'message','event'}: raise ValueError('Legacy choices require manual opportunity mapping')
            kind,aid,sid=parts[0],int(parts[1]),int(parts[2]); _account(conn,aid)
            if action=='accept': id=_insert(conn,dict(body,account_id=aid,company=body.get('company') or 'Unknown company'))
            else: id=body['target_id']; _revision(conn,id,body)
            opp=_opp(conn,id)
            if opp['account_id']!=aid: raise ValueError('Evidence belongs to another profile')
            _link(conn,opp,kind,sid)
            result={'opportunity':_touch(conn,id,'review_accepted',body)}
        conn.execute('INSERT OR REPLACE INTO pipeline_review_decisions VALUES(?,?,?)',(key,action,_now())); return result
    return _mutate(conn,body,'review',run)

def merge(conn,id,body):
    def run():
        target=_revision(conn,id,body); source=_revision(conn,body['source_id'],{'revision':body['source_revision']})
        if source['id']==id or source['account_id']!=target['account_id']: raise ValueError('Merge requires distinct opportunities in one profile')
        if source['status']!=target['status']: raise ValueError('Resolve conflicting statuses before merging')
        for field in ('response_due','stage'):
            unknown=None if field=='response_due' else 'Not confirmed'
            if source[field] and source[field]!=unknown and target[field] and target[field]!=unknown and source[field]!=target[field]: raise ValueError(f'Resolve conflicting {field} before merging')
            if (not target[field] or target[field]==unknown) and source[field] and source[field]!=unknown:
                conn.execute(f'UPDATE pipeline_opportunities SET {field}=? WHERE id=?',(source[field],id))
        conflicts=conn.execute("SELECT 1 FROM pipeline_attendance a JOIN pipeline_attendance b ON a.event_id=b.event_id AND a.start_at=b.start_at WHERE a.opportunity_id=? AND b.opportunity_id=? AND a.attendance<>b.attendance",(id,source['id'])).fetchone()
        if conflicts: raise ValueError('Resolve conflicting attendance before merging')
        for row in _rows(conn,'SELECT * FROM pipeline_links WHERE opportunity_id=?',(source['id'],)):
            conn.execute('INSERT OR IGNORE INTO pipeline_links VALUES(?,?,?,?)',(id,row['kind'],row['source_id'],row['snapshot']))
        conn.execute('DELETE FROM pipeline_links WHERE opportunity_id=?',(source['id'],))
        for task in _rows(conn,'SELECT * FROM pipeline_tasks WHERE opportunity_id=?',(source['id'],)):
            existing=conn.execute('SELECT * FROM pipeline_tasks WHERE opportunity_id=? AND id=?',(id,task['id'])).fetchone()
            if existing:
                if any(existing[k]!=task[k] for k in ('title','kind','responsibility','due_at','state','snoozed_until')): raise ValueError('Resolve conflicting action controls before merging')
                conn.execute('DELETE FROM pipeline_tasks WHERE opportunity_id=? AND id=?',(source['id'],task['id']))
            else: conn.execute('UPDATE pipeline_tasks SET opportunity_id=? WHERE opportunity_id=? AND id=?',(id,source['id'],task['id']))
        conn.execute('UPDATE pipeline_contacts SET opportunity_id=? WHERE opportunity_id=?',(id,source['id']))
        conn.execute('INSERT OR IGNORE INTO pipeline_attendance SELECT ?,event_id,start_at,attendance,recorded_at FROM pipeline_attendance WHERE opportunity_id=?',(id,source['id']))
        conn.execute('UPDATE pipeline_opportunities SET redirect_id=?,revision=revision+1,updated_at=? WHERE id=?',(id,_now(),source['id']))
        _history(conn,source['id'],'merged_into',{'target_id':id}); return _touch(conn,id,'merged_from',{'source_id':source['id']})
    return _mutate(conn,body,['merge',id],run)

def split(conn,id,body):
    def run():
        source=_revision(conn,id,body); new=_insert(conn,dict(body,account_id=source['account_id'],timezone=source['timezone']))
        for kind,key in [('event','event_ids'),('message','message_ids')]:
            for sid in set(body.get(key,[])):
                row=conn.execute('SELECT * FROM pipeline_links WHERE opportunity_id=? AND kind=? AND source_id=?',(id,kind,sid)).fetchone()
                if not row: raise ValueError('Selected evidence is not linked')
                conn.execute('INSERT INTO pipeline_links VALUES(?,?,?,?)',(new,kind,sid,row['snapshot']))
                conn.execute('DELETE FROM pipeline_links WHERE opportunity_id=? AND kind=? AND source_id=?',(id,kind,sid))
                if kind=='event': conn.execute('UPDATE pipeline_attendance SET opportunity_id=? WHERE opportunity_id=? AND event_id=?',(new,id,sid))
        for tid in set(body.get('task_ids',[])):
            cursor=conn.execute('UPDATE pipeline_tasks SET opportunity_id=? WHERE opportunity_id=? AND id=?',(new,id,tid))
            if not cursor.rowcount: raise ValueError('Selected task is not linked')
        _touch(conn,id,'split_to',{'target_id':new}); _history(conn,new,'split_from',{'source_id':id})
        return detail(conn,new)['opportunity']
    return _mutate(conn,body,['split',id],run)

def activate(conn,body):
    def run():
        unresolved=False
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='agent_followup_state'").fetchone():
            unresolved=conn.execute("SELECT 1 FROM agent_followup_state s WHERE NOT EXISTS(SELECT 1 FROM pipeline_review_decisions d WHERE d.key='legacy:agent_followup_state:None:' || s.id) LIMIT 1").fetchone()
        if unresolved: raise ValueError('Reconcile retained legacy reminder controls in Review evidence before activation')
        conn.execute("INSERT OR REPLACE INTO pipeline_settings VALUES('activated','true')")
        return {'activated':True}
    return _mutate(conn,body,'activate',run)


def note_calendar_sync(conn,account_id,errors=None):
    """Record a completed provider attempt inside the collector's transaction.

    A failed/partial attempt preserves last_success. This hook never commits.
    """
    now=_now()
    error='; '.join(str(e) for e in errors) if isinstance(errors,(list,tuple)) else str(errors) if errors else None
    conn.execute("INSERT INTO pipeline_sync_state(account_id,kind,last_success,last_attempt,error) VALUES(?,'calendar',?,?,?) ON CONFLICT(account_id,kind) DO UPDATE SET last_success=COALESCE(excluded.last_success,pipeline_sync_state.last_success),last_attempt=excluded.last_attempt,error=excluded.error",(account_id,None if error else now,now,error))


def sync_status(conn,account_id):
    result={r['kind']:{k:r[k] for k in ('last_success','last_attempt','error')} for r in _rows(conn,'SELECT * FROM pipeline_sync_state WHERE account_id=?',(account_id,))}
    result.setdefault('calendar',None);result.setdefault('mail',None)
    return result
