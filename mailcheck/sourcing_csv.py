"""Validated, atomic CSV interchange for native job sheets."""

import csv
import io
import re
from . import native_sourcing as sheets
from .sourcing_structure import append_cells, check_revision


def parse(text):
    if not text.strip() or len(text) > 2_000_000:
        raise ValueError("Choose a nonempty CSV file up to 2 MB.")
    try:
        rows = list(csv.reader(io.StringIO(text.lstrip("\ufeff")), strict=True))
    except csv.Error as exc:
        raise ValueError(
            "This CSV contains invalid quoting. Export it again or paste the cells."
        ) from exc
    if (
        not rows
        or len(rows) > 10_001
        or sum(len(r) for r in rows) > sheets.MAX_CELLS
        or any(len(r) > sheets.MAX_COLUMNS for r in rows)
    ):
        raise ValueError("Import up to 10,000 cells and 101 columns at a time.")
    if any(len(value) > 50_000 for row in rows for value in row):
        raise ValueError("A cell can contain up to 50,000 characters.")
    return rows


def import_rows(
    conn,
    tab,
    operation,
    revision,
    *,
    text,
    mode="append",
    has_header=True,
    work_date="all",
):
    scope = sheets.date_scope(work_date)
    rows = parse(text)
    headers = rows[0] if has_header else []
    data = rows[1:] if has_header else rows
    if not data or mode not in ("append", "replace"):
        raise ValueError("Choose append or replace and include at least one data row.")
    payload = {
        "action": "import",
        "revision": revision,
        "text": text,
        "mode": mode,
        "has_header": has_header,
        **({"work_date": work_date} if work_date != "all" else {}),
    }
    with sheets.atomic(conn):
        if not sheets.check_operation(conn, tab["id"], operation, payload):
            check_revision(conn, tab["id"], revision)
            columns = conn.execute(
                "SELECT * FROM native_columns WHERE tab_id=? ORDER BY position,id",
                (tab["id"],),
            ).fetchall()
            normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.casefold())
            aliases = {
                "company": ("company", "companyname", "employer"),
                "role": ("role", "jobtitle", "jobrole", "position"),
                "link": (
                    "joblink",
                    "joburl",
                    "url",
                    "link",
                    "applicationlink",
                    "applicationurl",
                ),
            }
            targets = []
            if headers:
                for header in headers:
                    key = normalize(header)
                    matches = [
                        i
                        for i, c in enumerate(columns)
                        if key and normalize(c["title"]) == key
                    ]
                    if len(matches) > 1:
                        raise ValueError(
                            "This CSV header matches multiple columns. Rename the columns before importing."
                        )
                    target = (
                        matches[0]
                        if matches
                        else next(
                            (
                                i
                                for i, c in enumerate(columns)
                                if key in aliases.get(c["kind"], ())
                            ),
                            None,
                        )
                    )
                    if target is None:
                        if len(columns) >= sheets.MAX_COLUMNS:
                            raise ValueError(
                                "This import would exceed 101 sheet columns."
                            )
                        target = len(columns)
                        title = header.strip()[:100] or f"Column {target+1}"
                        column = {"id": sheets.new_id(), "title": title, "kind": None}
                        conn.execute(
                            "INSERT INTO native_columns(id,tab_id,position,title) VALUES(?,?,?,?)",
                            (column["id"], tab["id"], target, title),
                        )
                        columns.append(column)
                    if target in targets:
                        raise ValueError(
                            "Two CSV headers target the same column. Use unique headers before importing."
                        )
                    targets.append(target)
                mapped = []
                for row in data:
                    if len(row) > len(headers):
                        raise ValueError("A data row extends beyond the CSV header.")
                    values = [""] * (max(targets) + 1)
                    for i, value in enumerate(row):
                        values[targets[i]] = value
                    mapped.append(values)
                data = mapped
            else:
                width = max(len(r) for r in data)
                for number in range(len(columns), width):
                    conn.execute(
                        "INSERT INTO native_columns(id,tab_id,position,title) VALUES(?,?,?,?)",
                        (sheets.new_id(), tab["id"], number, f"Column {number+1}"),
                    )
            if mode == "replace":
                if scope == "all":
                    conn.execute("DELETE FROM native_rows WHERE tab_id=?", (tab["id"],))
                else:
                    conn.execute(
                        "DELETE FROM native_rows WHERE tab_id=? AND work_date IS ?",
                        (tab["id"], scope),
                    )
                from .sourcing_structure import reorder, ordered_rows

                reorder(conn, ordered_rows(conn, tab["id"]))
            filtered=append_cells(conn, tab, data, validated_import=True, work_date=work_date)
            sheets.record_operation(
                conn, tab["id"], operation, payload, structural=True, filtered=filtered
            )
        from .sourcing_filters import result
        return result(conn,tab,operation)


MAX_EXPORT_BYTES = 32 * 1024 * 1024


def export_rows(conn, tab, *, work_date="all"):
    scope = sheets.date_scope(work_date)
    own_transaction = not conn.in_transaction
    if own_transaction:
        conn.execute("BEGIN")
    try:
        return _export_rows(conn, tab, scope)
    finally:
        if own_transaction:
            conn.rollback()


def _export_rows(conn, tab, scope):
    columns = [dict(c) for c in conn.execute(
        "SELECT id,title,kind FROM native_columns WHERE tab_id=? ORDER BY position,id", (tab['id'],))]
    fixed = {'company':'Company','role':'Role','link':'Job link','check':'Check'}
    titles = [fixed.get(c['kind'], c['title']) for c in columns]
    indexes = {c['id']: i for i, c in enumerate(columns)}
    params = (tab['id'], scope == 'all', scope)
    where = "r.tab_id=? AND (? OR r.work_date IS ?)"
    count = conn.execute("SELECT COUNT(*) FROM native_rows r WHERE " + where, params).fetchone()[0]
    stats = conn.execute("""SELECT COALESCE(SUM(length(CAST(c.value AS BLOB))),0), COUNT(*)
        FROM native_rows r JOIN native_cells c ON c.row_id=r.id
        JOIN native_columns col ON col.id=c.column_id AND col.tab_id=r.tab_id
        WHERE """ + where + " AND c.value!=''", params).fetchone()
    # Twice the UTF-8 text covers quote escaping; allow quotes, formula guards,
    # delimiters and CRLF as well, before allocating the output buffer.
    estimated = (2 * (stats[0] + sum(len(t.encode('utf-8')) for t in titles))
                 + 3 * (stats[1] + len(titles)) + (count + 1) * (len(columns) + 2))
    if estimated > MAX_EXPORT_BYTES:
        raise sheets.SnapshotTooLarge("This CSV export is too large to prepare safely. Export one work date at a time or split the sheet.")
    last = conn.execute("""SELECT r.position,r.id FROM native_rows r WHERE """ + where + """
        AND EXISTS(SELECT 1 FROM native_cells c JOIN native_columns col ON col.id=c.column_id
          WHERE c.row_id=r.id AND col.tab_id=r.tab_id AND c.value!='')
        ORDER BY r.position DESC,r.id DESC LIMIT 1""", params).fetchone()
    output = io.StringIO(newline='')
    writer = csv.writer(output)

    def write(values):
        writer.writerow([("'" + value) if value.lstrip().startswith(('=', '+', '-', '@')) else value for value in values])

    write(titles)
    if last is None:
        return output.getvalue()
    cursor = conn.execute("""SELECT r.id,c.column_id,c.value FROM native_rows r
        LEFT JOIN native_cells c ON c.row_id=r.id
        AND c.column_id IN (SELECT id FROM native_columns WHERE tab_id=r.tab_id)
        WHERE """ + where + " AND (r.position,r.id)<=(?,?) ORDER BY r.position,r.id", (*params, last[0], last[1]))
    current = None
    values = None
    for row in cursor:
        if row['id'] != current:
            if values is not None:
                write(values)
            current = row['id']
            values = [''] * len(columns)
        if row['column_id'] in indexes:
            values[indexes[row['column_id']]] = row['value']
    if values is not None:
        write(values)
    return output.getvalue()
