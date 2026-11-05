"""Compare dated sourcing rows with saved application confirmations."""
from datetime import date, datetime, timedelta, timezone
import re
import unicodedata
import time
from bisect import bisect_left, bisect_right
from . import payments
from . import native_sourcing as sheets
from .payments import ZONE, sync_receipts
from .sourcing_structure import check_revision


def company_key(value):
    name = unicodedata.normalize("NFKC", value or "").casefold().strip()
    # Dotted initialisms are harmless aliases; meaningful company words are not.
    name = re.sub(r"\b(?:[^\W\d_]\.){2,}", lambda m: m[0].replace(".", ""), name)
    words = re.findall(r"[^\W_]+", name)
    while words and words[-1] in {"inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "plc"}:
        words.pop()
    return " ".join(words)


def role_key(value):
    name = unicodedata.normalize("NFKC", value or "").casefold()
    name = re.sub(r"\s*[|,]\s*(?:remote|hybrid|onsite|on-site)(?:\s*[,(/].*)?\s*$", "", name)
    name = re.sub(r"[^\w+#]+", " ", name).replace("_", " ")
    words = name.split()
    return " ".join({"sr": "senior", "jr": "junior"}.get(word, word) for word in words)


def _matching_plan(conn, rows, receipts, *, early_since):
    """Only bind a receipt to an unambiguous job; never reuse a reserved receipt.

    Index candidates by account/company/role/date instead of comparing each
    receipt with every job. The plan is shared by manual and automatic checks.
    """
    groups = {}
    for row in rows:
        if not row['work_date'] or not (row['link'] or '').strip():
            continue
        company, role = company_key(row['company']), role_key(row['role'])
        if not company:
            continue
        for key in ((row['account_id'], company, role), (row['account_id'], company, None)):
            groups.setdefault(key, {}).setdefault(row['work_date'], []).append(row['id'])
    indexed = {key: (sorted(days), days) for key, days in groups.items()}
    reservations = {}
    receipt_keys = {(r['account_id'],r['message_id']) for r in receipts}
    message_ids = sorted({key[1] for key in receipt_keys})
    # Only inspect reservations for this batch of receipts, not all history.
    for offset in range(0,len(message_ids),800):
        batch = message_ids[offset:offset+800]
        placeholders = ','.join('?' for _ in batch)
        for row in conn.execute("""SELECT e.message_id,r.id,t.account_id FROM sourcing_check_activity e
            JOIN native_rows r ON r.id=e.row_id JOIN native_tabs t ON t.id=r.tab_id
            JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
            JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='check'
            JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id AND c.value='true'
            JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
            JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id AND trim(l.value)!=''
            WHERE e.message_id IN (""" + placeholders + ")", batch):
            key = (row['account_id'],row['message_id'])
            if key in receipt_keys:
                reservations.setdefault(key, set()).add(row['id'])
    today = payments.today().isoformat()
    plan = {}
    for receipt in receipts:
        company = company_key(receipt['company'])
        role = role_key(receipt['role']) if (receipt['role'] or '').strip() else None
        if role == '':
            continue
        indexed_group = indexed.get((receipt['account_id'], company, role))
        if not indexed_group:
            continue
        try:
            stamp = datetime.fromisoformat(receipt['received_at'].replace('Z', '+00:00'))
            stamp = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        day = stamp.astimezone(ZONE).date()
        dates, by_date = indexed_group
        candidates = set()
        for source_day in dates[bisect_left(dates, (day-timedelta(days=6)).isoformat()):bisect_right(dates, day.isoformat())]:
            candidates.update(by_date[source_day])
        if day >= early_since:
            for source_day in dates[bisect_right(dates, max(today, day.isoformat())):]:
                candidates.update(by_date[source_day])
        reserved = reservations.get((receipt['account_id'], receipt['message_id']), set())
        if reserved:
            # Existing bindings win over new candidates, including archived rows.
            if len(reserved) != 1:
                continue
            candidates &= reserved
        if len(candidates) != 1:
            continue
        row_id = next(iter(candidates))
        match = (stamp, receipt['message_id'])
        if row_id not in plan or match < plan[row_id]:
            plan[row_id] = match
    return plan


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
            receipts = list(conn.execute("""SELECT account_id,company,role,received_at,message_id
                FROM application_receipts WHERE account_id=? AND category='application_ack'
                AND ((julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?))
                  OR (julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?)))""",
                (tab['account_id'], lower, upper, early_lower, early_upper)))
            candidates = conn.execute("""SELECT r.id,r.tab_id,r.work_date,t.account_id,
                company.value AS company,role.value AS role,link.value AS link
                FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id
                JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
                JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
                JOIN native_columns rc ON rc.tab_id=t.id AND rc.kind='role'
                JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
                LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=cc.id
                LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=rc.id
                JOIN native_cells link ON link.row_id=r.id AND link.column_id=lc.id AND trim(link.value)!=''
                WHERE t.account_id=? AND (t.archived=0 OR t.id=?) AND r.work_date IS NOT NULL""", (tab['account_id'],tab['id'])).fetchall()
            plan = _matching_plan(conn, candidates, receipts, early_since=current-timedelta(days=6))
            columns = {row["kind"]: row["id"] for row in conn.execute("SELECT id,kind FROM native_columns WHERE tab_id=?", (tab["id"],))}
            if not all(kind in columns for kind in ("company", "role", "link", "check")):
                raise ValueError("The sheet needs Company, Role, Job link and Check columns.")
            for row in conn.execute("""SELECT r.id,r.work_date,company.value AS company,role.value AS role,link.value AS link,
                (SELECT c.value FROM native_cells c WHERE c.row_id=r.id AND c.column_id=?) AS checked
                FROM native_rows r LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=?
                LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=?
                LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=?
                WHERE r.tab_id=? AND (r.work_date=? OR r.work_date>?)""", (columns["check"], columns["company"], columns["link"], columns["role"], tab["id"], day, current.isoformat())).fetchall():
                if not (row["company"] or "").strip() and not (row["link"] or "").strip():
                    continue
                if row['checked'] == 'true':
                    continue
                match = plan.get(row['id'])
                checked = bool(match)
                if match:
                    from .sourcing_activity import confirm
                    confirm(conn,row['id'],*match)
                conn.execute("""INSERT INTO native_cells(row_id,column_id,value) VALUES(?,?,?)
                    ON CONFLICT(row_id,column_id) DO UPDATE SET value=excluded.value,version=native_cells.version+1 WHERE native_cells.value!='true' AND native_cells.value IS NOT excluded.value""",
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
        try:
            received = datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return False
        day = received.replace(tzinfo=received.tzinfo or timezone.utc).astimezone(ZONE).date()
        return refresh_since <= day <= refresh_until
    source_since = refresh_since - timedelta(days=6) if refresh_since else None
    with sheets.atomic(conn):
        sync_receipts(conn, since=refresh_since if week_only else None, until=refresh_until if week_only else None)
        tabs = {row["id"] for row in conn.execute("""SELECT t.id FROM native_tabs t
            JOIN accounts a ON a.id=t.account_id JOIN native_books b ON b.id=t.book_id
            JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL WHERE t.archived=0 OR ?""", (week_only,))}
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
            JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
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
        receipts = list(conn.execute("SELECT account_id,received_at,company,role,message_id FROM application_receipts WHERE category='application_ack' AND company!=''" + receipt_scope, receipt_parameters))
        plan = _matching_plan(conn, rows, receipts, early_since=refresh_since or (payments.today()-timedelta(days=6)))
        changed_tabs = set()
        checked_count = changed_count = 0
        for row in rows:
            # Every checking path fills unchecked rows only. Saved proof/date
            # metadata is accounting history and must never be refreshed here.
            if row['checked'] == 'true':
                checked_count += 1
                continue
            match = plan.get(row['id'])
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
    day_sql, day_params = payments.accounting_day_case('confirmed_at', date.fromisoformat(start), date.fromisoformat(end))
    # Aggregate inside SQLite rather than allocating one Python event object per
    # checked row, then scanning assignments for each object a second time.
    counts = {}
    matched_sql = """WITH completions AS MATERIALIZED (
        SELECT row_id,""" + day_sql + """ AS day FROM sourcing_check_activity
        WHERE julianday(confirmed_at)>=julianday(?) AND julianday(confirmed_at)<julianday(?))
        SELECT b.bidder_id,t.account_id,e.day,COUNT(*) AS n FROM completions e
        JOIN native_rows r ON r.id=e.row_id JOIN native_tabs t ON t.id=r.tab_id
        JOIN native_books b ON b.id=t.book_id JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
        JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='check'
        JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id AND c.value='true'
        JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
        JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id AND trim(l.value)!=''
        WHERE EXISTS (SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=b.bidder_id AND a.account_id=t.account_id
          AND a.start_date<=e.day AND (a.end_date IS NULL OR a.end_date>=e.day))
        GROUP BY b.bidder_id,t.account_id,e.day"""
    for row in conn.execute(matched_sql, (*day_params, lower, upper)):
        counts[row['bidder_id'],row['account_id'],row['day']] = row['n']
    manual_sql = """SELECT b.bidder_id,t.account_id,r.work_date AS day,COUNT(*) AS n
        FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
        JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
        JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='check'
        JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id AND c.value='true'
        JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
        JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id AND trim(l.value)!=''
        LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
        WHERE (e.confirmed_at IS NULL OR julianday(e.confirmed_at) IS NULL) AND r.work_date>=? AND r.work_date<=?
        AND EXISTS (SELECT 1 FROM bidder_assignments a WHERE a.bidder_id=b.bidder_id AND a.account_id=t.account_id
          AND a.start_date<=r.work_date AND (a.end_date IS NULL OR a.end_date>=r.work_date))
        GROUP BY b.bidder_id,t.account_id,r.work_date"""
    for row in conn.execute(manual_sql, (start, end)):
        key = (row['bidder_id'],row['account_id'],row['day'])
        counts[key] = counts.get(key,0)+row['n']
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
