"""Compare dated sourcing rows with saved application confirmations."""
from datetime import date, datetime, timedelta, timezone
import re
import unicodedata
import time
from . import native_sourcing as sheets
from .payments import ZONE, sync_receipts
from .sourcing_structure import check_revision


def company_key(value):
    name = unicodedata.normalize("NFKC", value or "").casefold().strip()
    name = re.sub(r"(?:[\s,]+)(?:incorporated|corporation|limited|inc|corp|llc|ltd)\.?$", "", name)
    return "".join(char for char in name if char.isalnum())


def role_key(value):
    # Keep + and # meaningful so C++, C#, and C roles do not collapse together.
    name = unicodedata.normalize("NFKC", value or "").casefold()
    return " ".join(re.sub(r"[^\w+#]+", " ", name).split())


def match_key(company, role):
    company, role = company_key(company), role_key(role)
    return (company, role) if company and role else None


def verify(conn, tab, operation, revision, work_date):
    day = sheets.date_scope(work_date)
    if day in (None, "all"):
        raise ValueError("Choose a job date before checking applications.")
    if not tab["account_id"]:
        raise ValueError("This sheet needs a connected account before checking applications.")
    selected = date.fromisoformat(day)
    lower = datetime.combine(selected, datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(selected + timedelta(days=7), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    payload = {"action": "verify", "revision": revision, "work_date": day}
    with sheets.atomic(conn):
        if not sheets.check_operation(conn, tab["id"], operation, payload):
            check_revision(conn, tab["id"], revision)
            sync_receipts(conn)
            matches = {match_key(row["company"], row["role"]) for row in conn.execute("""
                SELECT company,role FROM application_receipts WHERE account_id=? AND category='application_ack'
                AND julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?)
                """, (tab["account_id"], lower, upper))}
            matches.discard(None)
            columns = {row["kind"]: row["id"] for row in conn.execute("SELECT id,kind FROM native_columns WHERE tab_id=?", (tab["id"],))}
            if not all(kind in columns for kind in ("company", "role", "link", "check")):
                raise ValueError("The sheet needs Company, Role, Job link and Check columns.")
            for row in conn.execute("""SELECT r.id,company.value AS company,role.value AS role,link.value AS link
                FROM native_rows r LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=?
                LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=?
                LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=?
                WHERE r.tab_id=? AND r.work_date=?""", (columns["company"], columns["link"], columns["role"], tab["id"], day)).fetchall():
                if not (row["company"] or "").strip() and not (row["link"] or "").strip():
                    continue
                checked = bool((row["link"] or "").strip() and match_key(row["company"], row["role"]) in matches)
                conn.execute("""INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)
                    ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value,version=native_cells.version+1 WHERE native_cells.value!='true'""",
                    (row["id"], columns["check"], str(checked).lower()))
            sheets.record_operation(conn, tab["id"], operation, payload)
        result = sheets.snapshot(conn, tab)
        check = next(i for i, col in enumerate(result["columns"]) if col["kind"] == "check")
        result["verification"] = {"day": day, "timezone": ZONE.key,
            "checked": sum(row[check]["value"] == "true" for i,row in enumerate(result["rows"][1:],1) if result["row_dates"][i] == day)}
        return result


def verify_all(conn):
    """Refresh active account sheets against receipts in each row’s seven-day window.

    Read and update under one write transaction so edits cannot move a job between
    comparison and write. Unchanged cells retain their versions and tab revision.
    """
    with sheets.atomic(conn):
        sync_receipts(conn)
        tabs = {row["id"] for row in conn.execute("""SELECT t.id FROM native_tabs t
            JOIN accounts a ON a.id=t.account_id WHERE t.archived=0""")}
        rows = conn.execute("""SELECT r.id,r.tab_id,r.work_date,t.account_id,check_col.id AS check_column,
            company.value AS company,role.value AS role,link.value AS link,checked.value AS checked
            FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id
            JOIN accounts a ON a.id=t.account_id
            JOIN native_columns company_col ON company_col.tab_id=t.id AND company_col.kind='company'
            JOIN native_columns role_col ON role_col.tab_id=t.id AND role_col.kind='role'
            JOIN native_columns link_col ON link_col.tab_id=t.id AND link_col.kind='link'
            JOIN native_columns check_col ON check_col.tab_id=t.id AND check_col.kind='check'
            LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=company_col.id
            LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=role_col.id
            LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=link_col.id
            LEFT JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=check_col.id
            WHERE t.archived=0 AND r.work_date IS NOT NULL
            AND (trim(COALESCE(company.value,''))!='' OR trim(COALESCE(link.value,''))!='')""").fetchall()
        relevant = {(row["account_id"], row["work_date"]) for row in rows}
        matches = {}
        for receipt in conn.execute("SELECT account_id,received_at,company,role FROM application_receipts WHERE category='application_ack' AND company!=''"):
            try:
                received = datetime.fromisoformat(receipt["received_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            received_day = received.replace(tzinfo=received.tzinfo or timezone.utc).astimezone(ZONE).date()
            match = match_key(receipt["company"], receipt["role"])
            for offset in range(7):
                key = (receipt["account_id"], (received_day - timedelta(days=offset)).isoformat())
                if key in relevant and match:
                    matches.setdefault(key, set()).add(match)
        changed_tabs = set()
        checked_count = changed_count = 0
        for row in rows:
            checked = row["checked"] == "true" or bool((row["link"] or "").strip() and match_key(row["company"], row["role"]) in matches.get((row["account_id"], row["work_date"]), set()))
            checked_count += int(checked)
            value = str(checked).lower()
            if row["checked"] == value:
                continue
            conn.execute("""INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)
                ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value,version=native_cells.version+1""",
                (row["id"], row["check_column"], value))
            changed_tabs.add(row["tab_id"])
            changed_count += 1
        conn.executemany("UPDATE native_tabs SET revision=revision+1,updated_at=? WHERE id=?",
            [(time.time(), tab_id) for tab_id in changed_tabs])
        return {"tabs": len(tabs), "rows": len(rows), "checked": checked_count, "changed": changed_count}


def checked_counts(conn, start, end):
    """Count job links once per saved row, attributed to its dated account assignment."""
    return {(row["bidder_id"], row["work_date"]): row["count"] for row in conn.execute("""
        SELECT b.bidder_id,r.work_date,COUNT(*) AS count FROM native_rows r
        JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
        JOIN native_columns check_col ON check_col.tab_id=t.id AND check_col.kind='check'
        JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=check_col.id AND checked.value='true'
        JOIN native_columns link_col ON link_col.tab_id=t.id AND link_col.kind='link'
        JOIN native_cells link ON link.row_id=r.id AND link.column_id=link_col.id AND trim(link.value)!=''
        WHERE r.work_date>=? AND r.work_date<=? AND EXISTS (
            SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=b.bidder_id AND a.account_id=t.account_id
            AND a.start_date<=r.work_date AND (a.end_date IS NULL OR a.end_date>=r.work_date))
        GROUP BY b.bidder_id,r.work_date""", (start, end))}
