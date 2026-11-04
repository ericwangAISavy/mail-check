"""Synthetic payment-report benchmark; never reads a real workspace database.

Run: python tools/benchmark_payments.py --baseline fd8734f --rows 12000
Baseline modules come from the supplied local Git revision. Only temporary data
is modified. Counts must agree; timings are observations, not production SLAs.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import tempfile
import time
import types
from unittest.mock import patch

from mailcheck import db, payments, sourcing_verification


def seed(conn, count):
    accounts = [db.add_account(conn, label=f'synthetic-{i}', email=f'synthetic-{i}@example.test') for i in range(2)]
    for bidder in range(1, 5):
        conn.execute("INSERT INTO bidders(id,name,created_at) VALUES(?,?,'2026-01-01')", (bidder,f'Synthetic bidder {bidder}'))
        conn.execute("INSERT INTO native_books(id,bidder_id,title) VALUES(?,?,'Synthetic')", (bidder,bidder))
        for offset, account in enumerate(accounts):
            tab = (bidder-1)*2+offset+1
            conn.execute("INSERT INTO native_tabs(id,book_id,account_id,account_label,title,updated_at) VALUES(?,?,?,'Synthetic','Synthetic',0)",(tab,bidder,account))
            conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date) VALUES(?,?,'Synthetic','2026-01-01')", (bidder,account))
            for position, kind in enumerate(('company','role','link','check')):
                conn.execute('INSERT INTO native_columns(id,tab_id,position,title,kind) VALUES(?,?,?,?,?)',(f'{tab}-{kind}',tab,position,kind,kind))
    messages, classes, receipts, rows, cells, events = [], [], [], [], [], []
    for index in range(count):
        tab = index % 8 + 1
        bidder = (tab-1)//2+1
        account = accounts[(tab-1)%2]
        day = date(2026,11,4)-timedelta(days=index%90)
        stamp = datetime.combine(day, datetime.min.time(), timezone.utc).replace(hour=16).isoformat()
        key, company = f'synthetic-{index}', f'Company{index}'
        messages.append((index+1,account,key,str(index),'INBOX','synthetic@example.test','Synthetic',company,stamp,'Synthetic text',stamp))
        classes.append((index+1,'application_ack',company,'Engineer','synthetic','2',stamp))
        receipts.append((account,key,stamp,'application_ack',company,'Engineer'))
        rows.append((key,tab,index,day.isoformat()))
        for kind,value in (('company',company),('role','Engineer'),('link',f'https://example.test/job/{index}'),('check','true')):
            cells.append((key,f'{tab}-{kind}',value))
        if index % 3:
            events.append((key,bidder,account,day.isoformat(),stamp,'confirmation',stamp,key))
    conn.executemany('INSERT INTO messages(id,account_id,message_id,uid,folder,from_addr,from_name,subject,date_utc,body_text,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)', messages)
    conn.executemany('INSERT INTO classifications(message_pk,category,company,role,model,prompt_version,created_at) VALUES(?,?,?,?,?,?,?)', classes)
    conn.executemany('INSERT INTO application_receipts(account_id,message_id,received_at,category,company,role) VALUES(?,?,?,?,?,?)', receipts)
    conn.executemany('INSERT INTO native_rows(id,tab_id,position,work_date) VALUES(?,?,?,?)',rows)
    conn.executemany('INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)', cells)
    conn.executemany('INSERT INTO sourcing_check_activity(row_id,bidder_id,account_id,work_date,detected_at,source,confirmed_at,message_id) VALUES(?,?,?,?,?,?,?,?)', events)
    conn.commit()


def historical_module(revision, filename):
    source = subprocess.run(['git','show',f'{revision}:mailcheck/{filename}.py'],check=True,capture_output=True,text=True).stdout
    module = types.ModuleType(f'mailcheck._benchmark_{filename}')
    module.__package__ = 'mailcheck'
    exec(compile(source, f'{revision}:{filename}', 'exec'), module.__dict__)
    return module


def measure(conn, module, completed, rounds):
    times, writes = [], []
    result = None
    with patch.object(sourcing_verification, 'completed_account_counts', completed):
        for _ in range(rounds):
            before = conn.total_changes
            started = time.perf_counter()
            result = module.report(conn, date(2026,11,2), admin=True)
            conn.commit()
            times.append(time.perf_counter()-started)
            writes.append(conn.total_changes-before)
    return {'median_seconds':round(statistics.median(times),6),'seconds':[round(t,6) for t in times], 'rows_written':writes}, result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline')
    parser.add_argument('--rows',type=int,default=12000)
    parser.add_argument('--rounds',type=int,default=5)
    args = parser.parse_args()
    if args.rows < 1 or args.rounds < 1:
        parser.error('--rows and --rounds must be positive')
    with tempfile.TemporaryDirectory(prefix='offerpath-payment-benchmark-') as tmp:
        with patch.dict(os.environ, {'OFFERPATH_MAINTENANCE_LOCK':str(Path(tmp)/'installation.lock')}):
            conn = db.connect(Path(tmp)/'synthetic.db')
            try:
                seed(conn,args.rows)
                records = {'synthetic_rows':args.rows,'days':90}
                baseline_result = None
                if args.baseline:
                    baseline = historical_module(args.baseline,'payments')
                    old_verification = historical_module(args.baseline,'sourcing_verification')
                    records['baseline'], baseline_result = measure(conn,baseline,old_verification.completed_account_counts,args.rounds)
                records['current'], result = measure(conn,payments,sourcing_verification.completed_account_counts,args.rounds)
                assert sum(result['checked_daily']) > 0
                if baseline_result:
                    assert result['checked_daily'] == baseline_result['checked_daily']
                    assert result['daily'] == baseline_result['daily']
                    assert [b['total'] for b in result['bidders']] == [b['total'] for b in baseline_result['bidders']]
                    records['speedup'] = round(records['baseline']['median_seconds']/records['current']['median_seconds'],2)
                assert records['current']['rows_written'] == [0]*args.rounds
                sourcing_verification.verify_all(conn,refresh_since=date(2026,11,2),refresh_until=date(2026,11,8),week_only=True,sample=False)
                conn.commit()
                refresh_times, refresh_writes = [], []
                for _ in range(args.rounds):
                    before = conn.total_changes
                    started = time.perf_counter()
                    sourcing_verification.verify_all(conn,refresh_since=date(2026,11,2),refresh_until=date(2026,11,8),week_only=True,sample=False)
                    conn.commit()
                    refresh_times.append(time.perf_counter()-started)
                    refresh_writes.append(conn.total_changes-before)
                assert refresh_writes == [0]*args.rounds
                records['unchanged_week_refresh'] = {'median_seconds':round(statistics.median(refresh_times),6),'rows_written':refresh_writes}
                print(json.dumps(records,indent=2))
            finally:
                conn.close()


if __name__ == '__main__':
    main()
