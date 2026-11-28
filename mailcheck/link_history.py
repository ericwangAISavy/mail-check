"""Previewed, account-scoped removal of retained sourcing links."""
import json
from collections import Counter

from . import native_sourcing as sheets
from .sourcing_filters import link_key
from .sourcing_structure import insert_rows


def require_account(conn, account_id):
    if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone():
        raise LookupError('Email account not found.')


def bidders(conn, account_id):
    require_account(conn, account_id)
    return {'bidders': [dict(row) for row in conn.execute('''
        SELECT p.id,p.name,p.removed_at IS NOT NULL AS deleted,COUNT(*) AS link_count,
               MIN(r.work_date) AS first_date,MAX(r.work_date) AS last_date
        FROM native_tabs t JOIN native_books b ON b.id=t.book_id
        JOIN bidders p ON p.id=b.bidder_id JOIN native_rows r ON r.tab_id=t.id
        JOIN native_columns c ON c.tab_id=t.id AND c.kind='link'
        JOIN native_cells v ON v.row_id=r.id AND v.column_id=c.id
        WHERE t.account_id=? AND trim(v.value)!=''
        GROUP BY p.id ORDER BY deleted DESC,p.name COLLATE NOCASE,p.id''', (account_id,))]}


def selection(conn, account_id, scope):
    require_account(conn, account_id)
    tab = conn.execute('''SELECT t.* FROM native_tabs t JOIN native_books b ON b.id=t.book_id
        WHERE t.account_id=? AND b.bidder_id=?''', (account_id, scope['bidder_id'])).fetchone()
    if tab is None:
        raise LookupError('Bidder link history not found for this account.')
    rows = conn.execute('''SELECT r.id,r.work_date,v.value,
        COALESCE((SELECT cv.value FROM native_cells cv JOIN native_columns cc ON cc.id=cv.column_id
          WHERE cv.row_id=r.id AND cc.kind='check'),'false') AS checked
        FROM native_rows r JOIN native_columns c ON c.tab_id=r.tab_id AND c.kind='link'
        JOIN native_cells v ON v.row_id=r.id AND v.column_id=c.id
        WHERE r.tab_id=? AND trim(v.value)!=''
          AND (? IS NULL OR r.work_date>=?) AND (? IS NULL OR r.work_date<=?)
        ORDER BY r.id''', (tab['id'], scope.get('start'), scope.get('start'),
                          scope.get('end'), scope.get('end'))).fetchall()
    token = sheets.fingerprint({'account_id': account_id, 'scope': scope,
        'tab_id': tab['id'], 'revision': tab['revision'], 'rows': [tuple(row) for row in rows]})
    return tab, rows, token


def preview(conn, account_id, scope):
    _, rows, token = selection(conn, account_id, scope)
    return {'link_count': len(rows), 'checked_count': sum(row['checked'] == 'true' for row in rows),
            'preview_token': token}


def clear_imported_links(conn, tab, rows):
    if tab['legacy_tab_id'] is None:
        return
    legacy = conn.execute('SELECT snapshot,header_row,link_col FROM sourcing_tabs WHERE id=?',
                          (tab['legacy_tab_id'],)).fetchone()
    if not legacy or not legacy['snapshot']:
        return
    try:
        snapshot = json.loads(legacy['snapshot'])
        imported = snapshot['rows']
        if not isinstance(imported, list):
            raise ValueError()
    except (ValueError, TypeError, KeyError):
        raise ValueError('The retained import copy is unreadable. Link cleanup was cancelled.') from None
    remaining = Counter(link_key(row['value']) for row in rows)
    kept = []
    for index, row in enumerate(imported):
        cell = row[legacy['link_col']] if isinstance(row, list) and len(row) > legacy['link_col'] else None
        value = ''
        if isinstance(cell, dict):
            value = cell.get('link') or (cell.get('display') if cell.get('formula')
                                        else cell.get('value', cell.get('display', '')))
        key = link_key(str(value or ''))
        if index >= legacy['header_row'] and key and remaining[key]:
            remaining[key] -= 1
        else:
            kept.append(row)
    if len(kept) != len(imported):
        snapshot['rows'] = kept
        conn.execute('UPDATE sourcing_tabs SET snapshot=? WHERE id=?',
                     (json.dumps(snapshot), tab['legacy_tab_id']))


def clear(conn, account_id, scope, token, operation):
    payload = {'action': 'clear-link-history', 'account_id': account_id, 'scope': scope, 'preview_token': token}
    with sheets.atomic(conn):
        tab, rows, current = selection(conn, account_id, scope)
        if sheets.check_operation(conn, tab['id'], operation, payload):
            return json.loads(conn.execute('SELECT result FROM native_operations WHERE id=?', (operation,)).fetchone()[0])
        if token != current:
            raise FileExistsError('Link history changed. Review a fresh preview before deleting.')
        if not rows:
            raise ValueError('No links match this selection.')
        conn.executemany('DELETE FROM native_rows WHERE id=? AND tab_id=?',
                         [(row['id'], tab['id']) for row in rows])
        if not conn.execute('SELECT 1 FROM native_rows WHERE tab_id=?', (tab['id'],)).fetchone():
            insert_rows(conn, tab['id'], 1)
        clear_imported_links(conn, tab, rows)
        sheets.record_operation(conn, tab['id'], operation, payload, structural=True)
        result = {'deleted': len(rows), 'checked': sum(row['checked'] == 'true' for row in rows)}
        conn.execute('UPDATE native_operations SET result=? WHERE id=?', (json.dumps(result), operation))
    return result
