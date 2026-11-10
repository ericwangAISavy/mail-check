"""Workspace-local bulk completion with durable, exact batch Undo membership."""
from contextlib import contextmanager
from uuid import uuid4

from . import db
from .taxonomy import CATEGORIES, is_queue_category


@contextmanager
def _write(conn):
    own = not conn.in_transaction
    if own: conn.execute('BEGIN IMMEDIATE')
    try:
        yield
        if own: conn.commit()
    except BaseException:
        if own: conn.rollback()
        raise


def clear(conn, operation=None):
    categories = [c.name for c in CATEGORIES if is_queue_category(c.name)]
    operation = str(operation or uuid4())
    with _write(conn):
        previous = conn.execute('SELECT message_count FROM queue_clear_operations WHERE operation=?', (operation,)).fetchone()
        if previous is not None:
            count = previous['message_count']
            return {'count':count, 'operation':operation if count else None, 'replayed':True}
        stamp = db._handled_now(conn)
        cursor = conn.execute('''INSERT OR REPLACE INTO queue_clear_members(message_pk,operation,handled_at)
            SELECT m.id,?,? FROM messages m JOIN accounts a ON a.id=m.account_id
            ''' + db.LATEST_CLASSIFICATION + ''' WHERE m.handled_at IS NULL AND c.category IN ('''
            + ','.join('?' for _ in categories) + ')', [operation, stamp, *categories])
        count = cursor.rowcount
        if count:
            conn.execute('''UPDATE messages SET handled_at=? WHERE id IN
                (SELECT message_pk FROM queue_clear_members WHERE operation=?)''', (stamp, operation))
        conn.execute('INSERT INTO queue_clear_operations(operation,message_count,created_at) VALUES(?,?,?)',
                     (operation,count,stamp))
    return {'count':count, 'operation':operation if count else None, 'replayed':False}


def restore(conn, operation):
    with _write(conn):
        cursor = conn.execute('''UPDATE messages SET handled_at=NULL WHERE id IN (
            SELECT b.message_pk FROM queue_clear_members b JOIN messages m
            ON m.id=b.message_pk AND m.handled_at=b.handled_at WHERE b.operation=?)''', (operation,))
        count = cursor.rowcount
        conn.execute('DELETE FROM queue_clear_members WHERE operation=?', (operation,))
    return count


def undo_last(conn):
    with _write(conn):
        row = db.last_handled(conn)
        if row is None: return None
        batch = conn.execute('''SELECT operation FROM queue_clear_members
            WHERE message_pk=? AND handled_at=?''', (row['pk'], row['handled_at'])).fetchone()
        if batch:
            count = restore(conn, batch['operation'])
        else:
            conn.execute('DELETE FROM queue_clear_members WHERE message_pk=?', (row['pk'],))
            conn.execute('UPDATE messages SET handled_at=NULL WHERE id=?', (row['pk'],))
            count = 1
    return {**dict(row), 'count':count, 'bulk':bool(batch)}
