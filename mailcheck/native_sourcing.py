"""Mail-check-owned sheets: stable identities, sparse cells and atomic operations."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import logging
import os
import sqlite3
import sys
import time
import uuid
from datetime import date

MAX_ROWS = 100_000
MAX_COLUMNS = 101
MAX_CELLS = 10_000
MAX_SNAPSHOT_CELLS = 100_000
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


class SnapshotTooLarge(ValueError):
    """The full editor response would exceed its memory budget."""


PROTECTION_BATCH_SIZE = 500
SCHEMA = """
CREATE TABLE IF NOT EXISTS sourcing_blocked_roles (
 account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
 key TEXT NOT NULL, keyword TEXT NOT NULL, PRIMARY KEY(account_id,key)
);

CREATE TABLE IF NOT EXISTS sourcing_blocked_companies (key TEXT PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS native_books (
 id INTEGER PRIMARY KEY AUTOINCREMENT, bidder_id INTEGER NOT NULL UNIQUE REFERENCES bidders(id),
 title TEXT NOT NULL, legacy_book_id INTEGER UNIQUE
);
CREATE TABLE IF NOT EXISTS native_tabs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, book_id INTEGER NOT NULL REFERENCES native_books(id) ON DELETE CASCADE,
 account_id INTEGER REFERENCES accounts(id) ON DELETE SET NULL, account_label TEXT NOT NULL,
 title TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, structure_revision INTEGER NOT NULL DEFAULT 1,
 updated_at REAL NOT NULL, legacy_tab_id INTEGER UNIQUE, migration_notice TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0,
 UNIQUE(book_id,account_id)
);
CREATE TABLE IF NOT EXISTS native_columns (
 id TEXT PRIMARY KEY, tab_id INTEGER NOT NULL REFERENCES native_tabs(id) ON DELETE CASCADE,
 position INTEGER NOT NULL, title TEXT NOT NULL, kind TEXT, width INTEGER NOT NULL DEFAULT 220
);
CREATE UNIQUE INDEX IF NOT EXISTS native_column_kind ON native_columns(tab_id,kind) WHERE kind IS NOT NULL;
CREATE TABLE IF NOT EXISTS native_rows (
 id TEXT PRIMARY KEY, tab_id INTEGER NOT NULL REFERENCES native_tabs(id) ON DELETE CASCADE, position INTEGER NOT NULL, work_date TEXT
);
CREATE INDEX IF NOT EXISTS native_row_order ON native_rows(tab_id,position);
CREATE TABLE IF NOT EXISTS native_cells (
 row_id TEXT NOT NULL REFERENCES native_rows(id) ON DELETE CASCADE,
 column_id TEXT NOT NULL REFERENCES native_columns(id) ON DELETE CASCADE,
 value TEXT NOT NULL DEFAULT '', style TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
 PRIMARY KEY(row_id,column_id)
);
CREATE TABLE IF NOT EXISTS native_operations (
 id TEXT PRIMARY KEY, tab_id INTEGER NOT NULL REFERENCES native_tabs(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, result TEXT NOT NULL, created_at REAL NOT NULL
);
"""


def new_id():
    return uuid.uuid4().hex


# Work-queue lifecycle. Nothing is stored except when a row first held a job
# (native_rows.created_at); status is derived from that and the check cell.
LIFETIME_SECONDS = 7 * 24 * 3600
WARNING_SECONDS = 48 * 3600
QUEUE_ZONE = "America/Chicago"
_HAS_JOB = """EXISTS (SELECT 1 FROM native_cells jc JOIN native_columns jcol ON jcol.id=jc.column_id
    WHERE jc.row_id={row}.id AND COALESCE(jcol.kind,'')!='check'
    AND trim(jc.value, char(9)||char(10)||char(13)||' ')!='')"""


def _day_start(day, zone=QUEUE_ZONE):
    from datetime import datetime, time as day_time
    from zoneinfo import ZoneInfo
    return datetime.combine(day, day_time.min, ZoneInfo(zone)).timestamp()


def today_start(now=None):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    current = datetime.fromtimestamp(time.time() if now is None else now, ZoneInfo(QUEUE_ZONE))
    return _day_start(current.date())


def sync_created(conn, tab_id, now=None, *, clear=False):
    """Stamp rows the moment they first hold a job. Edits, checks, date moves and
    reordering never change the stamp. Rows emptied by a save are reset by
    compact_blank_rows; `clear` re-checks the whole sheet after structural
    operations, which are rare, so ordinary saves never scan every job."""
    stamp = time.time() if now is None else now
    conn.execute(f"UPDATE native_rows SET created_at=? WHERE tab_id=? AND created_at IS NULL AND {_HAS_JOB.format(row='native_rows')}", (stamp, tab_id))
    if clear:
        conn.execute(f"UPDATE native_rows SET created_at=NULL WHERE tab_id=? AND created_at IS NOT NULL AND NOT {_HAS_JOB.format(row='native_rows')}", (tab_id,))


def backfill_created(conn, now=None):
    """One-time upgrade: existing jobs start at the beginning of their sourcing day
    (Chicago); jobs that never had a day start now. Already-stamped rows are kept."""
    stamp = time.time() if now is None else now
    pending = f"created_at IS NULL AND {_HAS_JOB.format(row='native_rows')}"
    for (day,) in conn.execute(f"SELECT DISTINCT work_date FROM native_rows WHERE work_date IS NOT NULL AND {pending}").fetchall():
        try:
            start = _day_start(date.fromisoformat(day))
        except (TypeError, ValueError):
            continue
        conn.execute(f"UPDATE native_rows SET created_at=? WHERE work_date=? AND {pending}", (start, day))
    conn.execute(f"UPDATE native_rows SET created_at=? WHERE {pending}", (stamp,))


def workload(conn, tab_ids, now=None):
    """To do, new today, carryover, expiring soon, completed and expired per sheet,
    in one grouped query."""
    if not tab_ids:
        return {}
    current = time.time() if now is None else now
    expire_before, warn_before, day = current - LIFETIME_SECONDS, current - LIFETIME_SECONDS + WARNING_SECONDS, today_start(current)
    placeholders = ",".join("?" for _ in tab_ids)
    # One pass over the sheets' cells, grouped per row, rather than two correlated
    # lookups per row: this runs on every sheet-list request.
    rows = conn.execute(f"""SELECT tab_id,
        SUM(CASE WHEN NOT done AND created_at>? THEN 1 ELSE 0 END) AS todo,
        SUM(CASE WHEN NOT done AND created_at>? AND created_at>=? THEN 1 ELSE 0 END) AS new_today,
        SUM(CASE WHEN NOT done AND created_at>? AND created_at<=? THEN 1 ELSE 0 END) AS expiring,
        SUM(CASE WHEN done THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN NOT done AND created_at<=? THEN 1 ELSE 0 END) AS expired,
        COUNT(*) AS total
        FROM (SELECT r.tab_id, COALESCE(r.created_at, ?) AS created_at,
                MAX(col.kind='check' AND c.value='true') AS done,
                MAX(COALESCE(col.kind,'')!='check' AND trim(c.value, char(9)||char(10)||char(13)||' ')!='') AS job
              FROM native_rows r JOIN native_cells c ON c.row_id=r.id JOIN native_columns col ON col.id=c.column_id
              WHERE r.tab_id IN ({placeholders}) GROUP BY r.id)
        WHERE job GROUP BY tab_id""", (expire_before, expire_before, day, expire_before, warn_before, expire_before, current, *tab_ids)).fetchall()
    counts = {tab_id: {"todo": 0, "new_today": 0, "carryover": 0, "expiring": 0, "completed": 0, "expired": 0, "all": 0} for tab_id in tab_ids}
    for row in rows:
        counts[row["tab_id"]] = {"todo": row["todo"], "new_today": row["new_today"], "carryover": row["todo"] - row["new_today"],
                                 "expiring": row["expiring"], "completed": row["completed"], "expired": row["expired"], "all": row["total"]}
    return counts


@contextmanager
def atomic(conn, *, deferred=False):
    """SQLite serializes the version check and its writes across app processes."""
    conn.execute("BEGIN" if deferred else "BEGIN IMMEDIATE")
    started = time.monotonic()
    caller = sys._getframe(2)  # frame 1 is contextlib's __enter__
    where = f"{os.path.basename(caller.f_code.co_filename)}:{caller.f_code.co_name}"
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        held = time.monotonic() - started
        if not deferred and held > 10:
            # Other processes cannot write while this is held; name the holder so slow ones can be fixed.
            logging.getLogger(__name__).warning("Database write lock was held for %.0f seconds by %s.", held, where)


def _create_book(conn, bidder_id, title, legacy_id=None):
    if not conn.execute("SELECT 1 FROM bidders WHERE id=? AND removed_at IS NULL", (bidder_id,)).fetchone():
        raise ValueError("Bidder not found.")
    conn.execute(
        "INSERT OR IGNORE INTO native_books(bidder_id,title,legacy_book_id) VALUES(?,?,?)",
        (bidder_id, title.strip() or "Applications", legacy_id),
    )
    return conn.execute(
        "SELECT id FROM native_books WHERE bidder_id=?", (bidder_id,)
    ).fetchone()[0]


def create_book(conn, bidder_id, title="Applications"):
    with atomic(conn):
        return _create_book(conn, bidder_id, title)


def _create_tab(
    conn,
    book_id,
    account_id,
    title,
    *,
    label=None,
    legacy_id=None,
    columns=None,
    count=100,
    notice="",
):
    if label is None:
        account = conn.execute(
            "SELECT label,email FROM accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not account:
            raise ValueError("Profile not found.")
        label = account["email"]
    account = conn.execute("SELECT label FROM accounts WHERE id=?", (account_id,)).fetchone()
    if account:
        title = account["label"]
    tab_id = conn.execute(
        "INSERT INTO native_tabs(book_id,account_id,account_label,title,updated_at,legacy_tab_id,migration_notice) VALUES(?,?,?,?,?,?,?) RETURNING id",
        (
            book_id,
            account_id,
            label,
            title.strip() or label,
            time.time(),
            legacy_id,
            notice,
        ),
    ).fetchone()[0]
    definitions = columns or [
        ("Company", "company"),
        ("Role", "role"),
        ("Job link", "link"),
        ("Check", "check"),
    ]
    conn.executemany(
        "INSERT INTO native_columns(id,tab_id,position,title,kind) VALUES(?,?,?,?,?)",
        [
            (new_id(), tab_id, i, name, kind)
            for i, (name, kind) in enumerate(definitions)
        ],
    )
    conn.execute("UPDATE native_columns SET width=76 WHERE tab_id=? AND kind='check'", (tab_id,))
    conn.executemany(
        "INSERT INTO native_rows(id,tab_id,position) VALUES(?,?,?)",
        [(new_id(), tab_id, i) for i in range(max(count, 1))],
    )
    return tab_id


def create_tab(conn, book_id, account_id, title):
    with atomic(conn):
        return _create_tab(conn, book_id, account_id, title)


def owned(conn, tab_id, principal):
    row = conn.execute(
        "SELECT t.*,b.bidder_id FROM native_tabs t JOIN native_books b ON b.id=t.book_id WHERE t.id=?",
        (tab_id,),
    ).fetchone()
    if (
        not row
        or (row["archived"] and principal["role"] != "admin")
        or (principal["role"] != "admin" and row["bidder_id"] != principal["bidder_id"])
    ):
        raise PermissionError("Sheet not found.")
    return dict(row)


def snapshot(conn, tab, *, compact=False):
    if conn.in_transaction:
        return _snapshot(conn, tab, compact=compact)
    conn.execute("BEGIN")
    try:
        return _snapshot(conn, tab, compact=compact)
    finally:
        conn.rollback()


def _check_snapshot_budget(conn, tab):
    row_count = conn.execute("SELECT COUNT(*) FROM native_rows WHERE tab_id=?", (tab['id'],)).fetchone()[0]
    column_count = conn.execute("SELECT COUNT(*) FROM native_columns WHERE tab_id=?", (tab['id'],)).fetchone()[0]
    if (row_count + 1) * column_count > MAX_SNAPSHOT_CELLS:
        raise SnapshotTooLarge("This sheet is too large to open safely. Export CSV to preserve your data, then split it into smaller sheets.")
    text_bytes = conn.execute("""SELECT COALESCE(SUM(length(CAST(c.value AS BLOB)) + length(CAST(c.style AS BLOB))),0)
        FROM native_cells c JOIN native_rows r ON r.id=c.row_id WHERE r.tab_id=?""", (tab['id'],)).fetchone()[0]
    if text_bytes > MAX_SNAPSHOT_BYTES:
        raise SnapshotTooLarge("This sheet contains too much text to open safely. Export CSV to preserve your data, then split it into smaller sheets.")


def _snapshot(conn, tab, *, compact=False):
    _check_snapshot_budget(conn, tab)
    tab = conn.execute("SELECT t.*,COALESCE(a.label,t.title) AS account_title FROM native_tabs t LEFT JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (tab["id"],)).fetchone()
    columns = [
        dict(c)
        for c in conn.execute(
            "SELECT id,title,kind,width FROM native_columns WHERE tab_id=? ORDER BY position,id",
            (tab["id"],),
        )
    ]
    fixed_titles={'company':'Company','role':'Role','link':'Job link','check':'Check'}
    for column in columns:
        column['title']=fixed_titles.get(column['kind'],column['title'])
    row_records = [
        dict(r)
        for r in conn.execute(
            "SELECT id,work_date,created_at FROM native_rows WHERE tab_id=? ORDER BY position,id",
            (tab["id"],),
        )
    ]
    row_ids = [r["id"] for r in row_records]
    result = {
        "id": tab["id"],
        "title": tab["account_title"],
        "revision": str(tab["revision"]),
        "structure_revision": tab["structure_revision"],
        "row_ids": ["", *row_ids],
        "row_dates": [None, *[r["work_date"] for r in row_records]],
        # The work queue derives To do, Expired and Expiring soon from these. The
        # snapshot stays identical for an unchanged sheet; the clock comes from the
        # response's Date header.
        "row_created": [None, *[r["created_at"] for r in row_records]],
        "columns": columns,
        "header_row": 1,
        "refreshed_at": tab["updated_at"],
        "migration_notice": tab["migration_notice"],
        "properties": {
            "gridProperties": {"rowCount": len(row_ids) + 1, "columnCount": len(columns)}
        },
    }
    stored_cells = conn.execute(
        "SELECT c.* FROM native_cells c JOIN native_rows r ON r.id=c.row_id WHERE r.tab_id=?",
        (tab["id"],),
    )
    confirmed_times = {r['row_id']: r['confirmed_at'] for r in conn.execute(
        "SELECT e.row_id,e.confirmed_at FROM sourcing_check_activity e JOIN native_rows r ON r.id=e.row_id WHERE r.tab_id=?", (tab['id'],))}
    if compact:
        row_positions = {key: i for i, key in enumerate(row_ids, start=1)}
        column_positions = {column['id']: i for i, column in enumerate(columns)}
        result['cell_entries'] = [
            [row_positions[cell['row_id']], column_positions[cell['column_id']],
             cell['value'], cell['version'], json.loads(cell['style']) if cell['style'] != '{}' else {}]
            for cell in stored_cells if cell['column_id'] in column_positions
        ]
        result['confirmation_times'] = [[row_positions[key], stamp] for key, stamp in confirmed_times.items() if stamp is not None]
        return result

    cells = {(r["row_id"], r["column_id"]): r for r in stored_cells}
    rows = [
        [
            {
                "value": c["title"],
                "display": c["title"],
                "formula": False,
                "link": "",
                "version": 0,
                "style": {"bold": True},
            }
            for c in columns
        ]
    ]
    for row_id in row_ids:
        row = []
        for column in columns:
            cell = cells.get((row_id, column["id"]))
            value = cell["value"] if cell else ""
            row.append(
                {
                    "value": value,
                    "display": value,
                    "formula": False,
                    "link": (
                        value
                        if column["kind"] == "link"
                        and value.lower().startswith(("https://", "http://"))
                        else ""
                    ),
                    "version": cell["version"] if cell else 0,
                    "style": json.loads(cell["style"]) if cell else {},
                    **({"checked_at": confirmed_times.get(row_id)} if column["kind"] == "check" else {}),
                }
            )
        rows.append(row)
    result['rows'] = rows
    return result


def search_rows(conn, tab, words, context=""):
    """Search sparse values without allocating the editor's dense styled grid."""
    from itertools import groupby

    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute("BEGIN")
    try:
        _check_snapshot_budget(conn, tab)
        records = conn.execute(
            "SELECT r.id,r.work_date,c.value,col.kind FROM native_rows r "
            "LEFT JOIN native_cells c ON c.row_id=r.id "
            "LEFT JOIN native_columns col ON col.id=c.column_id "
            "WHERE r.tab_id=? ORDER BY r.position,r.id,col.position,col.id",
            (tab['id'],),
        )
        for number, (row_id, cells) in enumerate(groupby(records, key=lambda c: c['id']), 1):
            values = list(cells)
            text = [cell['value'] or '' for cell in values]
            if not any(text):
                continue
            haystack = ' '.join([*text, context]).casefold()
            if not all(word in haystack for word in words):
                continue
            fields = {cell['kind']: cell['value'] for cell in values if cell['kind']}
            yield {
                'row': number, 'row_id': row_id, 'work_date': values[0]['work_date'],
                **{kind: fields.get(kind, '') for kind in ('company', 'role', 'link')},
            }
    finally:
        if own_transaction:
            conn.rollback()


def fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def check_operation(conn, tab_id, operation, payload):
    digest = fingerprint(payload)
    previous = conn.execute(
        "SELECT * FROM native_operations WHERE id=?", (operation,)
    ).fetchone()
    if previous:
        if previous["tab_id"] != tab_id or previous["fingerprint"] != digest:
            raise ValueError("This operation ID was used for different changes.")
        return True
    return False


def record_operation(conn, tab_id, operation, payload, *, structural=False, filtered=None):
    sync_created(conn, tab_id, clear=structural)
    conn.execute(
        "UPDATE native_tabs SET revision=revision+1,structure_revision=structure_revision+?,updated_at=? WHERE id=?",
        (int(structural), time.time(), tab_id),
    )
    revision = conn.execute(
        "SELECT revision FROM native_tabs WHERE id=?", (tab_id,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO native_operations VALUES(?,?,?,?,?)",
        (
            operation,
            tab_id,
            fingerprint(payload),
            json.dumps({"revision": revision, **({"filtered": filtered} if filtered else {})}),
            time.time(),
        ),
    )


def date_scope(value):
    """None is the explicitly undated bucket; 'all' retains legacy API behavior."""
    if value == "all":
        return value
    if value == "undated":
        return None
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError("Choose a valid date (YYYY-MM-DD) or Undated.")
    return value


def save(conn, tab, operation, changes, *, work_date="all", compact_rows=False, assign_date=None):
    scope = date_scope(work_date)
    # The work queue edits jobs from many days at once: only blank rows that
    # receive a job take this date; rows that already have a day keep it.
    assign = None if assign_date is None else date_scope(assign_date)
    if assign_date is not None and (scope != "all" or assign in ("all", None)):
        raise ValueError("Choose a valid date for new jobs.")
    if not 1 <= len(changes) <= MAX_CELLS:
        raise ValueError("Save between 1 and 10,000 cells at a time.")
    payload = {
        "action": "save",
        "changes": changes,
        **({"compact_rows": True} if compact_rows else {}),
        **({"work_date": work_date} if work_date != "all" else {}),
        **({"assign_date": assign_date} if assign_date is not None else {}),
    }
    with atomic(conn):
        if not check_operation(conn, tab["id"], operation, payload):
            from . import sourcing_filters
            candidates=set()
            # Read the pre-save check state only for touched rows. Batching keeps
            # large pastes below SQLite's parameter limit without scanning history.
            row_ids = list(dict.fromkeys(change["row_id"] for change in changes))
            protected = set()
            for start in range(0, len(row_ids), PROTECTION_BATCH_SIZE):
                batch = row_ids[start:start + PROTECTION_BATCH_SIZE]
                placeholders = ",".join("?" for _ in batch)
                protected.update(r[0] for r in conn.execute(f"""SELECT v.row_id FROM native_cells v
                    JOIN native_columns c ON c.id=v.column_id
                    WHERE c.tab_id=? AND c.kind='check' AND v.value='true'
                    AND v.row_id IN ({placeholders})""", (tab["id"], *batch)))
            seen = set()
            cleared_content=False
            for change in changes:
                row_id, column_id = change["row_id"], change["column_id"]
                if (row_id, column_id) in seen:
                    raise ValueError("A cell may appear only once in a save.")
                seen.add((row_id, column_id))
                if (
                    not conn.execute(
                        "SELECT 1 FROM native_rows WHERE id=? AND tab_id=?",
                        (row_id, tab["id"]),
                    ).fetchone()
                    or not conn.execute(
                        "SELECT 1 FROM native_columns WHERE id=? AND tab_id=?",
                        (column_id, tab["id"]),
                    ).fetchone()
                ):
                    raise FileExistsError(
                        "A row or column changed or was removed. Your draft has been preserved."
                    )
                if scope != "all":
                    row_date = conn.execute(
                        "SELECT work_date FROM native_rows WHERE id=?", (row_id,)
                    ).fetchone()[0]
                    nonempty = conn.execute(
                        "SELECT 1 FROM native_cells WHERE row_id=? AND value!='' LIMIT 1",
                        (row_id,),
                    ).fetchone()
                    if row_date != scope and (row_date is not None or nonempty):
                        raise FileExistsError(
                            "This job was assigned to another day. Your draft is preserved."
                        )
                    if row_date != scope:
                        conn.execute(
                            "UPDATE native_rows SET work_date=? WHERE id=?",
                            (scope, row_id),
                        )
                cell = conn.execute(
                    "SELECT * FROM native_cells WHERE row_id=? AND column_id=?",
                    (row_id, column_id),
                ).fetchone()
                if (cell["version"] if cell else 0) != change["expected_version"]:
                    raise FileExistsError(
                        "Another person changed one of these cells. Compare your draft before reloading."
                    )
                value = change.get("value")
                if value is None:
                    value = cell["value"] if cell else ""
                if not isinstance(value, str) or len(value) > 50_000:
                    raise ValueError("A cell can contain up to 50,000 text characters.")
                kind = conn.execute("SELECT kind FROM native_columns WHERE id=?", (column_id,)).fetchone()[0]
                if kind!='check' and (cell['value'] if cell else '').strip() and not value.strip():
                    cleared_content=True
                if change.get("value") is not None:
                    from .sourcing_filters import normalize_job_cell
                    value = normalize_job_cell(value,kind)
                if kind == "check" and value not in ("", "true", "false"):
                    raise ValueError("Check cells must be checked or unchecked.")
                if kind == "check" and cell and cell["value"] == "true" and value != "true":
                    raise ValueError("Checked job links cannot be unchecked.")
                if (kind == 'link' or kind in ('company','role') and not (cell['value'] if cell else '').strip()) and value != (cell['value'] if cell else ''):
                    # Filter new URLs and newly completed company/role fields, never
                    # remove an already checked historical application.
                    if row_id not in protected:candidates.add(row_id)
                style = {
                    **(json.loads(cell["style"]) if cell else {}),
                    **(change.get("style") or {}),
                }
                # Lock rows that were checked before this save, so an initial
                # paste can still set the job details and check together.
                if row_id in protected and (
                    value != (cell["value"] if cell else "")
                    or style != (json.loads(cell["style"]) if cell else {})
                ):
                    raise ValueError("Checked rows cannot be edited.")
                conn.execute(
                    "INSERT INTO native_cells(row_id,column_id,value,style,version) VALUES(?,?,?,?,1) ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value,style=excluded.style,version=native_cells.version+1",
                    (row_id, column_id, value, json.dumps(style)),
                )
            if assign is not None:
                for start in range(0, len(row_ids), PROTECTION_BATCH_SIZE):
                    batch = row_ids[start:start + PROTECTION_BATCH_SIZE]
                    conn.execute(f"UPDATE native_rows SET work_date=? WHERE work_date IS NULL AND id IN ({','.join('?' for _ in batch)}) AND {_HAS_JOB.format(row='native_rows')}", (assign, *batch))
            filtered=sourcing_filters.filter_rows(conn,tab,candidates)
            from .sourcing_activity import record
            record(conn, "manual-edit")
            compacted=compact_blank_rows(conn, tab["id"]) if compact_rows or cleared_content else False
            record_operation(conn, tab["id"], operation, payload, structural=compacted or bool(sum(filtered.values())), filtered=filtered)
        from .sourcing_filters import result
        return result(conn, tab, operation)


def migrate(conn):
    """Copy available legacy snapshots once; never call Google or modify legacy data."""
    # Database upgrades already own the write transaction and its commit.
    with nullcontext() if conn.in_transaction else atomic(conn):
        for old_book in conn.execute("SELECT * FROM sourcing_books").fetchall():
            book_id = _create_book(
                conn, old_book["bidder_id"], old_book["title"], old_book["id"]
            )
            for old in conn.execute(
                "SELECT * FROM sourcing_tabs WHERE book_id=?", (old_book["id"],)
            ).fetchall():
                if conn.execute(
                    "SELECT 1 FROM native_tabs WHERE legacy_tab_id=?", (old["id"],)
                ).fetchone():
                    continue
                try:
                    cached = json.loads(old["snapshot"] or "{}")
                    rows = cached.get("rows", [])
                    if not isinstance(rows, list):
                        raise ValueError("Invalid rows")
                except (ValueError, TypeError, AttributeError):
                    rows = []
                notice = (
                    "Imported from the last cached Google copy. Newer Google edits must be pasted or imported manually."
                    if rows
                    else "No cached rows were available. Paste or import the current jobs into this sheet."
                )
                positions = {
                    old["company_col"]: "company",
                    old["role_col"]: "role",
                    old["link_col"]: "link",
                }
                header_index = max(old["header_row"] - 1, 0)
                header = rows[header_index] if header_index < len(rows) else []
                count = min(
                    MAX_COLUMNS,
                    max(
                        3,
                        max(positions) + 1,
                        max((len(r) for r in rows if isinstance(r, list)), default=0),
                    ),
                )
                definitions = []
                for i in range(count):
                    title = (
                        str(header[i].get("display") or header[i].get("value") or "")
                        if i < len(header) and isinstance(header[i], dict)
                        else ""
                    )
                    definitions.append(
                        (
                            title
                            or {
                                "company": "Company",
                                "role": "Role",
                                "link": "Job link",
                            }.get(positions.get(i), f"Column {i+1}"),
                            positions.get(i),
                        )
                    )
                data = rows[old["header_row"] : old["header_row"] + MAX_ROWS]
                missing_formula = any(
                    isinstance(cell, dict)
                    and cell.get("formula")
                    and not cell.get("display")
                    for row in data
                    if isinstance(row, list)
                    for cell in row
                )
                if missing_formula:
                    notice += " Some formula display values were unavailable; check the imported rows against your original file."
                tab_id = _create_tab(
                    conn,
                    book_id,
                    old["account_id"],
                    old["title"],
                    label=old["account_label"],
                    legacy_id=old["id"],
                    columns=definitions,
                    count=max(100, len(data)),
                    notice=notice,
                )
                native_rows = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM native_rows WHERE tab_id=? ORDER BY position",
                        (tab_id,),
                    )
                ]
                native_columns = [
                    r[0]
                    for r in conn.execute(
                        "SELECT id FROM native_columns WHERE tab_id=? ORDER BY position",
                        (tab_id,),
                    )
                ]
                for r, row in enumerate(data):
                    if not isinstance(row, list):
                        continue
                    for c, cell in enumerate(row[:count]):
                        if not isinstance(cell, dict):
                            continue
                        value = (
                            cell.get("display")
                            if cell.get("formula")
                            else cell.get("value", cell.get("display", ""))
                        )
                        if positions.get(c) == "link":
                            value = cell.get("link") or value
                        value = "" if value is None else str(value)
                        if value:
                            conn.execute(
                                "INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)",
                                (native_rows[r], native_columns[c], value),
                            )

        upgrade_verification_columns(conn)
        backfill_created(conn)


def upgrade_verification_columns(conn):
    for tab in conn.execute("SELECT id FROM native_tabs").fetchall():
        tab_id = tab["id"]
        if conn.execute("SELECT 1 FROM native_columns WHERE tab_id=? AND kind='check'", (tab_id,)).fetchone():
            continue
        link = conn.execute("SELECT position FROM native_columns WHERE tab_id=? AND kind='link'", (tab_id,)).fetchone()
        position = link[0] + 1 if link else 3
        conn.execute("UPDATE native_columns SET position=position+1 WHERE tab_id=? AND position>=?", (tab_id, position))
        conn.execute("INSERT INTO native_columns(id,tab_id,position,title,kind,width) VALUES(?,?,?,'Check','check',76)", (new_id(), tab_id, position))
        conn.execute("UPDATE native_tabs SET revision=revision+1,structure_revision=structure_revision+1 WHERE id=?", (tab_id,))
    conn.execute("UPDATE native_tabs SET title=(SELECT label FROM accounts WHERE id=native_tabs.account_id) WHERE account_id IS NOT NULL AND EXISTS(SELECT 1 FROM accounts WHERE id=native_tabs.account_id)")


def compact_blank_rows(conn, tab_id):
    before=[tuple(row) for row in conn.execute('SELECT id,work_date FROM native_rows WHERE tab_id=? ORDER BY position,id',(tab_id,))]
    blanks = [row["id"] for row in conn.execute("""SELECT r.id FROM native_rows r WHERE r.tab_id=? AND NOT EXISTS (
        SELECT 1 FROM native_cells c JOIN native_columns col ON col.id=c.column_id
        WHERE c.row_id=r.id AND ((COALESCE(col.kind,'')!='check' AND trim(c.value, char(9)||char(10)||char(13)||' ')!='')
            OR (col.kind='check' AND c.value='true'))) ORDER BY r.position,r.id""", (tab_id,))]
    if len(blanks)==1 and before and before[-1]==(blanks[0],None):
        return False  # Already compact; retain the input row's cell versions/styles.
    # One undated input row remains available after the last job.
    keep = blanks[-1] if blanks else new_id()
    conn.executemany("DELETE FROM native_rows WHERE id=?", [(row_id,) for row_id in blanks if row_id != keep])
    last = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM native_rows WHERE tab_id=? AND id!=?", (tab_id, keep)).fetchone()[0]
    conn.execute("INSERT INTO native_rows(id,tab_id,position) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET position=excluded.position,work_date=NULL,created_at=NULL", (keep, tab_id, last))
    conn.execute("DELETE FROM native_cells WHERE row_id=?", (keep,))
    after=[tuple(row) for row in conn.execute('SELECT id,work_date FROM native_rows WHERE tab_id=? ORDER BY position,id',(tab_id,))]
    return before!=after


def structure(conn, tab, operation, revision, command):
    from .sourcing_structure import structure as apply_structure

    return apply_structure(conn, tab, operation, revision, command)


def append(conn, tab, operation, revision, rows, *, work_date="all"):
    from .sourcing_structure import append as apply_append

    return apply_append(conn, tab, operation, revision, rows, work_date=work_date)


def delete_tab(conn, tab, revision):
    """Delete a local sheet and its retained import copy in one transaction."""
    from .sourcing_structure import check_revision
    with atomic(conn):
        check_revision(conn, tab["id"], revision)
        legacy_id = conn.execute("SELECT legacy_tab_id FROM native_tabs WHERE id=?", (tab["id"],)).fetchone()[0]
        conn.execute("DELETE FROM native_tabs WHERE id=?", (tab["id"],))
        # Prevent the one-time import migration from recreating a deleted sheet.
        if legacy_id is not None:
            conn.execute("DELETE FROM sourcing_tabs WHERE id=?", (legacy_id,))
    return {"ok": True}
