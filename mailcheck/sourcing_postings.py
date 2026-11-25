"""Bounded public ATS metadata; no mailbox data is sent to posting servers."""
from concurrent.futures import ThreadPoolExecutor, wait
import hashlib
import html
import json
import re
import sqlite3
import time
from threading import BoundedSemaphore
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

import httpx

SCHEMA = """
CREATE TABLE IF NOT EXISTS sourcing_posting_cache (
 key TEXT PRIMARY KEY,url TEXT NOT NULL,title TEXT NOT NULL,company TEXT NOT NULL,
 checked_at REAL NOT NULL,expires_at REAL NOT NULL,status TEXT NOT NULL
);
"""
_SEGMENT = re.compile(r'^[A-Za-z0-9_-]{1,100}$')
_UUID = re.compile(r'^[0-9a-fA-F-]{36}$')
_TRACKING = {'jr_id','source','gh_src','lever-source','ref','referrer','gclid','fbclid'}
_LOOKUP_SLOTS = BoundedSemaphore(8)


class PostingBusy(Exception):
    """Another workspace owns the process-wide lookup capacity; retry later."""


def specification(url):
    """Return public ATS coordinates only, never a user-supplied fetch host."""
    try:
        parts=urlsplit(html.unescape(str(url)).strip())
        if parts.scheme!='https' or parts.username or parts.password or parts.port not in (None,443):
            return None
        host=(parts.hostname or '').lower()
        path=[unquote(p) for p in parts.path.split('/') if p]
        query=dict(parse_qsl(parts.query))
        if host=='sjobs.brassring.com':
            coordinates={k.casefold():v for k,v in parse_qsl(parts.query)}
            partner,jid=coordinates.get('partnerid',''),coordinates.get('jobid','')
            if partner.isdigit() and jid.isdigit():
                return 'brassring',partner,jid
        if host in {'boards.greenhouse.io','job-boards.greenhouse.io'}:
            if path[:1]==['embed']:
                org,jid=query.get('for',''),query.get('token','')
            elif len(path)>=3 and path[1]=='jobs':
                org,jid=path[0],path[2]
            else:
                return None
            if _SEGMENT.fullmatch(org) and jid.isdigit():
                return 'greenhouse',org,jid
        if host in {'jobs.ashbyhq.com','jobs.lever.co','jobs.eu.lever.co'} and len(path)>=2:
            org,jid=path[:2]
            if _SEGMENT.fullmatch(org) and _UUID.fullmatch(jid):
                return ('ashby' if host=='jobs.ashbyhq.com' else 'lever'),org,jid.lower()
        if host.endswith('.myworkdayjobs.com'):
            match=re.search(r'(?<![A-Za-z0-9])(R[-_]?\d{4,})(?![A-Za-z0-9])',unquote(parts.path),re.I)
            if match:
                return 'workday',host,match[1].upper()
        if host.endswith('.workable.com'):
            if host=='apply.workable.com' and len(path)>=3 and path[1]=='j' and _SEGMENT.fullmatch(path[0]) and re.fullmatch(r'[A-Za-z0-9]{4,100}',path[2]):
                return 'workable',path[0],path[2]
            match=re.search(r'/(?:j|jobs)/([A-Za-z0-9]{4,})',parts.path)
            if match:
                return 'workable',host,match[1]
    except (ValueError,TypeError):
        pass
    return None


def posting_key(url):
    spec=specification(url)
    if spec:
        return json.dumps(spec,separators=(',',':'))
    try:
        p=urlsplit(html.unescape(str(url)).strip())
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443) or not p.path.strip('/'):
            return None
        query=sorted((k,v) for k,v in parse_qsl(p.query) if k.casefold() not in _TRACKING and not k.casefold().startswith('utm_'))
        canonical=urlunsplit(('https',p.netloc.lower(),p.path.rstrip('/'),urlencode(query),''))
        return 'url:'+hashlib.sha256(canonical.encode()).hexdigest()
    except (ValueError,TypeError):
        return None


def _download(url):
    """Only callers constructing fixed public ATS endpoints may use this helper."""
    started=time.monotonic()
    with httpx.Client(timeout=httpx.Timeout(2.0),follow_redirects=False,trust_env=False) as client:
        with client.stream('GET',url,headers={'User-Agent':'OfferPath/JobEvidence','Accept':'application/json,text/html'}) as response:
            response.raise_for_status()
            if response.status_code!=200:
                raise ValueError('Posting did not return content')
            chunks=[];size=0
            for chunk in response.iter_bytes():
                size+=len(chunk)
                if size>1024*1024 or time.monotonic()-started>3:
                    raise ValueError('Posting response limit exceeded')
                chunks.append(chunk)
            return b''.join(chunks).decode('utf-8',errors='replace')


def fetch_posting(url):
    spec=specification(url)
    if not spec:
        return None
    if not _LOOKUP_SLOTS.acquire(blocking=False):
        raise PostingBusy()
    try:
        return _fetch_posting(url,spec)
    finally:
        _LOOKUP_SLOTS.release()


def _fetch_posting(url,spec):
    provider,org,jid=spec
    if provider=='greenhouse':
        target=f'https://boards-api.greenhouse.io/v1/boards/{quote(org,safe="")}/jobs/{jid}'
        data=json.loads(_download(target))
        if not isinstance(data,dict):
            return None
        title=data.get('title')
        company=data.get('company_name','')
    elif provider in {'ashby','lever','workable'}:
        if provider=='workable':
            if not _SEGMENT.fullmatch(org):
                return None
            target=f'https://apply.workable.com/{quote(org,safe="")}/j/{jid}/'
        else:
            host='jobs.ashbyhq.com' if provider=='ashby' else 'jobs.lever.co'
            target=f'https://{host}/{quote(org,safe="")}/{jid}'
        page=_download(target)
        match=re.search(r'<title[^>]*>(.*?)</title>',page,re.I|re.S)
        if not match:
            return None
        label=html.unescape(re.sub('<[^>]+>','',match[1])).strip()
        if provider=='ashby' and ' @ ' in label:
            title,company=label.rsplit(' @ ',1)
        elif provider=='lever' and ' - ' in label:
            company,title=label.split(' - ',1)
        elif provider=='workable' and ' - ' in label:
            title,company=label.rsplit(' - ',1)
        else:
            return None
    else:
        return None
    if not isinstance(title,str) or not title.strip() or not isinstance(company,str):
        return None
    return {'title':html.unescape(title).strip()[:240],'company':html.unescape(company).strip()[:200],'url':url}


def cached_postings(conn,keys):
    keys=sorted(k for k in set(keys) if k)
    facts={};now=time.time()
    try:
        for offset in range(0,len(keys),400):
            batch=keys[offset:offset+400]
            for row in conn.execute('SELECT key,url,title,company,checked_at FROM sourcing_posting_cache WHERE status=? AND expires_at>? AND key IN ('+','.join('?' for _ in batch)+')',['available',now,*batch]):
                facts[row['key']]={k:row[k] for k in ('url','title','company','checked_at')}
    except sqlite3.OperationalError as exc:
        if 'no such table' not in str(exc):
            raise
    return facts


def warm_postings(conn,urls):
    """Call before a write transaction. Slow/missing providers never fail matching."""
    if conn.in_transaction:
        return
    now=time.time();todo={}
    for url in urls:
        spec=specification(url)
        if not spec or spec[0] not in {'greenhouse','ashby','lever','workable'}:
            continue
        key=posting_key(url)
        row=conn.execute('SELECT expires_at FROM sourcing_posting_cache WHERE key=?',(key,)).fetchone()
        if not row or row['expires_at']<=now:
            todo.setdefault(key,url)
        if len(todo)>=24:
            break
    if not todo:
        return
    executor=ThreadPoolExecutor(max_workers=8,thread_name_prefix='posting-evidence')
    futures={executor.submit(fetch_posting,url):(key,url) for key,url in todo.items()}
    done,_=wait(futures,timeout=4)
    executor.shutdown(wait=False,cancel_futures=True)
    updates=[]
    for future in done:
        key,url=futures[future]
        try:
            fact=future.result()
        except PostingBusy:
            # Local saturation is not evidence that the external posting failed.
            continue
        except (httpx.HTTPError,OSError,ValueError,TypeError):
            fact=None
        status='available' if fact else 'unavailable'
        updates.append((key,url,fact['title'] if fact else '',fact['company'] if fact else '',now,now+(86400 if fact else 600),status))
    if updates:
        timeout=conn.execute('PRAGMA busy_timeout').fetchone()[0]
        try:
            conn.execute('PRAGMA busy_timeout=0')
            conn.executemany('INSERT INTO sourcing_posting_cache VALUES(?,?,?,?,?,?,?) ON CONFLICT(key) DO UPDATE SET url=excluded.url,title=excluded.title,company=excluded.company,checked_at=excluded.checked_at,expires_at=excluded.expires_at,status=excluded.status',updates)
            conn.execute('DELETE FROM sourcing_posting_cache WHERE key IN (SELECT key FROM sourcing_posting_cache ORDER BY checked_at DESC LIMIT -1 OFFSET 10000)')
            conn.commit()
        except sqlite3.OperationalError as exc:
            conn.rollback()
            if ((getattr(exc,'sqlite_errorcode',0) or 0)&255) not in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
                raise
        finally:
            conn.execute(f'PRAGMA busy_timeout={timeout}')
