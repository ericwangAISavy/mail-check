"""Atomic row/column operations for native sheets."""

import json
from . import native_sourcing as sheets


def ordered_rows(conn, tab_id):
    return [
        r[0]
        for r in conn.execute(
            "SELECT id FROM native_rows WHERE tab_id=? ORDER BY position,id", (tab_id,)
        )
    ]


def reorder(conn, ids):
    conn.executemany(
        "UPDATE native_rows SET position=? WHERE id=?", list(enumerate(ids))
    )


def insert_rows(conn, tab_id, count, at=None, work_date="all"):
    scope = sheets.date_scope(work_date)
    ids = ordered_rows(conn, tab_id)
    if not 1 <= count <= 10_000 or len(ids) + count > sheets.MAX_ROWS:
        raise ValueError(
            "Insert up to 10,000 imported rows at a time, up to 100,000 rows per sheet."
        )
    if at and at not in ids:
        raise FileExistsError("The selected row was removed. Reload the sheet.")
    offset = ids.index(at) if at else len(ids)
    new = [sheets.new_id() for _ in range(count)]
    conn.executemany(
        "INSERT INTO native_rows(id,tab_id,position,work_date) VALUES(?,?,0,?)",
        [(key, tab_id, None if scope == "all" else scope) for key in new],
    )
    reorder(conn, ids[:offset] + new + ids[offset:])
    return new


def check_revision(conn, tab_id, revision):
    current = conn.execute(
        "SELECT revision FROM native_tabs WHERE id=?", (tab_id,)
    ).fetchone()
    if not current or str(current[0]) != str(revision):
        raise FileExistsError(
            "The sheet changed. Reload before changing its structure or importing rows."
        )


def structure(conn, tab, operation, revision, command):
    payload = {"action": "structure", "revision": revision, "command": command}
    with sheets.atomic(conn):
        if not sheets.check_operation(conn, tab["id"], operation, payload):
            check_revision(conn, tab["id"], revision)
            action = command["action"]
            if action == "insert_rows":
                if not 1 <= command.get("count", 20) <= 1000:
                    raise ValueError("Insert 1–1,000 rows at a time.")
                insert_rows(
                    conn,
                    tab["id"],
                    command.get("count", 20),
                    command.get("at_row_id"),
                    command.get("work_date", "all"),
                )
            elif action == "delete_rows":
                ids = command.get("ids", [])
                rows = set(ordered_rows(conn, tab["id"]))
                if not ids or len(ids) > 1000 or not set(ids) <= rows:
                    raise ValueError(
                        "Choose up to 1,000 existing rows from this sheet."
                    )
                conn.executemany(
                    "DELETE FROM native_rows WHERE id=? AND tab_id=?",
                    [(key, tab["id"]) for key in set(ids)],
                )
                if len(rows) == len(set(ids)):
                    insert_rows(conn, tab["id"], 1)
                reorder(conn, ordered_rows(conn, tab["id"]))
            elif action == "move_date":
                ids = command.get("ids", [])
                rows = set(ordered_rows(conn, tab["id"]))
                if not ids or len(ids) > 1000 or not set(ids) <= rows:
                    raise ValueError(
                        "Choose up to 1,000 existing rows from this sheet."
                    )
                scope = sheets.date_scope(command.get("work_date", ""))
                if scope == "all":
                    raise ValueError("Choose a date or Undated.")
                for row_id in set(ids):
                    conn.execute("""UPDATE native_cells SET value='false',version=version+1 WHERE row_id=? AND value='true'
                        AND column_id=(SELECT id FROM native_columns WHERE tab_id=? AND kind='check')
                        AND EXISTS(SELECT 1 FROM native_rows WHERE id=? AND work_date IS NOT ?)""", (row_id, tab["id"], row_id, scope))
                conn.executemany(
                    "UPDATE native_rows SET work_date=? WHERE id=?",
                    [(scope, key) for key in set(ids)],
                )
            elif action == "add_column":
                columns = conn.execute(
                    "SELECT * FROM native_columns WHERE tab_id=? ORDER BY position",
                    (tab["id"],),
                ).fetchall()
                if len(columns) >= sheets.MAX_COLUMNS:
                    raise ValueError("A sheet can contain up to 101 columns.")
                title = command.get("title", "").strip()
                if not title or len(title) > 100:
                    raise ValueError("Enter a column name of 1–100 characters.")
                conn.execute(
                    "INSERT INTO native_columns(id,tab_id,position,title) VALUES(?,?,?,?)",
                    (sheets.new_id(), tab["id"], len(columns), title),
                )
            elif action in ("delete_column", "rename_column", "resize_column"):
                column = conn.execute(
                    "SELECT * FROM native_columns WHERE id=? AND tab_id=?",
                    (command.get("column_id"), tab["id"]),
                ).fetchone()
                if not column:
                    raise ValueError("Choose a column from this sheet.")
                if column["kind"] == "check" and action == "rename_column":
                    raise ValueError("The Check column keeps its name.")
                if action == "delete_column":
                    if column["kind"]:
                        raise ValueError(
                            "Company, Role and Job link columns are required. Their names can be changed."
                        )
                    conn.execute(
                        "DELETE FROM native_columns WHERE id=?", (column["id"],)
                    )
                    ids = [
                        r[0]
                        for r in conn.execute(
                            "SELECT id FROM native_columns WHERE tab_id=? ORDER BY position,id",
                            (tab["id"],),
                        )
                    ]
                    conn.executemany(
                        "UPDATE native_columns SET position=? WHERE id=?",
                        list(enumerate(ids)),
                    )
                elif action == "rename_column":
                    title = command.get("title", "").strip()
                    if not title or len(title) > 100:
                        raise ValueError("Enter a column name of 1–100 characters.")
                    conn.execute(
                        "UPDATE native_columns SET title=? WHERE id=?",
                        (title, column["id"]),
                    )
                else:
                    width = command.get("width", 220)
                    if not 70 <= width <= 1200:
                        raise ValueError("Choose a column width of 70–1,200 pixels.")
                    conn.execute(
                        "UPDATE native_columns SET width=? WHERE id=?",
                        (width, column["id"]),
                    )
            else:
                raise ValueError("Unknown sheet action.")
            sheets.record_operation(
                conn, tab["id"], operation, payload, structural=True
            )
        return sheets.snapshot(conn, tab)


def append_cells(conn, tab, rows, *, validated_import=False, work_date="all"):
    columns = conn.execute(
        "SELECT id FROM native_columns WHERE tab_id=? ORDER BY position,id",
        (tab["id"],),
    ).fetchall()
    if (
        not rows
        or (not validated_import and sum(len(row) for row in rows) > sheets.MAX_CELLS)
        or any(len(row) > len(columns) for row in rows)
    ):
        raise ValueError("Append up to 10,000 cells within the existing sheet columns.")
    if any(
        not isinstance(value, str) or len(value) > 50_000
        for row in rows
        for value in row
    ):
        raise ValueError("Each cell must be text with at most 50,000 characters.")
    rows = [row for row in rows if any(value.strip() for value in row)]
    if not rows:
        sheets.compact_blank_rows(conn, tab["id"])
        return
    last = conn.execute(
        "SELECT MAX(r.position) FROM native_rows r JOIN native_cells c ON c.row_id=r.id WHERE r.tab_id=? AND c.value!=''",
        (tab["id"],),
    ).fetchone()[0]
    existing = ordered_rows(conn, tab["id"])
    at_index = (last + 1) if last is not None else 0
    at = existing[at_index] if at_index < len(existing) else None
    ids = insert_rows(conn, tab["id"], len(rows), at, work_date)
    conn.executemany(
        "INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)",
        [
            (ids[r], columns[c][0], value)
            for r, row in enumerate(rows)
            for c, value in enumerate(row)
            if value
        ],
    )

    sheets.compact_blank_rows(conn, tab["id"])


def append(conn, tab, operation, revision, rows, *, work_date="all"):
    sheets.date_scope(work_date)
    payload = {
        "action": "append",
        "revision": revision,
        "rows": rows,
        **({"work_date": work_date} if work_date != "all" else {}),
    }
    with sheets.atomic(conn):
        if not sheets.check_operation(conn, tab["id"], operation, payload):
            check_revision(conn, tab["id"], revision)
            append_cells(conn, tab, rows, work_date=work_date)
            sheets.record_operation(
                conn, tab["id"], operation, payload, structural=True
            )
        return sheets.snapshot(conn, tab)
