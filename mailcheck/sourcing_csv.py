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
            append_cells(conn, tab, data, validated_import=True, work_date=work_date)
            sheets.record_operation(
                conn, tab["id"], operation, payload, structural=True
            )
        return sheets.snapshot(conn, tab)


def export_rows(conn, tab, *, work_date="all"):
    scope = sheets.date_scope(work_date)
    result = sheets.snapshot(conn, tab)
    rows = [
        row
        for i, row in enumerate(result["rows"])
        if i == 0 or scope == "all" or result["row_dates"][i] == scope
    ]
    while len(rows) > 1 and not any(cell["value"] for cell in rows[-1]):
        rows.pop()
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for row in rows:
        # Keep spreadsheet applications from executing user-entered text on open.
        writer.writerow(
            [
                (
                    ("'" + str(cell["value"]))
                    if str(cell["value"]).lstrip().startswith(("=", "+", "-", "@"))
                    else cell["value"]
                )
                for cell in row
            ]
        )
    return output.getvalue()
