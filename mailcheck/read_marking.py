"""Durable Outlook read updates, dispatched after collection commits."""
import hashlib
import os
import tempfile
from pathlib import Path

from .sources.base import MessageReadError, ReadPermissionError, SourceError

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


def _marker_dir() -> Path:
    from .config import data_dir
    return data_dir() / 'outlook-read-permission'


def _permission_marker(account_id, mailbox) -> Path:
    """One file per account mailbox, so concurrent workers never rewrite shared state.

    The mailbox hash keeps a reused account ID from inheriting an old marker.
    """
    digest = hashlib.sha256(mailbox.casefold().encode()).hexdigest()[:16]
    return _marker_dir() / f'{int(account_id)}-{digest}'


def needs_permission(account_id, mailbox) -> bool:
    """True when Microsoft refused the last read update for lack of permission."""
    try:
        return _permission_marker(account_id, mailbox).exists()
    except OSError:
        return False


def _set_needs_permission(account, mailbox, refused):
    marker = _permission_marker(account.id, mailbox)
    try:
        if not refused:
            marker.unlink(missing_ok=True)
            return
        marker.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=marker.parent, prefix='.tmp-')
        os.close(descriptor)
        os.replace(temporary, marker)
    except OSError:
        pass  # status hint only; never fail collection over it


def drain(conn, account, source, check=lambda: None):
    errors = []
    if account.provider != 'outlook':
        return errors
    mailbox = account.email.casefold()
    rows = conn.execute('SELECT uid FROM outlook_read_tasks WHERE account_id=? AND mailbox=?',
                        (account.id, mailbox)).fetchall()
    name = account.label if hasattr(account, 'label') else account.id
    if not rows:
        _set_needs_permission(account, mailbox, False)
    granted = False
    for row in rows:
        check()
        try:
            source.mark_read(row[0])
        except ReadPermissionError as exc:
            _set_needs_permission(account, mailbox, True)
            errors.append(f'[{name}] Read marking pending: {exc}')
            break
        except MessageReadError as exc:
            if not exc.permanent:
                errors.append(f'[{name}] Read marking pending: {exc}')
                continue
            errors.append(f'[{name}] Read marking skipped: {exc}')
            # Fall through: drop an update Microsoft will never accept.
        except SourceError as exc:
            errors.append(f'[{name}] Read marking pending: {exc}')
            break
        else:
            if not granted:
                granted = True
                _set_needs_permission(account, mailbox, False)
        check()
        conn.execute('DELETE FROM outlook_read_tasks WHERE account_id=? AND mailbox=? AND uid=?',
                     (account.id, mailbox, row[0]))
        conn.commit()
    return errors
