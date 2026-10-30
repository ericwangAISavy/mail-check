"""Filter incoming job rows only; account history remains untouched."""
import json
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


def company_key(value):
    return ''.join(c for c in value.casefold() if c.isalnum())


def link_key(value):
    value=value.strip()
    try:
        url=urlsplit(value)
        if url.scheme.lower() not in ('http','https') or not url.hostname:return value
        query=sorted((k,v) for k,v in parse_qsl(url.query,keep_blank_values=True)
                     if not k.lower().startswith('utm_') and k.lower() not in ('jr_id','gclid','fbclid'))
        return urlunsplit(('https',url.netloc.lower(),url.path.rstrip('/'),urlencode(query),url.fragment))
    except ValueError:return value


def companies(conn):
    return [r[0] for r in conn.execute('SELECT name FROM sourcing_blocked_companies ORDER BY name COLLATE NOCASE')]


def set_companies(conn,names):
    cleaned={}
    for name in names:
        name=name.strip()
        key=company_key(name)
        if not key or len(name)>200:raise ValueError('Enter company names of 1–200 characters.')
        cleaned.setdefault(key,name)
    if len(cleaned)>1000:raise ValueError('Save up to 1,000 blocked companies.')
    conn.execute('DELETE FROM sourcing_blocked_companies')
    conn.executemany('INSERT INTO sourcing_blocked_companies(key,name) VALUES(?,?)',cleaned.items())


def filter_rows(conn,tab,ids):
    """Only supplied incoming rows can be deleted. Keep the first incoming copy."""
    from .sourcing_structure import reorder, ordered_rows
    from .sourcing_progress import report
    ids=set(ids)
    report(0,len(ids))
    summary={'duplicates':0,'blocked_companies':0}
    if not ids:return summary
    blocked={company_key(name) for name in companies(conn)}
    rows=conn.execute('''SELECT r.id,r.tab_id,c.kind,v.value FROM native_rows r
        JOIN native_tabs t ON t.id=r.tab_id JOIN native_columns c ON c.tab_id=t.id
        JOIN native_cells v ON v.row_id=r.id AND v.column_id=c.id
        WHERE (t.account_id=? OR t.id=?) AND c.kind IN ('company','link','check')
        ORDER BY r.position,r.id''',(tab['account_id'],tab['id']))
    values={}
    for row in rows:values.setdefault(row['id'],{})[row['kind']]=row['value']
    seen={link_key(v['link']) for key,v in values.items() if key not in ids and v.get('link','').strip()}
    processed=0
    for key,v in values.items():
        if key not in ids:continue
        processed+=1
        if processed % 16 == 0:
            report(processed,len(ids))
        link=link_key(v.get('link',''))
        # Incomplete rows are checked once their job URL is entered.
        if not link:continue
        company=company_key(v.get('company',''))
        reason='blocked_companies' if any(name in company for name in blocked) else 'duplicates' if link in seen else None
        if reason:
            conn.execute('DELETE FROM native_rows WHERE id=? AND tab_id=?',(key,tab['id']))
            summary[reason]+=1
        else:seen.add(link)
    report(len(ids),len(ids))
    if sum(summary.values()):reorder(conn,ordered_rows(conn,tab['id']))
    return summary


def result(conn,tab,operation):
    from .native_sourcing import snapshot
    value=snapshot(conn,tab)
    row=conn.execute('SELECT result FROM native_operations WHERE id=?',(operation,)).fetchone()
    if row:
        filtered=json.loads(row[0]).get('filtered')
        if filtered:value['filtered']=filtered
    return value
