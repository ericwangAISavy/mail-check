"""Read-only company, role and link search across retained workspace sheets."""
import base64
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from datetime import date


def search(sources, *, q='', cursor='', day='', limit=100):
    if day:
        try:
            if date.fromisoformat(day).isoformat() != day:
                raise ValueError()
        except ValueError:
            raise ValueError('Choose a valid job date (YYYY-MM-DD).') from None
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
    for identity, filename in sources:
        if time.monotonic() >= deadline:
            incomplete = True
            break
        path = Path(filename)
        if not path.is_file():
            continue
        source = hashlib.sha256(identity.encode()).hexdigest()
        connection = None
        try:
            connection = sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)
            connection.row_factory = sqlite3.Row
            budget = min(deadline,time.monotonic()+.5)
            connection.set_progress_handler(lambda: time.monotonic()>budget,1000)
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'native_rows','native_columns','native_cells'} <= tables:
                continue
            connection.create_function('job_match',3,lambda company,role,link: all(
                word in ' '.join((company or '',role or '',link or '')).casefold() for word in words))
            where = ''
            parameters = []
            if day:
                where += ' AND r.work_date=?'
                parameters.append(day)
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
                WHERE (lower(trim(link.value)) LIKE 'https://%' OR lower(trim(link.value)) LIKE 'http://%')
                AND job_match(company.value,role.value,link.value)
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
