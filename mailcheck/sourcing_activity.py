"""Observed check activity, distinct from sourcing dates and inferred work hours."""
from datetime import datetime, timedelta, timezone
from .payments import ZONE, monday, today

SCHEMA = """
CREATE TABLE IF NOT EXISTS sourcing_activity_meta (id INTEGER PRIMARY KEY CHECK(id=1),started_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sourcing_check_activity (
 row_id TEXT PRIMARY KEY,bidder_id INTEGER NOT NULL,account_id INTEGER,work_date TEXT,
 detected_at TEXT,source TEXT NOT NULL,confirmed_at TEXT,message_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_check_activity_time ON sourcing_check_activity(detected_at,bidder_id);
CREATE TABLE IF NOT EXISTS sourcing_activity_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,recorded_at TEXT NOT NULL,source TEXT NOT NULL,through_event INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sourcing_activity_samples (
 run_id INTEGER NOT NULL REFERENCES sourcing_activity_runs(id) ON DELETE CASCADE,
 bidder_id INTEGER NOT NULL,new_checks INTEGER NOT NULL,checked_total INTEGER NOT NULL,
 PRIMARY KEY(run_id,bidder_id)
);
"""
_CHECKED_ROWS = """SELECT r.id AS row_id,b.bidder_id,t.account_id,r.work_date,
 EXISTS(SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=b.bidder_id AND a.account_id=t.account_id
 AND a.start_date<=r.work_date AND (a.end_date IS NULL OR a.end_date>=r.work_date)) AS eligible
 FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
 JOIN bidders p ON p.id=b.bidder_id
 JOIN native_columns col ON col.tab_id=t.id AND col.kind='check'
 JOIN native_cells c ON c.row_id=r.id AND c.column_id=col.id AND c.value='true'
 JOIN native_columns link ON link.tab_id=t.id AND link.kind='link'
 JOIN native_cells l ON l.row_id=r.id AND l.column_id=link.id AND trim(l.value)!=''
 WHERE p.removed_at IS NULL"""

def now():
    return datetime.now(timezone.utc)


def initialize(conn):
    if conn.execute("SELECT 1 FROM sourcing_activity_meta WHERE id=1").fetchone():
        return
    conn.execute("INSERT INTO sourcing_activity_meta VALUES(1,?)", (now().isoformat(),))
    # Existing checks have no reliable detection timestamp. Preserve their baseline.
    for row in conn.execute(_CHECKED_ROWS).fetchall():
        conn.execute("INSERT OR IGNORE INTO sourcing_check_activity(row_id,bidder_id,account_id,work_date,detected_at,source) VALUES(?,?,?,?,NULL,'baseline')",
                     (row['row_id'],row['bidder_id'],row['account_id'],row['work_date']))


def confirm(conn, row_id, received, message_id):
    row = conn.execute("SELECT r.work_date,t.account_id,b.bidder_id FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id WHERE r.id=?", (row_id,)).fetchone()
    conn.execute("""INSERT INTO sourcing_check_activity(row_id,bidder_id,account_id,work_date,detected_at,source,confirmed_at,message_id)
        VALUES(?,?,?,?,?,'confirmation',?,?) ON CONFLICT(row_id) DO UPDATE SET
        confirmed_at=excluded.confirmed_at,message_id=excluded.message_id,account_id=excluded.account_id,
        bidder_id=excluded.bidder_id,work_date=excluded.work_date,source='confirmation'""",
        (row_id,row['bidder_id'],row['account_id'],row['work_date'],now().isoformat(),received.isoformat(),message_id))


def record(conn, source, *, sample=False):
    stamp = now().isoformat()
    added = {}
    for row in conn.execute(_CHECKED_ROWS + " AND t.archived=0 AND NOT EXISTS(SELECT 1 FROM sourcing_check_activity e WHERE e.row_id=r.id)").fetchall():
        conn.execute("INSERT INTO sourcing_check_activity(row_id,bidder_id,account_id,work_date,detected_at,source) VALUES(?,?,?,?,?,?)",
                     (row['row_id'],row['bidder_id'],row['account_id'],row['work_date'],stamp,source))
        if row['eligible']:
            added[row['bidder_id']] = added.get(row['bidder_id'],0) + 1
    if sample:
        from .sourcing_verification import checked_counts
        totals = {}
        for (bidder, _day), count in checked_counts(conn, '0001-01-01', '9999-12-31').items():
            totals[bidder] = totals.get(bidder,0) + count
        previous = conn.execute("SELECT through_event FROM sourcing_activity_runs ORDER BY id DESC LIMIT 1").fetchone()
        cursor = previous['through_event'] if previous else 0
        added = {r['bidder_id']: r['n'] for r in conn.execute("""SELECT e.bidder_id,COUNT(*) AS n
            FROM sourcing_check_activity e WHERE e.rowid>? AND e.detected_at IS NOT NULL
            AND EXISTS(SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=e.bidder_id AND a.account_id=e.account_id
            AND a.start_date<=e.work_date AND (a.end_date IS NULL OR a.end_date>=e.work_date)) GROUP BY e.bidder_id""",(cursor,))}
        through = conn.execute("SELECT COALESCE(MAX(rowid),0) FROM sourcing_check_activity").fetchone()[0]
        run = conn.execute("INSERT INTO sourcing_activity_runs(recorded_at,source,through_event) VALUES(?,?,?)",(stamp,source,through)).lastrowid
        conn.executemany("INSERT INTO sourcing_activity_samples VALUES(?,?,?,?)", [
            (run,row['id'],added.get(row['id'],0),totals.get(row['id'],0))
            for row in conn.execute("SELECT id FROM bidders WHERE removed_at IS NULL")])


def report(conn, week=None, *, bidder_id=None, day=None):
    activity_day = day
    start = monday(week or today())
    end = start + timedelta(days=7)
    lower = datetime.combine(start,datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(end,datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    dates = [(start+timedelta(days=i)).isoformat() for i in range(7)]
    bidders = {r['id']: {'id':r['id'],'name':r['name'],'hourly':[0]*24,'daily':[0]*7,
                        'heatmap':[[0]*24 for _ in range(7)],'new_checks':0,'last_detected':None,
                        'active_half_hours':0,'latest_check':None,'previous_check':None}
               for r in conn.execute("SELECT id,name FROM bidders WHERE removed_at IS NULL AND (? IS NULL OR id=?) ORDER BY name",(bidder_id,bidder_id))}
    buckets = {who:set() for who in bidders}
    from .sourcing_verification import confirmation_events
    events = confirmation_events(conn,lower,upper,bidder_id)
    for row in events:
        if row['bidder_id'] not in bidders: continue
        stamp = datetime.fromisoformat(row['activity_at']).astimezone(ZONE)
        day = dates.index(stamp.date().isoformat())
        bidder = bidders[row['bidder_id']]
        bidder['hourly'][stamp.hour] += 1
        bidder['daily'][day] += 1
        bidder['heatmap'][day][stamp.hour] += 1
        bidder['new_checks'] += 1
        bidder['last_detected'] = row['activity_at']
        buckets[row['bidder_id']].add((stamp.date().isoformat(),stamp.hour,stamp.minute//30,stamp.utcoffset()))
    timeline = {}
    for row in conn.execute("""SELECT r.id,r.recorded_at,r.source,s.bidder_id,s.new_checks,s.checked_total
        FROM sourcing_activity_runs r JOIN sourcing_activity_samples s ON s.run_id=r.id
        WHERE r.recorded_at>=? AND r.recorded_at<? AND (? IS NULL OR s.bidder_id=?)
        ORDER BY r.recorded_at,r.id""",(lower,upper,bidder_id,bidder_id)):
        if row['bidder_id'] not in bidders: continue
        point = timeline.setdefault(row['id'], {'at':row['recorded_at'],'source':row['source'],'counts':{}})
        point['counts'][str(row['bidder_id'])] = row['new_checks']
        bidder = bidders[row['bidder_id']]
        bidder['previous_check'] = bidder['latest_check']
        bidder['latest_check'] = {'at':row['recorded_at'],'new_checks':row['new_checks'],'checked_total':row['checked_total']}
    for who,bidder in bidders.items(): bidder['active_half_hours'] = len(buckets[who])
    def empty_account(row):
        return {'id':row['id'],'name':row['name'],'hourly':[0]*24,'daily':[0]*7,
                'heatmap':[[0]*24 for _ in range(7)],'new_checks':0,'last_detected':None,
                'active_half_hours':0,'latest_check':None,'previous_check':None}
    accounts = {r['id']:empty_account(r) for r in conn.execute("""SELECT a.account_id AS id,
        COALESCE(MAX(NULLIF(ac.email,'')),MIN(a.account_label)) AS name FROM bidder_assignments a
        JOIN bidders p ON p.id=a.bidder_id LEFT JOIN accounts ac ON ac.id=a.account_id
        WHERE p.removed_at IS NULL AND (? IS NULL OR a.bidder_id=?) GROUP BY a.account_id ORDER BY name""",(bidder_id,bidder_id))}
    account_buckets = {who:set() for who in accounts}
    for row in events:
        if row['bidder_id'] not in bidders or row['account_id'] not in accounts: continue
        stamp = datetime.fromisoformat(row['activity_at']).astimezone(ZONE)
        day = dates.index(stamp.date().isoformat())
        account = accounts[row['account_id']]
        account['hourly'][stamp.hour] += 1
        account['daily'][day] += 1
        account['heatmap'][day][stamp.hour] += 1
        account['new_checks'] += 1
        account['last_detected'] = row['activity_at']
        account_buckets[row['account_id']].add((stamp.date().isoformat(),stamp.hour,stamp.minute//30,stamp.utcoffset()))
    # Run cursors already persist the exact event range observed at each check.
    # Reconstruct account series from those ranges, including quiet checks.
    runs = conn.execute("""SELECT r.*,COALESCE((SELECT through_event FROM sourcing_activity_runs prev
        WHERE prev.id<r.id ORDER BY prev.id DESC LIMIT 1),0) AS previous_event
        FROM sourcing_activity_runs r WHERE r.recorded_at>=? AND r.recorded_at<?
        AND (? IS NULL OR EXISTS(SELECT 1 FROM sourcing_activity_samples s WHERE s.run_id=r.id AND s.bidder_id=?))
        ORDER BY r.id""",(lower,upper,bidder_id,bidder_id)).fetchall()
    run_events = []
    if runs:
        run_events = conn.execute("""SELECT e.rowid AS event_id,e.account_id,e.bidder_id FROM sourcing_check_activity e
            JOIN bidders p ON p.id=e.bidder_id WHERE e.rowid>? AND e.rowid<=? AND e.detected_at IS NOT NULL
            AND p.removed_at IS NULL AND (? IS NULL OR e.bidder_id=?) AND EXISTS(SELECT 1 FROM bidder_assignments a
            WHERE a.bidder_id=e.bidder_id AND a.account_id=e.account_id AND a.start_date<=e.work_date
            AND (a.end_date IS NULL OR a.end_date>=e.work_date)) ORDER BY e.rowid""",
            (runs[0]['previous_event'],runs[-1]['through_event'],bidder_id,bidder_id)).fetchall()
    account_timeline = []
    event_index = 0
    for run in runs:
        counts = {str(who):0 for who in accounts}
        while event_index<len(run_events) and run_events[event_index]['event_id']<=run['through_event']:
            event = run_events[event_index]
            if str(event['account_id']) in counts:
                counts[str(event['account_id'])] += 1
            event_index += 1
        account_timeline.append({'at':run['recorded_at'],'source':run['source'],'counts':counts})
        for who,account in accounts.items():
            account['previous_check'] = account['latest_check']
            account['latest_check'] = {'at':run['recorded_at'],'new_checks':counts[str(who)],'checked_total':None}
    for who,account in accounts.items(): account['active_half_hours'] = len(account_buckets[who])
    # Hourly confirmation series retains quiet periods without using check-run times.
    confirmation_points, account_confirmation_points = {}, {}
    instant = datetime.fromisoformat(lower)
    until = datetime.fromisoformat(upper)
    while instant < until:
        key = instant.isoformat()
        confirmation_points[key] = {'at':key,'source':'confirmation','counts':{str(who):0 for who in bidders}}
        account_confirmation_points[key] = {'at':key,'source':'confirmation','counts':{str(who):0 for who in accounts}}
        instant += timedelta(hours=1)
    for event in events:
        key = datetime.fromisoformat(event['activity_at']).astimezone(timezone.utc).replace(minute=0,second=0,microsecond=0).isoformat()
        if event['bidder_id'] in bidders:
            confirmation_points[key]['counts'][str(event['bidder_id'])] += 1
        if event['bidder_id'] in bidders and event['account_id'] in accounts:
            account_confirmation_points[key]['counts'][str(event['account_id'])] += 1
    meta = conn.execute("SELECT started_at FROM sourcing_activity_meta WHERE id=1").fetchone()
    return {'workday':workday_report(conn,activity_day,bidders,accounts,bidder_id), 'week_start':dates[0],'dates':dates,'timezone':ZONE.key,'tracking_since':meta['started_at'] if meta else None,
            'confirmation_timeline':list(confirmation_points.values()),'account_confirmation_timeline':list(account_confirmation_points.values()),
            'accounts':list(accounts.values()),'account_timeline':account_timeline[-240:],
            'bidders':list(bidders.values()),'check_count':len(timeline),'timeline':list(timeline.values())[-240:]}


def workday_report(conn, day, bidders, accounts, bidder_id):
    local = now().astimezone(ZONE)
    day = day or (local - timedelta(hours=6)).date()
    lower = datetime.combine(day,datetime.min.time(),ZONE).replace(hour=6).astimezone(timezone.utc)
    upper = datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE).replace(hour=6).astimezone(timezone.utc)
    def point(stamp, ids, source):
        return {'at':stamp,'source':source,'counts':{str(who):0 for who in ids}}
    confirmations, account_confirmations = {}, {}
    instant = lower
    while instant < upper:
        key = instant.isoformat()
        confirmations[key] = point(key,bidders,'confirmation')
        account_confirmations[key] = point(key,accounts,'confirmation')
        instant += timedelta(minutes=15)
    eligible = """EXISTS(SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=e.bidder_id
        AND a.account_id=e.account_id AND a.start_date<=e.work_date
        AND (a.end_date IS NULL OR a.end_date>=e.work_date))"""
    from .sourcing_verification import confirmation_events
    for event in confirmation_events(conn,lower.isoformat(),upper.isoformat(),bidder_id):
        stamp = datetime.fromisoformat(event['confirmed_at']).astimezone(timezone.utc)
        key = stamp.replace(minute=stamp.minute//15*15,second=0,microsecond=0).isoformat()
        if event['bidder_id'] in bidders:
            confirmations[key]['counts'][str(event['bidder_id'])] += 1
            if event['account_id'] in accounts:
                account_confirmations[key]['counts'][str(event['account_id'])] += 1
    runs = conn.execute("""SELECT r.*,COALESCE((SELECT through_event FROM sourcing_activity_runs prev
        WHERE prev.id<r.id ORDER BY prev.id DESC LIMIT 1),0) AS previous_event
        FROM sourcing_activity_runs r WHERE r.recorded_at>=? AND r.recorded_at<?
        AND (? IS NULL OR EXISTS(SELECT 1 FROM sourcing_activity_samples s WHERE s.run_id=r.id AND s.bidder_id=?))
        ORDER BY r.id""",(lower.isoformat(),upper.isoformat(),bidder_id,bidder_id)).fetchall()
    run_points, account_runs = [], []
    events = []
    if runs:
        events = conn.execute(f"""SELECT e.rowid AS event_id,e.bidder_id,e.account_id FROM sourcing_check_activity e
            WHERE e.rowid>? AND e.rowid<=? AND e.detected_at IS NOT NULL
            AND (? IS NULL OR e.bidder_id=?) AND {eligible} ORDER BY e.rowid""",
            (runs[0]['previous_event'],runs[-1]['through_event'],bidder_id,bidder_id)).fetchall()
    index = 0
    for run in runs:
        bidder_point = point(run['recorded_at'],bidders,run['source'])
        account_point = point(run['recorded_at'],accounts,run['source'])
        for sample in conn.execute('SELECT bidder_id,new_checks FROM sourcing_activity_samples WHERE run_id=?',(run['id'],)):
            if sample['bidder_id'] in bidders:
                bidder_point['counts'][str(sample['bidder_id'])] = sample['new_checks']
        while index < len(events) and events[index]['event_id']<=run['through_event']:
            event = events[index]
            if event['bidder_id'] in bidders and event['account_id'] in accounts:
                account_point['counts'][str(event['account_id'])] += 1
            index += 1
        run_points.append(bidder_point)
        account_runs.append(account_point)
    return {'date':day.isoformat(),'start':lower.isoformat(),'end':upper.isoformat(),
            'confirmations':list(confirmations.values()),'account_confirmations':list(account_confirmations.values()),
            'runs':run_points,'account_runs':account_runs}
