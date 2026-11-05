"""Restore only audit-listed rebuild-cleared checks. Preview is the default."""
import argparse
from collections import Counter
from contextlib import closing, nullcontext
from datetime import date
import json
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mailcheck.maintenance import MaintenanceError, MaintenanceLock, lock_path


def recover(database, audit_file, *, apply=False, use_source_dates=False, config=None):
    if apply and (not use_source_dates or config is None):
        raise ValueError('Apply requires --use-source-dates and --config pointing to the installation config file')
    if apply and not Path(config).is_file():
        raise ValueError('--config must point to the existing installation config file')
    document = json.loads(Path(audit_file).read_text())
    start = date.fromisoformat(document['week_start'])
    candidates = [r for r in document['diagnostics'] if
        'previous_automatic_check_cleared_by_rebuild' in r.get('reasons', [])]
    if not candidates or len({r['row_id'] for r in candidates}) != len(candidates):
        raise ValueError('Audit must contain a nonempty, unique set of rebuild-cleared row IDs')
    mode = 'rw' if apply else 'ro'
    maintenance = MaintenanceLock(lock_path(Path(config)), exclusive=True) if apply else nullcontext()
    with maintenance, closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode='+mode, uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if not apply:
            conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        pending, skipped, conflicts = [], [], []
        for expected in candidates:
            row = conn.execute('''SELECT r.id,r.work_date,r.tab_id,b.bidder_id,t.account_id,p.name,p.removed_at,
                e.source,e.confirmed_at,e.message_id,cc.id AS column_id,c.value AS checked,
                (SELECT l.value FROM native_cells l JOIN native_columns lc ON lc.id=l.column_id
                 WHERE l.row_id=r.id AND lc.kind='link') AS link,
                EXISTS(SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=b.bidder_id
                  AND a.account_id=t.account_id AND a.start_date<=r.work_date
                  AND (a.end_date IS NULL OR a.end_date>=r.work_date)) AS assigned
                FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id
                JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id
                JOIN sourcing_check_activity e ON e.row_id=r.id
                JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='check'
                LEFT JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id WHERE r.id=?''',(expected['row_id'],)).fetchone()
            valid = row is not None and all(row[k] == expected[k] for k in ('bidder_id','account_id','work_date'))
            if valid:
                try:
                    valid = 0 <= (date.fromisoformat(row['work_date'])-start).days < 7
                except (TypeError, ValueError):
                    valid = False
                valid = valid and row['removed_at'] is None and row['assigned'] and bool((row['link'] or '').strip())
            if not valid:
                conflicts.append(expected['row_id'])
            elif row['checked'] == 'true':
                skipped.append(row['id'])
            elif row['source'] != 'rebuild-cleared' or row['confirmed_at'] is not None or row['message_id'] is not None or row['checked'] not in ('false','',None):
                conflicts.append(row['id'])
            else:
                pending.append(dict(row))
        result = {'mode':'apply' if apply else 'preview','week_start':start.isoformat(),
            'audit_candidates':len(candidates),'restore_count':len(pending),'already_checked':len(skipped),
            'conflicts':conflicts,'credit_date_policy':'saved sourcing date; original receipt dates are unavailable',
            'by_bidder':dict(Counter(r['name'] for r in pending)),
            'by_source_date':dict(sorted(Counter(r['work_date'] for r in pending).items())),
            'rows':[{'row_id':r['id'],'bidder':r['name'],'credit_date':r['work_date']} for r in pending]}
        if conflicts:
            raise ValueError('No changes made: audit/database conflicts for row IDs: '+', '.join(conflicts))
        if apply:
            try:
                for row in pending:
                    conn.execute('''INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,'true')
                        ON CONFLICT(row_id,column_id) DO UPDATE SET value='true',version=native_cells.version+1''',
                        (row['id'],row['column_id']))
                    conn.execute("UPDATE sourcing_check_activity SET source='recovered-rebuild' WHERE row_id=?",(row['id'],))
                for tab in {r['tab_id'] for r in pending}:
                    conn.execute('UPDATE native_tabs SET revision=revision+1,updated_at=? WHERE id=?',(time.time(),tab))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--audit',required=True)
    parser.add_argument('--config',help='Same installation config path used by the app, for its exclusive maintenance lock')
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--use-source-dates',action='store_true',help='Accept sourcing dates as credit dates, affecting daily deductions')
    args = parser.parse_args()
    try:
        print(json.dumps(recover(args.database,args.audit,apply=args.apply,use_source_dates=args.use_source_dates,config=args.config),indent=2))
    except (ValueError,KeyError,sqlite3.Error,OSError,MaintenanceError) as exc:
        parser.exit(1,str(exc)+'\n')


if __name__ == '__main__':
    main()
