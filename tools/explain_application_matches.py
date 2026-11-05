"""Read-only matching report: no verification writes, email bodies, or credentials."""
import argparse
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from mailcheck import payments
from mailcheck.sourcing_verification import _contains_name, _matching_plan, company_key


def explain(database, account, company):
    key = company_key(company)
    if not key:
        raise ValueError('Company must not be empty')
    with closing(sqlite3.connect(Path(database).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        rows = [dict(r) for r in conn.execute('''SELECT r.id,r.tab_id,r.work_date,t.account_id,
            ac.email AS account_email,b.bidder_id,p.name AS bidder,t.archived,
            co.value AS company,ro.value AS role,li.value AS link,ch.value AS checked,
            e.message_id AS saved_receipt,e.confirmed_at
            FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id
            LEFT JOIN accounts ac ON ac.id=t.account_id
            JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id
            JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
            JOIN native_columns rc ON rc.tab_id=t.id AND rc.kind='role'
            JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
            JOIN native_columns hc ON hc.tab_id=t.id AND hc.kind='check'
            LEFT JOIN native_cells co ON co.row_id=r.id AND co.column_id=cc.id
            LEFT JOIN native_cells ro ON ro.row_id=r.id AND ro.column_id=rc.id
            LEFT JOIN native_cells li ON li.row_id=r.id AND li.column_id=lc.id
            LEFT JOIN native_cells ch ON ch.row_id=r.id AND ch.column_id=hc.id
            LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
            WHERE p.removed_at IS NULL''')]
        ids = {r['id'] for r in conn.execute('SELECT id FROM accounts WHERE lower(email)=lower(?)',(account.strip(),))}
        receipts = [dict(r) for r in conn.execute('''SELECT account_id,message_id,received_at,company,role
            FROM application_receipts WHERE category='application_ack' ''')
            if r['account_id'] in ids and _contains_name(key,company_key(r['company']))]
        active_rows = [r for r in rows if r['account_id'] in ids and not r['archived']]
        plan = _matching_plan(conn,active_rows,receipts,early_since=payments.today()-timedelta(days=6))
        bindings = {}
        for row in rows:
            if row['checked']=='true' and row['saved_receipt']:
                bindings.setdefault((row['account_id'],row['saved_receipt']),[]).append(row['id'])
        related = [r for r in rows if _contains_name(key,company_key(r['company']))]
        for row in related:
            match = plan.get(row['id'])
            row['same_email_account'] = row['account_id'] in ids
            row['would_add_check'] = row['checked'] != 'true' and match is not None
            row['matched_receipt_date'] = match[0].isoformat() if match else None
            row['has_saved_receipt'] = bool(row.pop('saved_receipt'))
            row['has_job_link'] = bool((row.pop('link') or '').strip())
        # Receipt identifiers are excluded from shared reports.
        return {'company_query':company,'email_account':account,'matching_account_ids':sorted(ids),
            'rows':related,'receipts':[{**{k:r[k] for k in ('account_id','received_at','company','role')},
                'bound_checked_row_ids':bindings.get((r['account_id'],r['message_id']),[])} for r in receipts],
            'explanation':'A blank role prefers one unchecked job on the receipt Chicago date, otherwise one unchecked job in the existing date window. Compare account, work date, competing rows and existing receipt bindings. No data changed; this report uses currently saved receipt data.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True)
    parser.add_argument('--account',required=True)
    parser.add_argument('--company',required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(explain(args.database,args.account,args.company),indent=2))
    except (ValueError,sqlite3.Error,OSError) as exc:
        parser.exit(1,str(exc)+'\n')


if __name__=='__main__':
    main()
