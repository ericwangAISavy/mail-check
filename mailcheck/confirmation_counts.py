"""Read-only distinct application confirmations, without changing email records."""
from collections import defaultdict
from datetime import datetime,timedelta,timezone
import json


def job_references(subject,body,html):
    # Reuse locally extracted job references; never fetch any email URL.
    from .sourcing_fallbacks import _references
    refs=_references({'subject':(subject or '')[:2000],'body_text':(body or '')[:16000],
                      'original_html':(html or '')[:64000]})
    return json.dumps(sorted({ref.casefold() for ref in refs if not ref.startswith(('http://','https://')) and len(ref)<=120}))


def receipt_stamp(value):
    try:
        stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
        return stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError,TypeError,AttributeError,OverflowError):
        return None


def receipt_references(value):
    try:
        refs=json.loads(value)
    except (ValueError,TypeError):
        return set()
    return {ref.casefold() for ref in refs if isinstance(ref,str) and ref} if isinstance(refs,list) else set()


def counts(conn,start,end):
    from .payments import ZONE
    lower=datetime.combine(start,datetime.min.time(),ZONE).astimezone(timezone.utc)
    upper=datetime.combine(end+timedelta(days=1),datetime.min.time(),ZONE).astimezone(timezone.utc)
    rows=conn.execute('''SELECT account_id,message_id,received_at,company,role,job_refs FROM application_receipts
        WHERE category='application_ack' AND julianday(received_at)>=julianday(?)
        AND julianday(received_at)<julianday(?) ORDER BY julianday(received_at),account_id,message_id''',
        (lower.isoformat(),upper.isoformat()))
    totals=defaultdict(int)
    for group in applications(rows,ZONE):
        totals[group['account_id'],group['day']]+=1
    return dict(totals)


def applications(rows,zone):
    """Same-day confirmation identities shared by payment and outcome reports."""
    from .sourcing_verification import company_key,role_key
    groups=defaultdict(list)
    for row in rows:
        stamp=receipt_stamp(row['received_at'])
        if stamp is None:continue
        day=stamp.astimezone(zone).date().isoformat()
        company=company_key(row['company']);role=role_key(row['role'])
        refs=receipt_references(row['job_refs'])
        # Missing company evidence cannot identify a duplicate application.
        identity=company if company and company not in {'unknown','unknown company','other','not provided'} else 'message:'+row['message_id']
        key=(row['account_id'],day,identity)
        candidates=groups[key]
        compatible=[]
        for group in candidates:
            if role and group['role'] and role!=group['role']:
                continue
            if refs and group['refs']:
                # Shared footer/recommended-job links must not bridge two
                # confirmations that contain different explicit references.
                if refs==group['refs']:compatible.append(group)
            elif not role or not group['role'] or role==group['role']:
                compatible.append(group)
        if len(compatible)==1:
            group=compatible[0]
            group['refs'].update(refs)
            group['role']=group['role'] or role
            group['duplicates']+=1
            group['stamp']=min(group['stamp'],stamp)
        else:
            candidates.append(dict(refs=refs,role=role,company=company,
                account_id=row['account_id'],day=day,stamp=stamp,duplicates=0))
    return [group for candidates in groups.values() for group in candidates]
