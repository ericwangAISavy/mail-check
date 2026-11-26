"""Read-only company, role and link search across retained workspace sheets."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from datetime import date
from urllib.parse import urlsplit
from .sourcing_filters import link_key


def _one_page_link(link):
    try:
        host=(urlsplit((link or '').strip()).hostname or '').casefold()
        return any(host==domain or host.endswith('.'+domain) for domain in ('greenhouse.io','ashbyhq.com'))
    except ValueError:
        return False


def _owned_links(filename,deadline):
    """Read all retained own links; a partial scan cannot enforce exclusion."""
    path=Path(filename)
    connection=None
    try:
        if not path.is_file():
            return set()
        connection=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)
        budget=min(deadline,time.monotonic()+.5)
        connection.set_progress_handler(lambda:time.monotonic()>budget,1000)
        tables={r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'native_rows','native_columns','native_cells'}<=tables:
            return set()
        values=connection.execute("""SELECT DISTINCT v.value FROM native_rows r
            JOIN native_columns c ON c.tab_id=r.tab_id AND c.kind='link'
            JOIN native_cells v ON v.row_id=r.id AND v.column_id=c.id WHERE trim(v.value)!=''""").fetchall()
        # URL parsing (including cold imports) is CPU work, not a database read.
        # Release the read connection before applying the request's remaining
        # budget; streaming parsing counted that time against SQLite's .5s cap.
        connection.close()
        connection=None
        links=set()
        for index,(value,) in enumerate(values):
            if index%128==0 and time.monotonic()>deadline:
                return None
            links.add(link_key(value))
        return links if time.monotonic()<=deadline else None
    except (OSError,sqlite3.Error):
        return None
    finally:
        if connection is not None:
            connection.close()


def search(sources, *, q='', cursor='', day='', start_date='', end_date='', limit=100, exclude_source=None, exclude_one_page=False, only_one_page=False):
    # Explicit inclusion wins for old/shared URLs containing both flags.
    exclude_one_page=exclude_one_page and not only_one_page
    if type(limit) is not int or not 1<=limit<=500:
        raise ValueError('Choose a page size between 1 and 500.')
    for value in (day,start_date,end_date):
        if not value:
            continue
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError:
            raise ValueError('Choose a valid job date (YYYY-MM-DD).') from None
    if day:
        if start_date or end_date:
            raise ValueError('Choose either a single job date or a date range.')
        start_date=end_date=day
    if start_date and end_date and start_date>end_date:
        raise ValueError('The end date must be on or after the start date.')
    words = q.casefold().split()
    after = None
    if cursor:
        try:
            after = json.loads(base64.urlsafe_b64decode(cursor.encode()).decode())
            if not isinstance(after, list) or len(after) != 3 or not all(isinstance(value,str) for value in after):
                raise ValueError()
        except (ValueError, UnicodeError):
            raise ValueError('Invalid search cursor.') from None
    results, incomplete = [], False
    deadline = time.monotonic()+5
    sources=list(sources)
    owned=set()
    if exclude_source is not None:
        for identity,filename in sources:
            if identity==exclude_source:
                owned=_owned_links(filename,deadline)
                if owned is None:
                    return dict(items=[],next_cursor=None,incomplete=True,incomplete_reason='own_links_unavailable')
                break
    for identity, filename in sources:
        if identity==exclude_source:
            continue
        if time.monotonic() >= deadline:
            incomplete = True
            break
        path = Path(filename)
        source = hashlib.sha256(identity.encode()).hexdigest()
        connection = None
        try:
            if not path.is_file():
                continue
            connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)
            connection.row_factory = sqlite3.Row
            budget = min(deadline,time.monotonic()+.5)
            url_cpu=0.0
            def expired():
                now=time.monotonic()
                return now>deadline or now-url_cpu>budget
            connection.set_progress_handler(expired,1000)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'native_rows','native_columns','native_cells'} <= tables:
                continue
            connection.create_function('job_match',3,lambda company,role,link: all(
                word in ' '.join((company or '',role or '',link or '')).casefold() for word in words))
            def visible(link):
                nonlocal url_cpu
                started=time.monotonic()
                if started>=deadline:
                    raise TimeoutError('Job search deadline expired')
                if not exclude_one_page and not only_one_page and not owned:
                    return True
                try:
                    one_page=_one_page_link(link) if only_one_page or exclude_one_page else False
                    result=(not only_one_page or one_page) and (not exclude_one_page or not one_page) and (not owned or link_key(link or '') not in owned)
                finally:
                    finished=time.monotonic()
                    url_cpu+=max(0,finished-started)
                # Small SQL reads may never invoke the SQLite progress handler.
                if finished>deadline:
                    raise TimeoutError('Job search deadline expired')
                return result
            connection.create_function('job_visible',1,visible)
            where = ''
            parameters = []
            if start_date:
                where += ' AND r.work_date>=?'
                parameters.append(start_date)
            if end_date:
                where += ' AND r.work_date<=?'
                parameters.append(end_date)
            if after:
                where += " AND (COALESCE(r.work_date,'') < ? OR (COALESCE(r.work_date,'')=? AND (? > ? OR (?=? AND r.id>?))))"
                parameters.extend([after[0],after[0],source,after[1],source,after[1],after[2]])
            rows = connection.execute("""
                SELECT r.id,COALESCE(r.work_date,'') AS day,COALESCE(company.value,'') AS company,
                    COALESCE(role.value,'') AS role,trim(link.value,char(9)||char(10)||char(13)||' ') AS link
                FROM native_rows r
                JOIN native_columns lc ON lc.tab_id=r.tab_id AND lc.kind='link'
                JOIN native_cells link ON link.row_id=r.id AND link.column_id=lc.id
                LEFT JOIN native_columns cc ON cc.tab_id=r.tab_id AND cc.kind='company'
                LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=cc.id
                LEFT JOIN native_columns rc ON rc.tab_id=r.tab_id AND rc.kind='role'
                LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=rc.id
                WHERE (lower(trim(link.value,char(9)||char(10)||char(13)||' ')) LIKE 'https://%'
                    OR lower(trim(link.value,char(9)||char(10)||char(13)||' ')) LIKE 'http://%')
                AND job_match(company.value,role.value,link.value)
                AND job_visible(link.value)
                """+where+" ORDER BY COALESCE(r.work_date,'') DESC,r.id LIMIT ?",[*parameters,limit+1]).fetchall()
            results.extend({**dict(row),'source':source} for row in rows)
        except (OSError,sqlite3.Error):
            incomplete = True
        finally:
            if connection is not None:
                connection.close()
    results.sort(key=lambda row:(row['source'],row['id']))
    results.sort(key=lambda row:row['day'],reverse=True)
    page = results[:limit]
    next_cursor = None
    if len(results)>limit and not incomplete:
        last = page[-1]
        next_cursor = base64.urlsafe_b64encode(json.dumps([last['day'],last['source'],last['id']]).encode()).decode()
    return dict(items=[dict(id=hashlib.sha256((row['source']+row['id']).encode()).hexdigest(),
                            company=row['company'],role=row['role'],link=row['link']) for row in page],
                next_cursor=next_cursor,incomplete=incomplete)
