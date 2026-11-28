"""Why automatic mail collection is failing, in words safe to show on an account.

Failures are stored in realtime_accounts.last_error with FAILURE_PREFIX, so a
successful collection (which rewrites last_error) clears them automatically.
Only fixed phrases are stored: provider error text can contain hostnames,
addresses or tokens and never reaches the page.
"""
from __future__ import annotations

import imaplib
import logging
import socket
import sqlite3
import ssl

FAILURE_PREFIX = 'Sync failing: '


def describe(exc: BaseException) -> str:
    from ..outlook_auth import OutlookAuthError, ReconnectRequired
    from ..sources.base import ReadPermissionError, SourceError
    if isinstance(exc, ReconnectRequired):
        return 'Microsoft sign-in expired. Reconnect this mailbox.'
    if isinstance(exc, OutlookAuthError):
        return 'Microsoft sign-in is unavailable. Reconnect this mailbox.'
    if isinstance(exc, ReadPermissionError):
        return 'The mailbox did not allow reading messages. Reconnect it.'
    if isinstance(exc, imaplib.IMAP4.error) and 'auth' in str(exc).lower():
        return 'The mail server rejected the sign-in. Reconnect this mailbox.'
    if isinstance(exc, PermissionError):
        return "OfferPath could not read this mailbox's saved sign-in. Reconnect it."
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return 'The mail server did not respond in time.'
    if isinstance(exc, (ssl.SSLError, ConnectionError, socket.gaierror)):
        return 'The mail server could not be reached.'
    if isinstance(exc, sqlite3.Error):
        return 'The workspace database was busy.'
    if isinstance(exc, (SourceError, imaplib.IMAP4.error)):
        return 'The mail server returned an error.'
    return f'Mail collection stopped unexpectedly ({type(exc).__name__}).'


def failure_reason(last_error: str | None) -> str | None:
    """The stored failure without its prefix, or None for no failure."""
    if last_error and last_error.startswith(FAILURE_PREFIX):
        return last_error[len(FAILURE_PREFIX):] or None
    return None


def _current_error(conn, account_id: int) -> str:
    row = conn.execute('SELECT last_error FROM realtime_accounts WHERE account_id=?', (account_id,)).fetchone()
    return (row[0] if row else '') or ''


def record_failure(conn, account_id: int, exc: BaseException, *, since: float | None = None) -> None:
    """Best effort: recording must never hide the original error.

    With ``since``, a failure after mail was already collected in this attempt
    (e.g. queueing classification) is not reported as a mail sync failure.
    """
    from . import storage
    try:
        conn.rollback()  # drop the failed attempt's partial writes first
        if since is not None:
            row = conn.execute('SELECT last_sync FROM realtime_accounts WHERE account_id=?', (account_id,)).fetchone()
            if row and row[0] is not None and row[0] >= since:
                return
        storage.set_status(conn, account_id, error=FAILURE_PREFIX + describe(exc))
        conn.commit()
    except Exception:
        logging.getLogger(__name__).debug('Could not record mail collection failure.', exc_info=True)


def set_other_status(conn, account_id: int, error: str = '') -> None:
    """Calendar/classification status writes must not hide a mail sync failure:
    only a mail collection attempt may set or clear that."""
    from . import storage
    if failure_reason(_current_error(conn, account_id)):
        return
    storage.set_status(conn, account_id, error=error)
