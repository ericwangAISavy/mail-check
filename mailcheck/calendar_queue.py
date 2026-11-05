"""Durable, fair calendar analysis work; no Graph calls are needed to resume."""
from __future__ import annotations
import hashlib
import json
import time
from dataclasses import asdict
from datetime import datetime
from .calendar_events import CalendarBooking


def enqueue(conn, account_id, booking, *, cached, max_chars):
    value = asdict(booking)
    value['description'] = booking.description[:max_chars]
    for name in ('start','end','updated_at'):
        value[name] = value[name].isoformat() if value[name] else None
    payload = json.dumps(value, sort_keys=True)
    version = hashlib.sha256(payload.encode()).hexdigest()
    now = time.time()
    conn.execute('''INSERT INTO calendar_analysis_tasks(account_id,external_id,version,booking,start_at,state,last_seen)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_id,external_id) DO UPDATE SET
        booking=excluded.booking,start_at=excluded.start_at,last_seen=excluded.last_seen,
        state=CASE WHEN excluded.state='done' THEN 'done'
            WHEN calendar_analysis_tasks.version!=excluded.version OR calendar_analysis_tasks.state IN ('done','cancelled') THEN 'pending'
            ELSE calendar_analysis_tasks.state END,
        attempts=CASE WHEN calendar_analysis_tasks.version!=excluded.version THEN 0 ELSE calendar_analysis_tasks.attempts END,
        next_attempt=CASE WHEN calendar_analysis_tasks.version!=excluded.version OR excluded.state='done' THEN 0 ELSE calendar_analysis_tasks.next_attempt END,
        last_error=CASE WHEN calendar_analysis_tasks.version!=excluded.version OR excluded.state='done' THEN '' ELSE calendar_analysis_tasks.last_error END,
        version=excluded.version''',
        (account_id,booking.provider_id,version,None if cached else payload,booking.start.isoformat(),'done' if cached else 'pending',now))
    conn.commit()


def snapshot_complete(conn, account_id, since, until, started):
    # Only a complete provider snapshot may retire absent work. Failed Graph
    # fetches must not erase queued events or the original calendar sources.
    conn.execute("""UPDATE calendar_analysis_tasks SET state='cancelled',booking=NULL
        WHERE account_id=? AND last_seen<? AND julianday(start_at)>=julianday(?)
        AND julianday(start_at)<julianday(?)""",(account_id,started,since,until))


def decode(task):
    value = json.loads(task['booking'])
    for name in ('start','end','updated_at'):
        value[name] = datetime.fromisoformat(value[name]) if value[name] else None
    return CalendarBooking(**value)


def progress(conn):
    now = time.time()
    counts = dict(conn.execute("""SELECT t.state,COUNT(*) FROM calendar_analysis_tasks t JOIN accounts a ON a.id=t.account_id
        WHERE a.enabled=1 AND a.provider='outlook' AND t.state!='cancelled' GROUP BY t.state"""))
    state = conn.execute('SELECT * FROM calendar_analysis_worker WHERE id=1').fetchone()
    pending = sum(counts.get(key,0) for key in ('pending','retry','processing'))
    review = counts.get('needs_review',0)
    retry = conn.execute("""SELECT MIN(CASE WHEN t.state='processing' THEN t.lease_until ELSE t.next_attempt END)
        FROM calendar_analysis_tasks t JOIN accounts a ON a.id=t.account_id
        WHERE a.enabled=1 AND a.provider='outlook' AND t.state IN ('pending','retry','processing')""").fetchone()[0]
    pause = state['next_run'] if state else 0
    failed = conn.execute("""SELECT t.last_error FROM calendar_analysis_tasks t JOIN accounts a ON a.id=t.account_id
        WHERE a.enabled=1 AND a.provider='outlook' AND t.state IN ('retry','needs_review') AND t.last_error!='' ORDER BY t.next_attempt LIMIT 1""").fetchone()
    return dict(done=counts.get('done',0),pending=pending,needs_review=review,total=counts.get('done',0)+pending+review,
        retrying=counts.get('retry',0),running=counts.get('processing',0),
        retry_in=max(0,int(max(pause,retry or 0)-now)) if pending else 0,
        last_error=((state['last_error'] if state else '') or (failed[0] if failed else '')) if pending or review else '')


def due(conn):
    p = progress(conn)
    return bool(p['pending'] and p['retry_in']==0)


def claim(conn, *, lease_seconds=600):
    now = time.time()
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('INSERT OR IGNORE INTO calendar_analysis_worker(id) VALUES(1)')
    state = conn.execute('SELECT * FROM calendar_analysis_worker WHERE id=1').fetchone()
    if state['next_run'] > now:
        conn.commit();return None
    task = conn.execute('''SELECT t.* FROM calendar_analysis_tasks t JOIN accounts a ON a.id=t.account_id
        WHERE a.enabled=1 AND a.provider='outlook' AND t.booking IS NOT NULL
        AND ((t.state IN ('pending','retry') AND t.next_attempt<=?) OR (t.state='processing' AND t.lease_until<=?))
        ORDER BY CASE WHEN t.account_id>? THEN 0 ELSE 1 END,t.account_id,
        CASE WHEN t.state='retry' THEN 1 ELSE 0 END,
        CASE WHEN julianday(t.start_at)>=julianday('now') THEN 0
             WHEN julianday(t.start_at)>=julianday('now','-30 days') THEN 1 ELSE 2 END,
        CASE WHEN julianday(t.start_at)>=julianday('now') THEN julianday(t.start_at) END ASC,
        julianday(t.start_at) DESC,t.id LIMIT 1''',(now,now,state['last_account'])).fetchone()
    if not task:
        conn.commit();return None
    conn.execute("UPDATE calendar_analysis_tasks SET state='processing',lease_until=?,attempts=attempts+1 WHERE id=?",(now+lease_seconds,task['id']))
    conn.execute('UPDATE calendar_analysis_worker SET last_account=? WHERE id=1',(task['account_id'],))
    conn.commit()
    return dict(task,attempts=task['attempts']+1)


def current(conn, task):
    return bool(conn.execute("SELECT 1 FROM calendar_analysis_tasks WHERE id=? AND version=? AND attempts=? AND state='processing'",
        (task['id'],task['version'],task['attempts'])).fetchone())


def finish(conn, task):
    changed = conn.execute("UPDATE calendar_analysis_tasks SET state='done',booking=NULL,last_error='',next_attempt=0,lease_until=0 WHERE id=? AND version=? AND attempts=? AND state='processing'",
        (task['id'],task['version'],task['attempts'])).rowcount
    if changed:
        conn.execute("UPDATE calendar_analysis_worker SET last_error='',next_run=0 WHERE id=1")


def retry(conn, task, reason, *, service_unavailable=False, invalid_response=False):
    wait = min(1800,30 * 2**min(task['attempts']-1,6))
    state = 'needs_review' if invalid_response and task['attempts']>=3 else 'retry'
    changed = conn.execute("""UPDATE calendar_analysis_tasks SET state=?,last_error=?,next_attempt=?,lease_until=0
        WHERE id=? AND version=? AND attempts=? AND state='processing'""",
        (state,reason,0 if state=='needs_review' else time.time()+wait,task['id'],task['version'],task['attempts'])).rowcount
    if changed:
        conn.execute("UPDATE calendar_analysis_worker SET last_error=?,next_run=? WHERE id=1",
            (reason,time.time()+60 if service_unavailable else 0))


def retry_now(conn):
    conn.execute("UPDATE calendar_analysis_tasks SET next_attempt=0,state='pending',attempts=0,last_error='' WHERE state IN ('retry','needs_review')")
    conn.execute("UPDATE calendar_analysis_worker SET next_run=0,last_error='' WHERE id=1")
