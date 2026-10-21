"""Mail-check-owned sheets: stable identities, sparse cells and atomic operations."""

from __future__ import annotations

from contextlib import contextmanager, nullcontext
import hashlib
import json
import sqlite3
import time
import uuid
from datetime import date

MAX_ROWS = 100_000
MAX_COLUMNS = 101
MAX_CELLS = 10_000
SCHEMA = """
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


@contextmanager
def atomic(conn):
    """SQLite serializes the version check and its writes across app processes."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


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


def snapshot(conn, tab):
    if conn.in_transaction:
        return _snapshot(conn, tab)
    conn.execute("BEGIN")
    try:
        return _snapshot(conn, tab)
    finally:
        conn.rollback()


def _snapshot(conn, tab):
    tab = conn.execute("SELECT t.*,COALESCE(a.label,t.title) AS account_title FROM native_tabs t LEFT JOIN accounts a ON a.id=t.account_id WHERE t.id=?", (tab["id"],)).fetchone()
    columns = [
        dict(c)
        for c in conn.execute(
            "SELECT id,title,kind,width FROM native_columns WHERE tab_id=? ORDER BY position,id",
            (tab["id"],),
        )
    ]
    row_records = [
        dict(r)
        for r in conn.execute(
            "SELECT id,work_date FROM native_rows WHERE tab_id=? ORDER BY position,id",
            (tab["id"],),
        )
    ]
    row_ids = [r["id"] for r in row_records]
    cells = {
        (r["row_id"], r["column_id"]): r
        for r in conn.execute(
            "SELECT c.* FROM native_cells c JOIN native_rows r ON r.id=c.row_id WHERE r.tab_id=?",
            (tab["id"],),
        )
    }
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
                }
            )
        rows.append(row)
    return {
        "id": tab["id"],
        "title": tab["account_title"],
        "revision": str(tab["revision"]),
        "structure_revision": tab["structure_revision"],
        "row_ids": ["", *row_ids],
        "row_dates": [None, *[r["work_date"] for r in row_records]],
        "columns": columns,
        "rows": rows,
        "header_row": 1,
        "refreshed_at": tab["updated_at"],
        "migration_notice": tab["migration_notice"],
        "properties": {
            "gridProperties": {"rowCount": len(rows), "columnCount": len(columns)}
        },
    }


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


def record_operation(conn, tab_id, operation, payload, *, structural=False):
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
            json.dumps({"revision": revision}),
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


def save(conn, tab, operation, changes, *, work_date="all", compact_rows=False):
    scope = date_scope(work_date)
    if not 1 <= len(changes) <= MAX_CELLS:
        raise ValueError("Save between 1 and 10,000 cells at a time.")
    payload = {
        "action": "save",
        "changes": changes,
        **({"compact_rows": True} if compact_rows else {}),
        **({"work_date": work_date} if work_date != "all" else {}),
    }
    with atomic(conn):
        if not check_operation(conn, tab["id"], operation, payload):
            seen = set()
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
                if kind == "check" and value not in ("", "true", "false"):
                    raise ValueError("Check cells must be checked or unchecked.")
                if kind == "check" and cell and cell["value"] == "true" and value != "true":
                    raise ValueError("Checked job links cannot be unchecked.")
                style = {
                    **(json.loads(cell["style"]) if cell else {}),
                    **(change.get("style") or {}),
                }
                conn.execute(
                    "INSERT INTO native_cells(row_id,column_id,value,style,version) VALUES(?,?,?,?,1) ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value,style=excluded.style,version=native_cells.version+1",
                    (row_id, column_id, value, json.dumps(style)),
                )
            from .sourcing_activity import record
            record(conn, "manual-edit")
            if compact_rows:
                compact_blank_rows(conn, tab["id"])
            record_operation(conn, tab["id"], operation, payload, structural=compact_rows)
        return snapshot(conn, tab)


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
    blanks = [row["id"] for row in conn.execute("""SELECT r.id FROM native_rows r WHERE r.tab_id=? AND NOT EXISTS (
        SELECT 1 FROM native_cells c JOIN native_columns col ON col.id=c.column_id
        WHERE c.row_id=r.id AND COALESCE(col.kind,'')!='check' AND trim(c.value, char(9)||char(10)||char(13)||' ')!='') ORDER BY r.position,r.id""", (tab_id,))]
    # One undated input row remains available after the last job.
    keep = blanks[-1] if blanks else new_id()
    conn.executemany("DELETE FROM native_rows WHERE id=?", [(row_id,) for row_id in blanks if row_id != keep])
    last = conn.execute("SELECT COALESCE(MAX(position),-1)+1 FROM native_rows WHERE tab_id=? AND id!=?", (tab_id, keep)).fetchone()[0]
    conn.execute("INSERT INTO native_rows(id,tab_id,position) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET position=excluded.position,work_date=NULL", (keep, tab_id, last))
    conn.execute("DELETE FROM native_cells WHERE row_id=?", (keep,))


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
