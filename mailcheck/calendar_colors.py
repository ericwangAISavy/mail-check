"""Per-account calendar colors chosen from a fixed palette (no free-form colors)."""
from __future__ import annotations

import sqlite3

# Number of palette slots the calendar styles define (account-color-0..N-1).
PALETTE_SIZE = 8

SCHEMA = '''CREATE TABLE IF NOT EXISTS account_calendar_colors (
    account_id INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    color INTEGER NOT NULL CHECK(color >= 0))'''


def colors(conn: sqlite3.Connection) -> dict[int, int]:
    """Chosen colors by account id; accounts without a choice are absent."""
    try:
        rows = conn.execute('SELECT account_id, color FROM account_calendar_colors').fetchall()
    except sqlite3.OperationalError:  # table not created yet (nothing chosen)
        return {}
    return {int(account_id): int(color) for account_id, color in rows if 0 <= int(color) < PALETTE_SIZE}


def set_color(conn: sqlite3.Connection, account_id: int, color: int | None) -> None:
    """Choose a palette slot for an account, or None to go back to automatic."""
    if color is not None and not (isinstance(color, int) and 0 <= color < PALETTE_SIZE):
        raise ValueError(f'Choose a color from the {PALETTE_SIZE} options.')
    if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (account_id,)).fetchone():
        raise LookupError('No such account.')
    conn.execute(SCHEMA)
    if color is None:
        conn.execute('DELETE FROM account_calendar_colors WHERE account_id=?', (account_id,))
    else:
        conn.execute('''INSERT INTO account_calendar_colors(account_id, color) VALUES(?, ?)
            ON CONFLICT(account_id) DO UPDATE SET color=excluded.color''', (account_id, color))
    conn.commit()
