"""Durable Outlook read updates, dispatched after collection commits."""
from .sources.base import MessageReadError, SourceError

SCHEMA = """
CREATE TABLE IF NOT EXISTS outlook_read_tasks (
 account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 mailbox TEXT NOT NULL,
 uid TEXT NOT NULL,
 PRIMARY KEY(account_id, mailbox, uid)
);
"""


def enqueue(conn, account, uid, *, is_read=None):
    if account.provider == 'outlook' and uid:
        if is_read is True:
            conn.execute('DELETE FROM outlook_read_tasks WHERE account_id=? AND mailbox=? AND uid=?',
                         (account.id, account.email.casefold(), uid))
            return
        conn.execute('INSERT OR IGNORE INTO outlook_read_tasks VALUES(?,?,?)',
                     (account.id, account.email.casefold(), uid))


def drain(conn, account, source, check=lambda: None):
    errors = []
    if account.provider != 'outlook':
        return errors
    mailbox = account.email.casefold()
    rows = conn.execute('SELECT uid FROM outlook_read_tasks WHERE account_id=? AND mailbox=?',
                        (account.id, mailbox)).fetchall()
    for row in rows:
        check()
        try:
            source.mark_read(row[0])
        except SourceError as exc:
            errors.append(f'[{account.label if hasattr(account, "label") else account.id}] Read marking pending: {exc}')
            if isinstance(exc, MessageReadError):
                continue
            break
        check()
        conn.execute('DELETE FROM outlook_read_tasks WHERE account_id=? AND mailbox=? AND uid=?',
                     (account.id, mailbox, row[0]))
        conn.commit()
    return errors
