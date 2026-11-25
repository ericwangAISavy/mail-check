"""Shared company feedback: fixed badges only, no interview or mailbox disclosure."""
import json
import time

OPTIONS=('in-person','linkedin','fuck','normal')
SCHEMA='''
CREATE TABLE IF NOT EXISTS interview_company_feedback (
 workspace TEXT NOT NULL, author TEXT NOT NULL, company_key TEXT NOT NULL,
 tags TEXT NOT NULL, updated_at REAL NOT NULL,
 PRIMARY KEY(workspace,author,company_key)
);
CREATE INDEX IF NOT EXISTS interview_feedback_company ON interview_company_feedback(company_key);
'''


def company_key(company):
    from .sourcing_verification import company_key as normalize
    if not isinstance(company,str) or not company.strip() or len(company)>200:
        raise ValueError('Set a company of 1–200 characters in interview details first.')
    key=normalize(company)
    if key in ('unknown','unknown company','not provided','other','interview','meeting') or not key:
        raise ValueError('Set the actual company in interview details first.')
    return ''.join(key.split())


def save(conn,workspace,author,company,tags):
    key=company_key(company)
    if not isinstance(tags,list) or any(tag not in OPTIONS for tag in tags) or len(tags)>4:
        raise ValueError('Choose only the four supported feedback badges.')
    chosen=[tag for tag in OPTIONS if tag in tags]
    if not chosen:
        conn.execute('DELETE FROM interview_company_feedback WHERE workspace=? AND author=? AND company_key=?',(workspace,author,key))
    else:
        conn.execute('''INSERT INTO interview_company_feedback VALUES(?,?,?,?,?)
            ON CONFLICT(workspace,author,company_key) DO UPDATE SET tags=excluded.tags,updated_at=excluded.updated_at''',
            (workspace,author,key,json.dumps(chosen),time.time()))


def summary(conn,companies,workspace,author):
    keys={name:company_key(name) for name in companies}
    grouped={key:{'tags':set(),'mine':[]} for key in keys.values()}
    if grouped and conn is not None:
        for row in conn.execute('SELECT workspace,author,company_key,tags FROM interview_company_feedback WHERE company_key IN ('+','.join('?' for _ in grouped)+')',list(grouped)):
            tags=json.loads(row['tags'])
            if not isinstance(tags,list) or any(tag not in OPTIONS for tag in tags):
                raise ValueError('Stored interview feedback is invalid.')
            grouped[row['company_key']]['tags'].update(tags)
            if row['workspace']==workspace and row['author']==author:
                grouped[row['company_key']]['mine']=[tag for tag in OPTIONS if tag in tags]
    return {name:{'tags':[tag for tag in OPTIONS if tag in grouped[key]['tags']],'mine':grouped[key]['mine']} for name,key in keys.items()}
