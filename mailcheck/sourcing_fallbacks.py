"""Additional OR matching passes; saved proof stays immutable when shared."""
from datetime import datetime,timedelta,timezone
from functools import lru_cache
import html
import re
from urllib.parse import unquote

from .payments import ZONE
from .sourcing_postings import posting_key,specification,cached_postings,warm_postings

SCHEMA = """
CREATE TABLE IF NOT EXISTS sourcing_match_evidence (
 row_id TEXT PRIMARY KEY REFERENCES native_rows(id) ON DELETE CASCADE,
 account_id INTEGER NOT NULL,message_id TEXT NOT NULL,rule TEXT NOT NULL,
 detail TEXT NOT NULL,posting_key TEXT,posting_title TEXT,recorded_at TEXT NOT NULL
);
"""
_URL=re.compile(r'https?://[^\s<>"\x27\]]+',re.I)
_REAPPLY=re.compile(r'already have your application on file|application has overwritten|applied again for this job',re.I)
_RECEIPT=re.compile(r'(?:thank\s+you|thanks).*?(?:appl(?:ying|ication)|interest)|(?:application|resume).*?(?:received|review)|received.*?application',re.I|re.S)


def candidate_rows(conn,accounts,row_ids=None):
    rows=[]
    accounts=sorted(set(accounts))
    if row_ids is not None:
        row_ids=sorted(set(row_ids))
        if not row_ids:
            return []
        if len(row_ids)>400:
            return [row for offset in range(0,len(row_ids),400) for row in candidate_rows(conn,accounts,row_ids[offset:offset+400])]
    for offset in range(0,len(accounts),400):
        batch=accounts[offset:offset+400]
        rows.extend(dict(r) for r in conn.execute("""SELECT r.id,r.tab_id,r.work_date,t.account_id,hc.id AS check_column,
            company.value AS company,role.value AS role,link.value AS link,checked.value AS checked,
            e.confirmed_at,e.source AS check_source
            FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id JOIN accounts a ON a.id=t.account_id
            JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
            JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
            JOIN native_columns rc ON rc.tab_id=t.id AND rc.kind='role'
            JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
            JOIN native_columns hc ON hc.tab_id=t.id AND hc.kind='check'
            LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=cc.id
            LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=rc.id
            LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=lc.id
            LEFT JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=hc.id
            LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
            WHERE t.archived=0 AND r.work_date IS NOT NULL AND trim(COALESCE(link.value,''))!=''
            AND t.account_id IN ("""+','.join('?' for _ in batch)+')'+(' AND r.id IN ('+','.join('?' for _ in row_ids)+')' if row_ids is not None else ''),[*batch,*(row_ids or [])]))
    return rows


@lru_cache(maxsize=8192)
def _company_key(value):
    from .sourcing_verification import company_key
    return company_key(value)


@lru_cache(maxsize=8192)
def _alias(value):
    words=_company_key((value or '').replace('&',' and ')).split()
    return ''.join(w for w in words if w!='and')


def _body(value):
    # Plain text is primary. HTML links are examined separately, not rendered.
    return str(value.get('body_text') or '')[:16000]


@lru_cache(maxsize=8192)
def _employer_pattern(company):
    name=_company_key(company)
    if len(name)<3 or name in {'greenhouse','lever','ashby','workday','smartrecruiters','other','unknown'}:
        return None
    words=[re.escape(w) for w in name.split()]
    pattern=r'\b(?:at|to|with|from|joining|join|in|formerly|formally)\s+(?:the\s+)?'+r'[\W_]*'.join(words)+r'\b'
    return re.compile(pattern,re.I)


def _employer(text,company):
    pattern=_employer_pattern(company)
    return bool(pattern and pattern.search(text[:6000]))


def _related(receipt,row,fact=None):
    from .sourcing_verification import _contains_name
    cache=receipt.setdefault('_employer_relations',{})
    key=(row['company'],fact.get('company') if fact else None)
    if key in cache:
        return cache[key]
    left,right=_company_key(receipt['company']),_company_key(row['company'])
    words=receipt.get('_body_words')
    if words is None:
        words=set(re.findall(r'[^\W_]+',_body(receipt).casefold()))
        receipt['_body_words']=words
    first=right.split()[0] if right else ''
    related=(_contains_name(left,right) or bool(_alias(receipt['company']) and _alias(receipt['company'])==_alias(row['company']))
        or bool(first in words and _employer(_body(receipt),row['company']))
        or bool(fact and _alias(fact.get('company')) and _alias(fact['company'])==_alias(receipt['company'])))
    cache[key]=related
    return related


def _content(conn,receipts):
    found={}
    for account in sorted({r['account_id'] for r in receipts}):
        ids=sorted({r['message_id'] for r in receipts if r['account_id']==account})
        for offset in range(0,len(ids),400):
            batch=ids[offset:offset+400]
            for row in conn.execute('SELECT account_id,message_id,subject,substr(body_text,1,16000) AS body_text,substr(original_html,1,64000) AS original_html FROM messages WHERE account_id=? AND message_id IN ('+','.join('?' for _ in batch)+')',[account,*batch]):
                found[account,row['message_id']]=dict(row)
    return [{**r,**found.get((r['account_id'],r['message_id']),{})} for r in receipts]


def _reservations(conn,receipts,*,with_rows=False):
    reserved={}
    for account in sorted({r['account_id'] for r in receipts}):
        ids=sorted({r['message_id'] for r in receipts if r['account_id']==account})
        for offset in range(0,len(ids),400):
            batch=ids[offset:offset+400]
            for row in conn.execute("""SELECT e.message_id,r.id FROM sourcing_check_activity e JOIN native_rows r ON r.id=e.row_id
                JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
                JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
                JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='check'
                JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id AND c.value='true'
                JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
                JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id AND trim(l.value)!=''
                WHERE t.account_id=? AND e.message_id IN ("""+','.join('?' for _ in batch)+')',[account,*batch]):
                reserved.setdefault((account,row['message_id']),set()).add(row['id'])
    return reserved if with_rows else set(reserved)


def _reference_text(receipt):
    if '_reference_text' not in receipt:
        receipt['_reference_text']=unquote(unquote(html.unescape(str(receipt.get('subject') or '')+' '+_body(receipt)+' '+str(receipt.get('original_html') or ''))))
    return receipt['_reference_text']


def _job_url(url):
    if specification(url):
        return True
    from urllib.parse import urlsplit
    try:
        path=urlsplit(url).path
        return bool(re.search(r'/(?:jobs?|careers?|positions?|openings?)/[^/]+',path,re.I))
    except ValueError:
        return False


def _references(receipt):
    if '_references' in receipt:
        return receipt['_references']
    text=_reference_text(receipt)
    tokens=set()
    for raw in _URL.findall(text):
        raw=raw.rstrip('.,);')
        spec=specification(raw)
        if spec:
            tokens.add(spec[2])
        elif _job_url(raw):
            tokens.add(raw.split('?')[0])
    tokens.update(re.findall(r'(?<![A-Za-z0-9])R[-_]?\d{4,}(?![A-Za-z0-9])',text,re.I))
    tokens.update(re.findall(r'\b(?:job|requisition|req|position)\s*(?:id|number|no\.?|#)?\s*[:#-]?\s*([A-Za-z]*[-_]?\d{4,})\b',text,re.I))
    tokens.update(re.findall(r'\b(?:job|posting|requisition|position)\s*(?:id|identifier|#)\s*[:#-]?\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\b',text,re.I))
    receipt['_references']=tokens
    return tokens


def historical_rows(conn,receipts,*,early_since):
    """Retrieve history by explicit references, not by scanning all old cells."""
    recent=[]
    reserved=_reservations(conn,receipts)
    for r in receipts:
        if (r['account_id'],r['message_id']) in reserved:
            continue
        try:
            stamp=datetime.fromisoformat(r['received_at'].replace('Z','+00:00'))
            if stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(ZONE).date()>=early_since:
                recent.append(dict(r))
        except (ValueError,TypeError):
            continue
    tokens={}
    for receipt in _content(conn,recent):
        refs=_references(receipt)
        if refs:
            tokens.setdefault(receipt['account_id'],set()).update(refs)
    ids=set()
    for account,values in tokens.items():
        values=sorted(values)
        for offset in range(0,len(values),100):
            batch=values[offset:offset+100]
            ids.update(r[0] for r in conn.execute("""SELECT l.row_id FROM native_tabs t
                JOIN native_columns k ON k.tab_id=t.id AND k.kind='link'
                JOIN native_cells l ON l.column_id=k.id WHERE t.account_id=? AND t.archived=0 AND ("""+
                ' OR '.join('instr(lower(l.value),lower(?))>0' for _ in batch)+')',[account,*batch]))
    return candidate_rows(conn,tokens,ids) if ids else []


def _identity(receipt,row):
    key=row.get('_posting_key') or posting_key(row['link'])
    if not key:
        return False
    text=_reference_text(receipt)
    if '_job_keys' not in receipt:
        receipt['_job_keys']={posting_key(raw.rstrip('.,);')) for raw in _URL.findall(text) if _job_url(raw.rstrip('.,);'))}
    if key in receipt['_job_keys']:
        return True
    spec=row.get('_specification') or specification(row['link'])
    # Standalone requisition IDs require independent employer evidence.
    if not spec or not _related(receipt,row):
        return False
    provider,_,jid=spec
    if provider=='workday' or (provider in {'ashby','lever'} and len(jid)==36):
        return bool(re.search(r'(?<![A-Za-z0-9])'+re.escape(jid)+r'(?![A-Za-z0-9])',text,re.I))
    if provider=='greenhouse':
        return bool(re.search(r'\b(?:job|requisition|req|position)\s*(?:id|number|no\.?|#)?\s*[:#-]?\s*'+re.escape(jid)+r'\b',text,re.I))
    return False


def extend_plan(conn,rows,receipts,legacy,*,early_since,postings=None,evidence=None,explanations=None):
    from .sourcing_verification import _matching_plan,role_key,_contains_name,MATCHING_WINDOW_DAYS
    evidence=evidence if evidence is not None else {}
    result=dict(legacy)
    # Saved checks and legacy matches cannot be replaced by fallback evidence.
    if not any(row['checked'] != 'true' and row['id'] not in legacy and row['work_date']
               and (row['link'] or '').strip() for row in rows):
        return result
    reservations=_reservations(conn,receipts,with_rows=True)
    used=set()
    byid={r['id']:dict(r) for r in rows}
    for rid,match in legacy.items():
        reservations.setdefault((byid[rid]['account_id'],match[1]),set()).add(rid)
    reserved_ids=set().union(*reservations.values()) if reservations else set()
    recent=[]
    for r in receipts:
        if (r['account_id'],r['message_id']) in used:
            continue
        try:
            stamp=datetime.fromisoformat(r['received_at'].replace('Z','+00:00'))
            stamp=stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc)
        except (ValueError,TypeError):
            continue
        if stamp.astimezone(ZONE).date()>=early_since:
            recent.append({**dict(r),'stamp':stamp})
    if not recent:
        return result
    recent.sort(key=lambda r:(r['stamp'],r['message_id']))
    recent=_content(conn,recent)
    recent=[r for r in recent if _RECEIPT.search(_body(r)) and not _REAPPLY.search(_body(r))]
    # Checked bindings participate as evidence for sharing, never as new writes.
    available=[dict(r) for r in rows if (r['checked']!='true' or r['id'] in reserved_ids) and r['work_date'] and (r['link'] or '').strip()]
    postings=postings if postings is not None else cached_postings(conn,[posting_key(r['link']) for r in available])
    for row in available:
        row['_posting_key']=posting_key(row['link'])
        row['_specification']=specification(row['link'])
    facts_by_id={r['id']:postings.get(r['_posting_key']) or {} for r in available} if postings else {}

    def record(rid,receipt,rule,detail):
        if rid in result or byid[rid]['checked']=='true':
            return
        result[rid]=(receipt['stamp'],receipt['message_id'])
        used.add((receipt['account_id'],receipt['message_id']))
        row=byid[rid];fact=postings.get(posting_key(row['link'])) or {}
        evidence[rid]={'rule':rule,'detail':detail,'account_id':receipt['account_id'],'message_id':receipt['message_id'],
            'posting_key':posting_key(row['link']),'posting_title':fact.get('title','')}

    def can_share(receipt,ids):
        bound=reservations.get((receipt['account_id'],receipt['message_id']))
        return not bound or bool(bound.intersection(ids))

    # Explicit identities have priority among the new alternatives.
    for receipt in recent:
        if not _references(receipt):
            continue
        candidates=[r for r in available if r['account_id']==receipt['account_id'] and r['work_date']<=receipt['stamp'].astimezone(ZONE).date().isoformat() and _identity(receipt,r)]
        if candidates and can_share(receipt,{r['id'] for r in candidates}):
            for row in candidates:
                record(row['id'],receipt,'job_identity','Saved email identifies this application URL or requisition ID.')
    pending=[r for r in recent if (r['account_id'],r['message_id']) not in used and not _references(r)]
    unique=_matching_plan(conn,available,pending,early_since=early_since)
    byreceipt={(r['account_id'],r['message_id']):r for r in pending}
    groups={}
    for rid,(_,mid) in unique.items():
        groups.setdefault((byid[rid]['account_id'],mid),[]).append(rid)
    for key,ids in groups.items():
        receipt=byreceipt[key]
        if can_share(receipt,ids):
            for rid in ids:
                record(rid,receipt,'unique_unchecked','Unchecked row matches the existing company, role and date criteria; role-qualified confirmations may support multiple rows.')
    for receipt in recent:
        # A role-qualified confirmation also supports name/role matches even
        # when it contains a link to another job ID, as requested. Company-only
        # recovery keeps its explicit identity when one is available.
        if not (receipt['role'] or '').strip() and _references(receipt):
            continue
        day=receipt['stamp'].astimezone(ZONE).date()
        matches=[]
        for row in available:
            if row['account_id']!=receipt['account_id'] or not (day-timedelta(days=MATCHING_WINDOW_DAYS-1)).isoformat()<=row['work_date']<=day.isoformat():
                continue
            fact=facts_by_id.get(row['id']) or {}
            if not _related(receipt,row,fact):
                continue
            email_role=role_key(receipt['role']);saved_role=role_key(row['role'])
            body_role=role_key(_body(receipt));actual_role=role_key(fact.get('title'))
            if not email_role:
                matches.append((row,'company_only','Confirmation has no role or job reference; employer evidence supports all eligible company rows.',0))
            elif actual_role and _contains_name(actual_role,body_role):
                matches.append((row,'posting_title','Email role is supported by the actual linked posting title.',int(bool(email_role) and actual_role==email_role)))
            elif email_role and _contains_name(email_role,saved_role) and _contains_name(email_role,body_role):
                matches.append((row,'company_alias','Email employer evidence or company-name normalization and explicit role identify the row.',0))
            elif saved_role and _contains_name(saved_role,body_role):
                matches.append((row,'email_details','Explicit employer and role in the saved email recover missing classification details.',0))
        if any(m[3] for m in matches):
            matches=[m for m in matches if m[3]]
        if matches and can_share(receipt,{r['id'] for r,_,_,_ in matches}):
            for row,rule,detail,_ in matches:
                record(row['id'],receipt,rule,detail)
        elif len(matches)>1 and explanations is not None:
            for row,_,_,_ in matches:
                explanations[row['id']]=f'Fallback review: {len(matches)} unchecked job IDs match this email; no additional application was counted.'
    return result


def save_evidence(conn,row_id,evidence):
    if not evidence:
        return
    conn.execute('INSERT INTO sourcing_match_evidence VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(row_id) DO UPDATE SET account_id=excluded.account_id,message_id=excluded.message_id,rule=excluded.rule,detail=excluded.detail,posting_key=excluded.posting_key,posting_title=excluded.posting_title,recorded_at=excluded.recorded_at WHERE sourcing_match_evidence.message_id IS NOT excluded.message_id OR sourcing_match_evidence.account_id IS NOT excluded.account_id',
        (row_id,evidence['account_id'],evidence['message_id'],evidence['rule'],evidence['detail'],evidence.get('posting_key'),evidence.get('posting_title'),datetime.now(timezone.utc).isoformat()))


def prepare_postings(conn,*,since,until,accounts=None,network=True):
    """Warm only employer-compatible title mismatches, before verification locks."""
    if not network or conn.in_transaction:
        return
    lower=datetime.combine(since,datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    upper=datetime.combine(until+timedelta(days=1),datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    if accounts is not None and not accounts:
        return
    scopes=[None] if accounts is None else [sorted(accounts)[i:i+400] for i in range(0,len(accounts),400)]
    receipts=[]
    for scope in scopes:
        clause='' if scope is None else ' AND account_id IN ('+','.join('?' for _ in scope)+')'
        receipts.extend(dict(r) for r in conn.execute("SELECT account_id,message_id,received_at,company,role FROM application_receipts WHERE category='application_ack' AND julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?)"+clause+" ORDER BY received_at DESC LIMIT 1000",[lower,upper,*(scope or [])]))
    receipts=sorted(receipts,key=lambda r:r['received_at'],reverse=True)[:1000]
    reserved=_reservations(conn,receipts)
    receipts=_content(conn,[r for r in receipts if (r['account_id'],r['message_id']) not in reserved])
    rows=candidate_rows(conn,{r['account_id'] for r in receipts})
    from .sourcing_verification import role_key,_contains_name,_matching_plan
    # Do not spend the request budget on cases that already resolve locally.
    legacy=_matching_plan(conn,rows,receipts,early_since=since)
    local=extend_plan(conn,rows,receipts,legacy,early_since=since,postings={})
    row_accounts={r['id']:r['account_id'] for r in rows}
    resolved={(row_accounts[rid],match[1]) for rid,match in local.items()}
    receipts=[r for r in receipts if (r['account_id'],r['message_id']) not in resolved]
    current_counts={}
    for receipt in receipts:
        try:
            stamp=datetime.fromisoformat(receipt['received_at'].replace('Z','+00:00'))
            day=stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(ZONE).date().isoformat()
        except (ValueError,TypeError):
            continue
        current_counts[receipt['account_id'],receipt['message_id']]=sum(r['checked']!='true' and r['account_id']==receipt['account_id'] and r['work_date']==day and _related(receipt,r) for r in rows)
    urls=[]
    for row in rows:
        if row['checked']=='true':
            continue
        for receipt in receipts:
            if row['account_id']!=receipt['account_id']:
                continue
            try:
                day=datetime.fromisoformat(receipt['received_at'].replace('Z','+00:00'))
                day=day.replace(tzinfo=day.tzinfo or timezone.utc).astimezone(ZONE).date()
            except (ValueError,TypeError):
                continue
            if not (day-timedelta(days=9)).isoformat()<=row['work_date']<=day.isoformat():
                continue
            if not _related(receipt,row):
                continue
            # A title qualifier or a missing extracted role may distinguish
            # otherwise identical sheet titles after reading the real posting.
            raw_role=role_key(receipt['role'])
            body_named_role=bool(re.search(r'\b(?:for|our)\s+(?:the\s+)?[A-Za-z][^.!?\n]{3,160}\b(?:role|position|at)\b',_body(receipt),re.I))
            if (raw_role and raw_role!=role_key(row['role'])) or (not raw_role and body_named_role):
                count=current_counts.get((receipt['account_id'],receipt['message_id']),0)
                priority=(int(count!=1),int(not _contains_name(raw_role,role_key(row['role']))),int(row['work_date']!=day.isoformat()))
                urls.append((priority,row['link']));break
    warm_postings(conn,[url for _,url in sorted(urls,key=lambda item:item[0])])
