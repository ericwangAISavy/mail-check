"""Read-only application cohort outcomes; email volume is never a conversion rate."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime,timedelta,timezone

from .confirmation_counts import applications,receipt_stamp,receipt_references
from .payments import ZONE
from .sourcing_verification import company_key,role_key

HORIZONS=(7,14,30)


def report(conn,*,as_of=None,history_since=None,account=None,bidder=None):
    now=as_of or datetime.now(timezone.utc)
    today=now.astimezone(ZONE).date()
    through={str(h):(today-timedelta(days=h+1)).isoformat() for h in HORIZONS}
    scope='';params=[now.isoformat()]
    if account:
        scope+=' AND account_id IN (SELECT id FROM accounts WHERE label=?)';params.append(account)
    if bidder is not None:
        scope+=' AND account_id IN (SELECT account_id FROM bidder_assignments WHERE bidder_id=?)';params.append(bidder)
    rows=conn.execute("""SELECT * FROM application_receipts WHERE category IN
        ('application_ack','interview_invite','rejection') AND julianday(received_at)<=julianday(?)
        """+scope+" ORDER BY julianday(received_at),account_id,message_id",params).fetchall()
    labels={r['id']:r['label'] for r in conn.execute('SELECT id,label FROM accounts')}
    slots={aid:i for i,aid in enumerate(sorted(labels,key=lambda aid:labels[aid].casefold()))}
    assignments=conn.execute('SELECT account_id,start_date,end_date FROM bidder_assignments WHERE bidder_id=?',(bidder,)).fetchall() if bidder is not None else []
    def in_scope(aid,day):
        return (not account or labels.get(aid)==account) and (bidder is None or any(
            r['account_id']==aid and r['start_date']<=day and (not r['end_date'] or r['end_date']>=day) for r in assignments))
    profiles={}
    def profile(aid):
        return profiles.setdefault(aid,dict(id=aid,label=labels.get(aid,f'Profile #{aid} (removed)'),color_slot=slots.get(aid,len(slots)+aid),daily={},duplicates=0,
            unmatched=dict(interview=0,rejection=0)))
    for aid,label in labels.items():
        if (not account or label==account) and (bidder is None or any(r['account_id']==aid for r in assignments)):
            profile(aid)
    groups=applications((r for r in rows if r['category']=='application_ack'),ZONE)
    index=defaultdict(list)
    for group in groups:
        group['outcomes']=dict(interview=None,rejection=None)
        index[group['account_id'],group['company']].append(group)
    # SQLite's julianday sort rounds below a millisecond; bisect requires exact order.
    for values in index.values():values.sort(key=lambda group:group['stamp'])
    stamps={key:[g['stamp'] for g in values] for key,values in index.items()}
    for row in rows:
        if row['category']=='application_ack':continue
        stamp=receipt_stamp(row['received_at'])
        if stamp is None:continue
        company=company_key(row['company']);role=role_key(row['role'])
        refs=receipt_references(row['job_refs'])
        key=(row['account_id'],company)
        values=index.get(key,[])
        end=bisect_right(stamps.get(key,[]),stamp)
        start=bisect_right(stamps.get(key,[]),stamp-timedelta(days=180))
        candidates=[]
        for group in values[start:end]:
            if not company or company in {'unknown','unknown company','other','not provided'}:continue
            if role and group['role'] and role!=group['role']:continue
            if refs and group['refs'] and refs!=group['refs']:continue
            candidates.append((2 if refs and refs==group['refs'] else 1 if role and role==group['role'] else 0,group))
        metric='interview' if row['category']=='interview_invite' else 'rejection'
        if candidates:
            strength=max(x[0] for x in candidates)
            candidates=[g for score,g in candidates if score==strength]
        if len(candidates)==1:
            group=candidates[0]
            previous=group['outcomes'][metric]
            group['outcomes'][metric]=min(previous,stamp) if previous else stamp
        elif in_scope(row['account_id'],stamp.astimezone(ZONE).date().isoformat()):
            profile(row['account_id'])['unmatched'][metric]+=1
    for group in groups:
        aid=group['account_id'];day=group['day']
        if not in_scope(aid,day):continue
        p=profile(aid);p['duplicates']+=group['duplicates']
        bucket=p['daily'].setdefault(day,dict(applications=0,windows={str(h):dict(eligible=0,interview=0,rejection=0,answered=0) for h in HORIZONS}))
        bucket['applications']+=1
        for h in HORIZONS:
            if day>through[str(h)] or (history_since and day<history_since):continue
            w=bucket['windows'][str(h)];w['eligible']+=1
            flags={m:bool(t and t<=group['stamp']+timedelta(days=h)) for m,t in group['outcomes'].items()}
            for m,hit in flags.items():w[m]+=int(hit)
            w['answered']+=int(any(flags.values()))
    return dict(version=1,as_of=now.isoformat(),timezone=str(ZONE),history_since=history_since,
        mature_through=through,followup_days=list(HORIZONS),accounts=sorted(profiles.values(),key=lambda p:p['label'].casefold()))
