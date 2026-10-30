"""Compare dated sourcing rows with saved application confirmations."""
from datetime import date, datetime, timedelta, timezone
import re
import unicodedata
import time
from bisect import bisect_right
from . import payments
from . import native_sourcing as sheets
from .payments import ZONE, sync_receipts
from .sourcing_structure import check_revision


def company_key(value):
    name = unicodedata.normalize("NFKC", value or "").casefold().strip()
    first_word = re.match(r"[a-z0-9]+", name)
    return first_word.group() if first_word else ""


def role_key(value):
    name = " ".join(unicodedata.normalize("NFKC", value or "").casefold().split())
    name = re.split(r"[^a-z ]", name, maxsplit=1)[0]
    return re.sub(r"[^a-z]", "", name)


def match_key(company, role):
    role_present = bool((role or "").strip())
    company, role = company_key(company), role_key(role)
    return (company, role) if company and (role or not role_present) else None


def receipt_match(company, role, matches):
    options = [matches[key] for key in (match_key(company, role), (company_key(company), "")) if key in matches]
    return min(options) if options else None


def add_receipt(matches, receipt):
    key = match_key(receipt['company'],receipt['role'])
    if not key: return
    try:
        received = datetime.fromisoformat(receipt['received_at'].replace('Z','+00:00'))
        received = received.replace(tzinfo=received.tzinfo or timezone.utc).astimezone(timezone.utc)
    except (ValueError,TypeError): return
    value = (received,receipt['message_id'])
    if key not in matches or value < matches[key]: matches[key] = value


def verify(conn, tab, operation, revision, work_date):
    day = sheets.date_scope(work_date)
    if day in (None, "all"):
        raise ValueError("Choose a job date before checking applications.")
    if not tab["account_id"]:
        raise ValueError("This sheet needs a connected account before checking applications.")
    selected = date.fromisoformat(day)
    current = payments.today()
    early_lower = datetime.combine(current - timedelta(days=6), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    early_upper = datetime.combine(current + timedelta(days=1), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    lower = datetime.combine(selected, datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(selected + timedelta(days=7), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    payload = {"action": "verify", "revision": revision, "work_date": day}
    with sheets.atomic(conn):
        if not sheets.check_operation(conn, tab["id"], operation, payload):
            check_revision(conn, tab["id"], revision)
            sync_receipts(conn)
            matches = {}
            for receipt in conn.execute("""SELECT company,role,received_at,message_id FROM application_receipts WHERE account_id=? AND category='application_ack'
                AND julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?)""",(tab['account_id'],lower,upper)):
                add_receipt(matches,receipt)
            early_matches = {}
            for receipt in conn.execute("""SELECT company,role,received_at,message_id FROM application_receipts
                WHERE account_id=? AND category='application_ack' AND julianday(received_at)>=julianday(?)
                AND julianday(received_at)<julianday(?)""", (tab['account_id'],early_lower,early_upper)):
                add_receipt(early_matches,receipt)
            columns = {row["kind"]: row["id"] for row in conn.execute("SELECT id,kind FROM native_columns WHERE tab_id=?", (tab["id"],))}
            if not all(kind in columns for kind in ("company", "role", "link", "check")):
                raise ValueError("The sheet needs Company, Role, Job link and Check columns.")
            for row in conn.execute("""SELECT r.id,r.work_date,company.value AS company,role.value AS role,link.value AS link
                FROM native_rows r LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=?
                LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=?
                LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=?
                WHERE r.tab_id=? AND (r.work_date=? OR r.work_date>?)""", (columns["company"], columns["link"], columns["role"], tab["id"], day, current.isoformat())).fetchall():
                if not (row["company"] or "").strip() and not (row["link"] or "").strip():
                    continue
                candidates = []
                if (row['link'] or '').strip():
                    if row['work_date'] == day:
                        candidates.append(receipt_match(row['company'],row['role'],matches))
                    if row['work_date'] > current.isoformat():
                        candidates.append(receipt_match(row['company'],row['role'],early_matches))
                match = min((match for match in candidates if match),default=None)
                checked = bool(match)
                if match:
                    from .sourcing_activity import confirm
                    confirm(conn,row['id'],*match)
                conn.execute("""INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)
                    ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value,version=native_cells.version+1 WHERE native_cells.value!='true'""",
                    (row["id"], columns["check"], str(checked).lower()))
            from .sourcing_activity import record
            record(conn, "tab-check", sample=True)
            sheets.record_operation(conn, tab["id"], operation, payload)
        result = sheets.snapshot(conn, tab)
        check = next(i for i, col in enumerate(result["columns"]) if col["kind"] == "check")
        result["verification"] = {"day": day, "timezone": ZONE.key,
            "checked": sum(row[check]["value"] == "true" for i,row in enumerate(result["rows"][1:],1) if result["row_dates"][i] == day),
            "future_checked": sum(row[check]["value"] == "true" for i,row in enumerate(result["rows"][1:],1)
                if result["row_dates"][i] and result["row_dates"][i] > current.isoformat() and result["row_dates"][i] != day)}
        return result


def verify_all(conn, *, refresh_since=None, refresh_until=None, sample=True, week_only=False, rebuild=False):
    """Refresh active account sheets against receipts in each row’s seven-day window.

    A bounded refresh includes links from six days before its receipt window and all later pre-registered dates. Recent receipts can match early work on future rows.
    Keep earlier receipts too so reconciliation never shifts an existing match
    to a later duplicate email. Passive report reads do not create check runs.

    Read and update under one write transaction so edits cannot move a job between
    comparison and write. Unchanged cells retain their versions and tab revision.
    """
    if (week_only or rebuild) and (not refresh_since or not refresh_until):
        raise ValueError("A week is required for a scoped refresh.")
    def in_week(stamp):
        if not stamp:
            return False
        received = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        day = received.replace(tzinfo=received.tzinfo or timezone.utc).astimezone(ZONE).date()
        return refresh_since <= day <= refresh_until
    source_since = refresh_since - timedelta(days=6) if refresh_since else None
    with sheets.atomic(conn):
        sync_receipts(conn, since=refresh_since if week_only else None, until=refresh_until if week_only else None)
        tabs = {row["id"] for row in conn.execute("""SELECT t.id FROM native_tabs t
            JOIN accounts a ON a.id=t.account_id WHERE t.archived=0 OR ?""", (week_only,))}
        row_prefix = ""
        row_source = "native_rows"
        row_parameters = []
        receipt_scope = ""
        receipt_parameters = []
        if refresh_since:
            lower = datetime.combine(source_since, datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
            upper = datetime.combine(refresh_until + timedelta(days=1), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
            row_scope = "(r.work_date>=?"
            row_parameters.append(source_since.isoformat())
            if week_only:
                event_lower = datetime.combine(refresh_since, datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
                row_scope += " OR (julianday(e.confirmed_at)>=julianday(?) AND julianday(e.confirmed_at)<julianday(?)) OR (e.confirmed_at IS NOT NULL AND julianday(e.confirmed_at) IS NULL)"
                row_parameters.extend((event_lower, upper))
            row_scope += ")"
            # Materialize the small date candidate set before touching the four
            # cell columns. Otherwise SQLite can join every historical cell
            # before applying the OR on a stale confirmation's timestamp.
            row_prefix = "WITH candidate_rows AS MATERIALIZED (SELECT r.* FROM native_rows r LEFT JOIN sourcing_check_activity e ON e.row_id=r.id WHERE " + row_scope + ") "
            row_source = "candidate_rows"
            # Keep Python's existing parser authoritative for unusual legacy
            # timestamps that SQLite cannot parse. Standard receipts use the
            # existing category/date index; no new index or schema is needed.
            receipt_scope = " AND ((julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?)) OR julianday(received_at) IS NULL)"
            receipt_parameters.extend((lower, upper))
        row_parameters.extend((week_only, week_only))
        rows = conn.execute(row_prefix + """SELECT r.id,r.tab_id,r.work_date,t.account_id,check_col.id AS check_column,
            company.value AS company,role.value AS role,link.value AS link,checked.value AS checked,
            e.confirmed_at,e.source AS check_source
            FROM """ + row_source + """ r JOIN native_tabs t ON t.id=r.tab_id
            JOIN accounts a ON a.id=t.account_id
            JOIN native_columns company_col ON company_col.tab_id=t.id AND company_col.kind='company'
            JOIN native_columns role_col ON role_col.tab_id=t.id AND role_col.kind='role'
            JOIN native_columns link_col ON link_col.tab_id=t.id AND link_col.kind='link'
            JOIN native_columns check_col ON check_col.tab_id=t.id AND check_col.kind='check'
            LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=company_col.id
            LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=role_col.id
            LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=link_col.id
            LEFT JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=check_col.id
            LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
            WHERE (t.archived=0 OR ?) AND (r.work_date IS NOT NULL OR (? AND e.confirmed_at IS NOT NULL))
            AND (trim(COALESCE(company.value,''))!='' OR trim(COALESCE(link.value,''))!='' OR e.confirmed_at IS NOT NULL)""", row_parameters).fetchall()
        if refresh_since:
            rows = [r for r in rows if (r["work_date"] and source_since.isoformat() <= r["work_date"])
                    or (week_only and in_week(r["confirmed_at"]))]
        relevant = {(row["account_id"], row["work_date"]) for row in rows}
        matches = {}
        future_dates = {}
        for account, work_date in relevant:
            if work_date:future_dates.setdefault(account,[]).append(work_date)
        for dates in future_dates.values():dates.sort()
        early_since = refresh_since or (payments.today() - timedelta(days=6))
        for receipt in conn.execute("SELECT account_id,received_at,company,role,message_id FROM application_receipts WHERE category='application_ack' AND company!=''" + receipt_scope, receipt_parameters):
            try:
                received = datetime.fromisoformat(receipt["received_at"].replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            received_day = received.replace(tzinfo=received.tzinfo or timezone.utc).astimezone(ZONE).date()
            if refresh_since and (received_day < source_since or received_day > refresh_until): continue
            match = match_key(receipt["company"], receipt["role"])
            for offset in range(7):
                key = (receipt["account_id"], (received_day - timedelta(days=offset)).isoformat())
                if key in relevant and match:
                    add_receipt(matches.setdefault(key, {}),receipt)
            # A scheduled sourcing date is not a lower bound on actual completion.
            # Recent receipts may belong to any pre-registered future date.
            if received_day >= early_since and match:
                dates = future_dates.get(receipt['account_id'],[])
                for future_day in dates[bisect_right(dates,received_day.isoformat()):]:
                    add_receipt(matches.setdefault((receipt['account_id'],future_day),{}),receipt)
        changed_tabs = set()
        checked_count = changed_count = 0
        for row in rows:
            match = receipt_match(row['company'],row['role'],matches.get((row['account_id'],row['work_date']),{})) if (row['link'] or '').strip() else None
            if week_only:
                # Source dates can precede the receipt week. Never rewrite a
                # completion already attributed to another accounting week.
                if row['confirmed_at'] and not in_week(row['confirmed_at']):
                    continue
                sourced_in_week = bool(row['work_date'] and
                    refresh_since.isoformat() <= row['work_date'] <= refresh_until.isoformat())
                if row['checked'] == 'true' and not row['confirmed_at'] and not sourced_in_week:
                    continue
                if match and not in_week(match[0]):
                    match = None
                if not match and not in_week(row['confirmed_at']) and not sourced_in_week:
                    continue
            checked = row['checked'] == 'true' or bool(match)
            if rebuild and not match and row['check_source'] == 'confirmation' and in_week(row['confirmed_at']):
                checked = False
                conn.execute("UPDATE sourcing_check_activity SET confirmed_at=NULL,message_id=NULL,source='rebuild-cleared' WHERE row_id=?", (row['id'],))
            if match:
                from .sourcing_activity import confirm
                confirm(conn,row['id'],*match)
                if row['confirmed_at'] != match[0].isoformat():
                    changed_tabs.add(row['tab_id'])
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
        from .sourcing_activity import record
        if sample:
            record(conn, "global-check", sample=True)
        return {"tabs": len(tabs), "rows": len(rows), "checked": checked_count, "changed": changed_count}


def checked_account_counts(conn, start, end):
    """Count job links once per saved row, attributed to its dated account assignment."""
    return {(row["bidder_id"], row["account_id"], row["work_date"]): row["count"] for row in conn.execute("""
        SELECT b.bidder_id,t.account_id,r.work_date,COUNT(*) AS count FROM native_rows r
        JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
        JOIN native_columns check_col ON check_col.tab_id=t.id AND check_col.kind='check'
        JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=check_col.id AND checked.value='true'
        JOIN native_columns link_col ON link_col.tab_id=t.id AND link_col.kind='link'
        JOIN native_cells link ON link.row_id=r.id AND link.column_id=link_col.id AND trim(link.value)!=''
        WHERE r.work_date>=? AND r.work_date<=? AND EXISTS (
            SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=b.bidder_id AND a.account_id=t.account_id
            AND a.start_date<=r.work_date AND (a.end_date IS NULL OR a.end_date>=r.work_date))
        GROUP BY b.bidder_id,t.account_id,r.work_date""", (start, end))}


def checked_counts(conn, start, end):
    counts = {}
    for (bidder_id, _account_id, day), count in checked_account_counts(conn, start, end).items():
        counts[bidder_id, day] = counts.get((bidder_id, day), 0) + count
    return counts


def completed_account_counts(conn, start, end):
    """Count checked links on their confirmation's Chicago day, across source dates.

    Manual/legacy checks without a known receipt time keep their sourcing date.
    The same completion-day weights feed both payment totals and receipt estimates.
    """
    lower = datetime.combine(date.fromisoformat(start),datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(date.fromisoformat(end)+timedelta(days=1),datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    assignments = {}
    for assignment in conn.execute('SELECT bidder_id,account_id,start_date,end_date FROM bidder_assignments'):
        assignments.setdefault((assignment['bidder_id'],assignment['account_id']),[]).append((assignment['start_date'],assignment['end_date']))
    counts = {}
    for event in confirmation_events(conn,lower,upper):
        key = (event['bidder_id'],event['account_id'],event['completion_day'])
        counts[key] = counts.get(key,0)+1
    for row in conn.execute("""SELECT b.bidder_id,t.account_id,r.work_date,e.confirmed_at
        FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
        JOIN native_columns col ON col.tab_id=t.id AND col.kind='check'
        JOIN native_cells c ON c.row_id=r.id AND c.column_id=col.id AND c.value='true'
        JOIN native_columns link ON link.tab_id=t.id AND link.kind='link'
        JOIN native_cells l ON l.row_id=r.id AND l.column_id=link.id AND trim(l.value)!=''
        LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
        WHERE e.confirmed_at IS NULL AND r.work_date>=? AND r.work_date<=?""",(start,end)):
        day = row['work_date']
        if not day or not any(first<=day and (last is None or last>=day)
                              for first,last in assignments.get((row['bidder_id'],row['account_id']),[])):
            continue
        key = (row['bidder_id'],row['account_id'],day)
        counts[key] = counts.get(key,0)+1
    return counts


def confirmation_events(conn, lower, upper, bidder_id=None):
    """The shared source of matched completions for payments and activity graphs."""
    assignments = {}
    for a in conn.execute('SELECT bidder_id,account_id,start_date,end_date FROM bidder_assignments'):
        assignments.setdefault((a['bidder_id'],a['account_id']),[]).append((a['start_date'],a['end_date']))
    events = []
    for row in conn.execute("""SELECT r.id AS row_id,b.bidder_id,t.account_id,r.work_date,
        e.confirmed_at,e.confirmed_at AS activity_at,e.message_id,e.detected_at,e.source
        FROM sourcing_check_activity e JOIN native_rows r ON r.id=e.row_id
        JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
        JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
        JOIN native_columns col ON col.tab_id=t.id AND col.kind='check'
        JOIN native_cells c ON c.row_id=r.id AND c.column_id=col.id AND c.value='true'
        JOIN native_columns link ON link.tab_id=t.id AND link.kind='link'
        JOIN native_cells l ON l.row_id=r.id AND l.column_id=link.id AND trim(l.value)!=''
        WHERE julianday(e.confirmed_at)>=julianday(?) AND julianday(e.confirmed_at)<julianday(?)
        AND (? IS NULL OR b.bidder_id=?) ORDER BY julianday(e.confirmed_at),r.id""",(lower,upper,bidder_id,bidder_id)):
        event = dict(row)
        received = datetime.fromisoformat(event['confirmed_at'].replace('Z','+00:00'))
        received = received.replace(tzinfo=received.tzinfo or timezone.utc).astimezone(timezone.utc)
        day = received.astimezone(ZONE).date().isoformat()
        if any(first<=day and (last is None or last>=day)
               for first,last in assignments.get((event['bidder_id'],event['account_id']),[])):
            event['completion_day'] = day
            event['confirmed_at'] = event['activity_at'] = received.isoformat()
            events.append(event)
    return events
