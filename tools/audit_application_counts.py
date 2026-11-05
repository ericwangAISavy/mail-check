"""Read-only incident report. Does not run migrations, verification, or repairs."""
import argparse
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from zoneinfo import ZoneInfo


def audit(database, week):
    start = date.fromisoformat(week)
    start -= timedelta(days=start.weekday())
    end = start + timedelta(days=6)
    zone = ZoneInfo('America/Chicago')
    with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        assignments = {}
        for row in conn.execute('SELECT bidder_id,account_id,start_date,end_date FROM bidder_assignments'):
            assignments.setdefault((row['bidder_id'],row['account_id']),[]).append((row['start_date'],row['end_date']))
        def eligible(who, account, day):
            return day is not None and any(a <= day and (b is None or day <= b)
                for a,b in assignments.get((who,account),[]))
        rows = conn.execute('''SELECT r.id AS row_id,b.bidder_id,t.account_id,r.work_date,
            p.name AS bidder,p.removed_at,e.confirmed_at,e.source,
            (SELECT c.value FROM native_cells c JOIN native_columns col ON col.id=c.column_id
             WHERE c.row_id=r.id AND col.kind='check') AS checked,
            (SELECT c.value FROM native_cells c JOIN native_columns col ON col.id=c.column_id
             WHERE c.row_id=r.id AND col.kind='link') AS link
            FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id
            JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id
            LEFT JOIN sourcing_check_activity e ON e.row_id=r.id''').fetchall()
        issues = []
        totals = {}
        for row in rows:
            day = row['work_date']
            if row['confirmed_at']:
                try:
                    stamp = datetime.fromisoformat(row['confirmed_at'].replace('Z','+00:00'))
                    day = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(zone).date().isoformat()
                except ValueError:
                    pass
            source_in_week = row['work_date'] and start.isoformat() <= row['work_date'] <= end.isoformat()
            counted_in_week = day and start.isoformat() <= day <= end.isoformat()
            if not (source_in_week or counted_in_week):
                continue
            reasons = []
            checked = row['checked'] == 'true' and bool((row['link'] or '').strip())
            assigned = eligible(row['bidder_id'],row['account_id'],day)
            if checked and counted_in_week and assigned and row['removed_at'] is None:
                daily = totals.setdefault(str(row['bidder_id']),{'bidder':row['bidder'],'daily':[0]*7})
                daily['daily'][(date.fromisoformat(day)-start).days] += 1
            if checked and day != row['work_date']:
                reasons.append('confirmation_day_differs_from_source_day')
            if checked and not assigned:
                reasons.append('excluded_no_assignment_on_counted_day')
            if checked and row['removed_at'] is not None:
                reasons.append('excluded_removed_bidder')
            if row['source'] == 'rebuild-cleared' and not checked:
                reasons.append('previous_automatic_check_cleared_by_rebuild')
            if reasons:
                issues.append({key:row[key] for key in ('row_id','bidder_id','bidder','account_id','work_date','confirmed_at','source')} |
                    {'counted_day':day,'checked':checked,'assigned_on_source_day':eligible(row['bidder_id'],row['account_id'],row['work_date']),'reasons':reasons})
        orphans = [dict(r) for r in conn.execute('''SELECT e.row_id,e.bidder_id,e.account_id,e.work_date,e.source,e.confirmed_at
            FROM sourcing_check_activity e LEFT JOIN native_rows r ON r.id=e.row_id
            WHERE r.id IS NULL AND e.work_date>=? AND e.work_date<=?''',(start.isoformat(),end.isoformat()))]
        samples = [dict(r) for r in conn.execute('''SELECT r.recorded_at,r.source,s.bidder_id,s.checked_total
            FROM sourcing_activity_runs r JOIN sourcing_activity_samples s ON s.run_id=r.id
            ORDER BY r.id DESC,s.bidder_id LIMIT 200''')]
        return {'week_start':start.isoformat(),'timezone':str(zone),'current_eligible_checked_daily':totals,
            'diagnostics':issues,'deleted_row_activity_in_source_week':orphans,
            'recent_samples_all_dates_not_weekly':samples,
            'limitations':'Current records cannot prove every historical total. No records changed. No message bodies, links, credentials, or receipt identifiers exported.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--week',required=True)
    parser.add_argument('--output',type=Path)
    args = parser.parse_args()
    if args.output and args.output.resolve() in {Path(str(Path(args.database).resolve())+suffix) for suffix in ('','-wal','-shm')}:
        parser.error('Output must not overwrite the database or its journal files')
    result = json.dumps(audit(args.database,args.week),indent=2)
    if args.output:
        args.output.write_text(result+'\n')
    else:
        print(result)


if __name__ == '__main__':
    main()
