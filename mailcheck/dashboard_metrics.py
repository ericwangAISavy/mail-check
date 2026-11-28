"""Operational dashboard metrics — the single, read-only calculation layer behind
``/api/dashboard/metrics``. Definitions, formulas and limitations live in docs/METRICS.md;
keep the two in step. Nothing here writes to the database or estimates missing data:
a value that cannot be derived from stored records is returned as ``None``."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from . import calendar_colors, profile_outcomes
from .native_sourcing import LIFETIME_SECONDS, WARNING_SECONDS
from .payments import ZONE
from .sourcing_verification import completed_account_counts

#: Follow-up window an application cohort needs before its outcome rates are reported.
COHORT_DAYS = 14
#: Selectable graph ranges, in reporting weeks.
RANGES = (4, 8, 12)
DEFAULT_WEEKS = 8
#: Completed weeks averaged for the weekly summaries.
AVERAGE_WEEKS = 4
#: Share of outcome emails that must match exactly one application before outcome rates are shown.
MATCH_GATE = 0.8
#: Checked links still without a matching confirmation after this long need attention.
CONFIRMATION_GRACE = timedelta(hours=24)
#: How far back unconfirmed checks and unclassified mail are reported.
ATTENTION_DAYS = 30


# ---------------------------------------------------------------- periods

def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def bound(day: date) -> datetime:
    """UTC instant of a Chicago midnight (DST-safe)."""
    return datetime.combine(day, datetime.min.time(), ZONE).astimezone(timezone.utc)


def local_day(stamp: datetime) -> date:
    return stamp.astimezone(ZONE).date()


def week_before(instant: datetime) -> datetime:
    """The same Chicago wall-clock time one week earlier."""
    local = instant.astimezone(ZONE)
    return datetime.combine(local.date() - timedelta(days=7), local.time(), ZONE).astimezone(timezone.utc)


def graph_range(today: date, weeks: int | None = None, start: date | None = None, end: date | None = None) -> tuple[date, date]:
    """First Monday and last Sunday of the graph range (a preset number of weeks, or custom dates)."""
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("A custom range needs a start and an end date.")
        if start > end:
            raise ValueError("The range start must be on or before its end.")
        if (end - start).days > 366:
            raise ValueError("Choose a range of at most one year.")
        if start > today:
            raise ValueError("The range cannot start in the future.")
        return monday(start), min(monday(end), monday(today)) + timedelta(days=6)
    weeks = weeks or DEFAULT_WEEKS
    if weeks not in RANGES:
        raise ValueError("Choose 4, 8 or 12 weeks.")
    return monday(today) - timedelta(days=7 * (weeks - 1)), monday(today) + timedelta(days=6)


def _weeks(start: date, end: date) -> list[date]:
    out, week = [], monday(start)
    while week <= end:
        out.append(week)
        week += timedelta(days=7)
    return out


# ---------------------------------------------------------------- formulas

def rate(hits: int, base: int) -> float | None:
    """A share of a base; None (N/A) when there is no base."""
    return hits / base if base else None


def change(current: float | int | None, prior: float | int | None) -> dict | None:
    """Absolute change plus percentage change; the percentage is None when the previous
    value is zero (an undefined percentage is never shown)."""
    if current is None or prior is None:
        return None
    return {"absolute": current - prior, "percent": round((current - prior) / prior * 100, 1) if prior else None}


def _parse(value) -> datetime | None:
    from .confirmation_counts import receipt_stamp
    return receipt_stamp(value) if value else None


# ---------------------------------------------------------------- outcomes

def reply_history_start(conn) -> datetime | None:
    """Interview and rejection emails are recorded only from this instant on, so outcome
    rates and rejection counts are unavailable before it."""
    value = conn.execute(
        "SELECT MIN(j) FROM (SELECT julianday(COALESCE(date_utc, fetched_at)) AS j FROM messages "
        "UNION ALL SELECT julianday(received_at) FROM application_receipts WHERE category IN ('interview_invite','rejection'))"
    ).fetchone()[0]
    if value is None:
        return None
    return _parse(conn.execute("SELECT strftime('%Y-%m-%dT%H:%M:%S+00:00', ?)", (value,)).fetchone()[0])


def calendar_interviews(conn, labels: dict, aids, in_scope) -> list[tuple[int, datetime, int]]:
    """(account, start instant, event id) for each interview on the Interview calendar:
    the calendar's own event list (removed, hidden and duplicate copies excluded, enabled
    accounts only) without cancelled events. A shared interview appears for each of its
    profiles but is counted once in totals. Upcoming interviews are included."""
    from . import interviews
    out = []
    for aid in aids:
        label = labels.get(aid)
        if label is None:
            continue
        for event in interviews.list_events(conn, account=label):
            stamp = _parse(event.get("start_at"))
            if event["status"] == "Cancelled" or stamp is None:
                continue
            if in_scope(aid, local_day(stamp).isoformat()):
                out.append((aid, stamp, event["id"]))
    return out


def _unique_rejections(matched: dict) -> list[tuple[int, datetime]]:
    """(account, instant) of unique rejections: the first rejection matched to an
    application, plus unmatched rejection emails de-duplicated by company, role and job
    reference (emails naming no company cannot be de-duplicated and count individually)."""
    in_scope = matched["in_scope"]
    out = [(g["account_id"], g["outcomes"]["rejection"]) for g in matched["groups"] if g["outcomes"]["rejection"]]
    seen = set()
    for aid, metric, stamp, key in sorted(matched["unmatched"], key=lambda item: item[2]):
        if metric != "rejection":
            continue
        if key[0] and key[0] not in {"unknown", "unknown company", "other", "not provided"}:
            if (aid, key) in seen:
                continue
            seen.add((aid, key))
        out.append((aid, stamp))
    return [(aid, stamp) for aid, stamp in out if in_scope(aid, local_day(stamp).isoformat())]


def outcome_data(conn, now: datetime, *, account=None, bidder=None) -> dict:
    matched = profile_outcomes.match(conn, as_of=now, account=account, bidder=bidder)
    in_scope = matched["in_scope"]
    labels = matched["labels"]
    assigned = {r["account_id"] for r in matched["assignments"]}
    scope_ids = sorted((aid for aid, label in labels.items()
                        if (not account or label == account) and (bidder is None or aid in assigned)),
                       key=lambda aid: labels[aid].casefold())
    applications = [(g["account_id"], g["stamp"], date.fromisoformat(g["day"]), g)
                    for g in matched["groups"] if g["account_id"] in scope_ids and in_scope(g["account_id"], g["day"])]
    replies = reply_history_start(conn)

    def counted(aid, stamp):
        return aid in scope_ids and in_scope(aid, local_day(stamp).isoformat()) and (replies is None or stamp >= replies)

    # How reliably outcome emails can be attributed to one application.
    coverage = {}
    for metric, category in (("interview", "interview_invite"), ("rejection", "rejection")):
        received = 0
        for row in conn.execute("SELECT account_id, received_at FROM application_receipts WHERE category=? "
                                "AND julianday(received_at)<=julianday(?)", (category, now.isoformat())):
            stamp = _parse(row["received_at"])
            received += int(bool(stamp and counted(row["account_id"], stamp)))
        unmatched = sum(1 for aid, kind, stamp, _ in matched["unmatched"] if kind == metric and counted(aid, stamp))
        found = max(0, received - unmatched)
        coverage[metric] = {"emails": received, "matched": found, "share": rate(found, received)}
    return {"labels": labels, "scope_ids": scope_ids, "applications": applications,
            "rejections": _unique_rejections(matched), "reply_start": replies, "coverage": coverage,
            "interviews": calendar_interviews(conn, labels, scope_ids, in_scope)}


# ---------------------------------------------------------------- weekly summaries

def summaries(data: dict, now: datetime, trend_weeks: int = DEFAULT_WEEKS) -> dict:
    today = local_day(now)
    week = monday(today)
    prior = week - timedelta(days=7)
    elapsed = week_before(now)
    first_application = min((day for _, _, day, _ in data["applications"]), default=None)
    first_interview = min((local_day(stamp) for _, stamp, _ in data["interviews"]), default=None)
    history = {"applications": first_application,
               "interviews": min(filter(None, (first_application, first_interview)), default=None)}

    def applications(first: date, until: datetime | None = None) -> int:
        return sum(1 for _, stamp, day, _ in data["applications"]
                   if first <= day <= first + timedelta(days=6) and (until is None or stamp <= until))

    def meetings(first: date, until: datetime | None = None) -> int:
        return len({event for _, stamp, event in data["interviews"]
                    if first <= local_day(stamp) <= first + timedelta(days=6) and (until is None or stamp <= until)})

    def known(first: date, kind: str) -> bool:
        # A week is comparable only when records already existed on its Monday.
        return history[kind] is not None and history[kind] <= first

    def build(counter, kind: str) -> dict:
        completed = [week - timedelta(days=7 * i) for i in range(1, AVERAGE_WEEKS + 1)]
        usable = [w for w in completed if known(w, kind)]
        trend = []
        for i in range(trend_weeks - 1, -1, -1):
            w = week - timedelta(days=7 * i)
            trend.append({"week": w.isoformat(), "value": counter(w) if w == week or known(w, kind) else None, "partial": w == week})
        return {"previous_full": counter(prior) if known(prior, kind) else None,
                "average": sum(counter(w) for w in usable) / len(usable) if usable else None,
                "average_weeks": len(usable), "trend": trend}

    app = build(applications, "applications")
    current = applications(week, now)
    comparable = applications(prior, elapsed) if known(prior, "applications") else None
    app.update(current=current, previous_comparable=comparable, change=change(current, comparable))

    calendar = build(meetings, "interviews")
    scheduled = meetings(week)
    calendar.update(scheduled=scheduled, so_far=meetings(week, now),
                    previous_so_far=meetings(prior, elapsed) if known(prior, "interviews") else None,
                    change=change(scheduled, calendar["previous_full"]))
    return {"week_start": week.isoformat(), "week_end": (week + timedelta(days=6)).isoformat(),
            "applications": app, "interviews": calendar}


# ---------------------------------------------------------------- profile series

def profile_series(conn, data: dict, start: date, end: date, now: datetime) -> dict:
    """Weekly values per profile for each metric. None marks weeks without records."""
    today = local_day(now)
    weeks = _weeks(start, end)
    mature_through = today - timedelta(days=COHORT_DAYS + 1)
    reply_day = local_day(data["reply_start"]) if data["reply_start"] else None
    follow = timedelta(days=COHORT_DAYS)
    own: dict[int, dict] = defaultdict(lambda: {"applications": [], "interviews": [], "rejections": []})
    for aid, _, day, group in data["applications"]:
        own[aid]["applications"].append((day, group))
    for aid, stamp, event in data["interviews"]:
        own[aid]["interviews"].append((local_day(stamp), event))
    for aid, stamp in data["rejections"]:
        own[aid]["rejections"].append(local_day(stamp))

    availability = {}
    for metric, outcome, label in (("interview_rate", "interview", "interview invitation"), ("rejection_rate", "rejection", "rejection")):
        cover = data["coverage"][outcome]
        reason = None
        if cover["share"] is None:
            reason = f"No {label} emails have been recorded yet."
        elif cover["share"] < MATCH_GATE:
            reason = (f"Only {cover['matched']:,} of {cover['emails']:,} {label} emails ({cover['share']:.0%}) can be matched to one "
                      f"application; at least {MATCH_GATE:.0%} is needed for a reliable rate.")
        elif reply_day is None or reply_day > mature_through:
            reason = f"No application has had the full {COHORT_DAYS}-day follow-up since replies were first recorded."
        availability[metric] = {"available": reason is None, "reason": reason, **cover}

    colors = {**calendar_colors.default_colors(conn), **calendar_colors.colors(conn)}
    emails = {row["id"]: row["email"] for row in conn.execute("SELECT id,email FROM accounts")}
    series = []
    for aid in data["scope_ids"]:
        mine = own.get(aid, {"applications": [], "interviews": [], "rejections": []})
        first_application = min((day for day, _ in mine["applications"]), default=None)
        first_interview = min((day for day, _ in mine["interviews"]), default=None)
        first_record = min(filter(None, (first_application, first_interview)), default=None)
        points: dict[str, list] = {k: [] for k in ("applications", "interviews", "rejections", "interview_rate", "rejection_rate")}
        for week in weeks:
            last = week + timedelta(days=6)
            points["applications"].append(sum(1 for day, _ in mine["applications"] if week <= day <= last)
                                          if first_application and first_application <= last and week <= today else None)
            points["interviews"].append(len({e for day, e in mine["interviews"] if week <= day <= last})
                                        if first_record and first_record <= last else None)
            has_replies = reply_day is not None and reply_day <= last and week <= today and first_record is not None
            points["rejections"].append(sum(1 for day in mine["rejections"] if week <= day <= last) if has_replies else None)
            # Same cohort: applications of the week inside reply history that have had the follow-up window.
            cohort = [g for day, g in mine["applications"] if week <= day <= last and reply_day and reply_day <= day <= mature_through]
            for metric, outcome in (("interview_rate", "interview"), ("rejection_rate", "rejection")):
                value = None
                if availability[metric]["available"] and cohort:
                    hits = sum(1 for g in cohort if g["outcomes"][outcome] and g["outcomes"][outcome] <= g["stamp"] + follow)
                    value = {"value": hits / len(cohort), "hits": hits, "base": len(cohort)}
                points[metric].append(value)
        series.append({"id": aid, "label": data["labels"][aid], "email": emails.get(aid, ""),
                       "color": colors.get(aid, max(0, aid - 1) % 6), "points": points})
    return {"weeks": [{"start": w.isoformat(), "partial": w <= today <= w + timedelta(days=6),
                       "replies_partial": bool(reply_day and w < reply_day <= w + timedelta(days=6))} for w in weeks],
            "series": series, "rates": availability, "cohort_days": COHORT_DAYS, "mature_through": mature_through.isoformat(),
            "replies_since": reply_day.isoformat() if reply_day else None}


# ---------------------------------------------------------------- workload

def work_rows(conn, upper: datetime, *, account=None, bidder=None) -> list[dict]:
    """Sourcing rows that hold a link and were created before ``upper`` (current sheets only).

    ``done_at`` follows the authoritative checked-application rule used for payments: the
    matched confirmation time, otherwise the start of the row's sourcing day. ``spans`` are
    the intervals during which the bidder was assigned to the account and could work the row."""
    assignments = defaultdict(list)
    for row in conn.execute("SELECT bidder_id,account_id,start_date,end_date FROM bidder_assignments"):
        last = bound(date.fromisoformat(row["end_date"]) + timedelta(days=1)) if row["end_date"] else None
        assignments[row["bidder_id"], row["account_id"]].append((bound(date.fromisoformat(row["start_date"])), last))
    sql = """SELECT r.id, r.created_at, r.work_date, b.bidder_id, t.account_id,
        MAX(col.kind='check' AND c.value='true') AS done,
        MAX(col.kind='link' AND trim(c.value, char(9)||char(10)||char(13)||' ')!='') AS link,
        a.detected_at, a.confirmed_at
        FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id JOIN native_books b ON b.id=t.book_id
        JOIN bidders p ON p.id=b.bidder_id AND p.removed_at IS NULL
        JOIN native_cells c ON c.row_id=r.id JOIN native_columns col ON col.id=c.column_id
        LEFT JOIN sourcing_check_activity a ON a.row_id=r.id
        WHERE r.created_at IS NOT NULL AND r.created_at<?"""
    params: list = [upper.timestamp()]
    if bidder is not None:
        sql += " AND b.bidder_id=?"
        params.append(bidder)
    if account:
        sql += " AND t.account_id IN (SELECT id FROM accounts WHERE label=?)"
        params.append(account)
    rows = []
    for row in conn.execute(sql + " GROUP BY r.id HAVING link", params):
        created = datetime.fromtimestamp(row["created_at"], timezone.utc)
        expires = created + timedelta(seconds=LIFETIME_SECONDS)
        done_at = None
        if row["done"]:
            done_at = _parse(row["confirmed_at"])
            if done_at is None:
                try:
                    done_at = bound(date.fromisoformat(row["work_date"]))
                except (TypeError, ValueError):
                    done_at = created
            done_at = max(done_at, created)
        # A checked row stays available until it was completed, even after a late confirmation.
        closes = done_at + timedelta(microseconds=1) if done_at else expires
        spans = []
        for first, last in assignments.get((row["bidder_id"], row["account_id"]), ()):
            lo, hi = max(created, first), closes if last is None else min(closes, last)
            if lo < hi:
                spans.append((lo, hi))
        rows.append({"id": row["id"], "bidder_id": row["bidder_id"], "account_id": row["account_id"], "created": created,
                     "expires": expires, "done_at": done_at, "spans": spans, "confirmed": bool(row["confirmed_at"]),
                     "detected": _parse(row["detected_at"])})
    return rows


def productivity_window(rows: list[dict], lower: datetime, upper: datetime) -> dict:
    """Distinct workload available in [lower, upper): opening backlog plus newly available
    links, and how much of that same population was completed, expired or is still open."""
    carry = new = completed = expired = remaining = 0
    for row in rows:
        spans = [(lo, hi) for lo, hi in row["spans"] if lo < upper and hi > lower]
        if not spans:
            continue
        if min(lo for lo, _ in row["spans"]) < lower:
            carry += 1
        else:
            new += 1
        done = row["done_at"]
        if done is not None and lower <= done < upper:
            completed += 1
        elif done is None and row["expires"] <= upper and any(hi >= row["expires"] for _, hi in spans):
            expired += 1
        elif any(hi >= upper for _, hi in spans):
            remaining += 1
    available = carry + new
    return {"carryover": carry, "new": new, "available": available, "completed": completed, "expired": expired,
            "remaining": remaining, "completion_rate": rate(completed, available)}


def _buckets(start: date, end: date, today: date, grain: str) -> list[tuple[date, date]]:
    out, day = [], start
    while day <= min(end, today):
        last = day if grain == "daily" else monday(day) + timedelta(days=6)
        out.append((day, last))
        day = last + timedelta(days=1)
    return out


def bidder_series(conn, rows: list[dict], start: date, end: date, now: datetime, *, account=None, bidder=None) -> dict:
    """Daily and weekly workload per bidder, plus the combined supply and output series."""
    today = local_day(now)
    names = {r["id"]: r["name"] for r in conn.execute(
        "SELECT id,name FROM bidders WHERE removed_at IS NULL AND (? IS NULL OR id=?) ORDER BY name COLLATE NOCASE", (bidder, bidder))}
    ids = {r["id"] for r in conn.execute("SELECT id FROM accounts WHERE label=?", (account,))} if account else None
    history = min((local_day(r["created"]) for r in rows), default=None)
    checked = defaultdict(int)  # the authoritative checked-application counts used for payments
    if start <= today:
        for (who, aid, day), n in completed_account_counts(conn, start.isoformat(), min(end, today).isoformat()).items():
            if who in names and (ids is None or aid in ids):
                checked[who, date.fromisoformat(day)] += n
    by_bidder = defaultdict(list)
    for row in rows:
        by_bidder[row["bidder_id"]].append(row)
    result: dict = {}
    for grain in ("daily", "weekly"):
        buckets = _buckets(start, end, today, grain)
        series = {who: [] for who in names}
        workload = []
        for first, last in buckets:
            lower, upper = bound(first), min(bound(last + timedelta(days=1)), now)
            known = history is not None and last >= history
            totals = {"new": 0, "backlog": 0, "expired": 0}
            credited = 0
            for who in names:
                done = sum(checked.get((who, first + timedelta(days=i)), 0) for i in range((last - first).days + 1))
                credited += done
                if not known:
                    series[who].append(None)
                    continue
                window = productivity_window(by_bidder.get(who, []), lower, upper)
                series[who].append({**window, "checked": done})
                totals["backlog"] += window["remaining"]
                totals["expired"] += window["expired"]
                totals["new"] += window["new"]
            workload.append({**(totals if known else {"new": None, "backlog": None, "expired": None}),
                             "checked": credited if known or credited else None})
        meta = [{"start": f.isoformat(), "partial": last >= today} for f, last in buckets]
        result[grain] = {"buckets": meta, "series": [{"id": who, "name": names[who], "points": series[who]} for who in names],
                         "workload": workload}
    result["history_since"] = history.isoformat() if history else None
    return result


# ---------------------------------------------------------------- attention

def attention(conn, rows: list[dict], now: datetime, today: date, *, admin: bool, account=None, bidder=None) -> list[dict]:
    """Only data-backed items with a count above zero, each with a destination."""
    items = []
    start, end = today - timedelta(days=ATTENTION_DAYS - 1), today
    unconfirmed = [r for r in rows if r["done_at"] is not None and not r["confirmed"] and r["detected"] is not None
                   and bound(start) <= r["detected"] < bound(end + timedelta(days=1)) and r["detected"] <= now - CONFIRMATION_GRACE]
    if unconfirmed:
        items.append({"id": "missing_confirmations", "severity": "warning", "count": len(unconfirmed), "href": "/sourcing",
                      "label": "Unconfirmed links",
                      "detail": f"Checked in the last {ATTENTION_DAYS} days, more than 24 hours ago, with no matching confirmation email."})
    expiring = [r for r in rows if r["done_at"] is None and now < r["expires"] <= now + timedelta(seconds=WARNING_SECONDS)]
    if expiring:
        items.append({"id": "expiring_links", "severity": "warning", "count": len(expiring), "href": "/sourcing",
                      "label": "Expiring within 48 hours", "detail": "Open links reach their 7-day limit soon."})
    backlog = [r for r in rows if r["done_at"] is None and r["created"] < bound(today) and r["expires"] > now]
    if backlog:
        items.append({"id": "backlog", "severity": "info", "count": len(backlog), "href": "/sourcing",
                      "label": "Carried-over links", "detail": "Open links created before today."})
    from .payments import deduction_rule
    minimum = deduction_rule(conn)["minimum_daily"]
    if minimum > 0 and today.weekday() < 5:
        day = today.isoformat()
        assigned = {r["bidder_id"] for r in conn.execute("""SELECT DISTINCT a.bidder_id FROM bidder_assignments a
            JOIN bidders b ON b.id=a.bidder_id AND b.removed_at IS NULL
            WHERE a.start_date<=? AND (a.end_date IS NULL OR a.end_date>=?) AND (? IS NULL OR a.bidder_id=?)""", (day, day, bidder, bidder))}
        short = []
        for who in sorted(assigned):
            today_window = productivity_window([r for r in rows if r["bidder_id"] == who], bound(today), now)
            if today_window["available"] < minimum:
                short.append(who)
        if short:
            items.append({"id": "insufficient_workload", "severity": "warning", "count": len(short), "href": "/sourcing",
                          "label": "Bidders below the daily minimum workload",
                          "detail": f"Fewer than {minimum} links available today (deduction policy minimum)."})
    if admin:
        try:
            from .realtime import storage as realtime_storage
            from .realtime.sync_status import failure_reason
            enabled = {r["id"] for r in conn.execute("SELECT id FROM accounts WHERE enabled=1 AND (? IS NULL OR label=?)", (account, account))}
            failing = [r for r in realtime_storage.status(conn) if r["account_id"] in enabled and failure_reason(r["last_error"])]
        except Exception:  # realtime tables are optional in older databases
            failing = []
        if failing:
            items.append({"id": "account_connectivity", "severity": "critical", "count": len(failing), "href": "/accounts",
                          "label": "Accounts with sync failures", "detail": "Real-time mail sync reported an error."})
        scope, params = "", [bound(start).isoformat(), bound(end + timedelta(days=1)).isoformat()]
        if account:
            scope = " AND m.account_id IN (SELECT id FROM accounts WHERE label=?)"
            params.append(account)
        unclassified = conn.execute("""SELECT COUNT(*) FROM messages m LEFT JOIN classifications c ON c.id=(SELECT id FROM classifications
            WHERE message_pk=m.id ORDER BY created_at DESC, id DESC LIMIT 1)
            WHERE (c.id IS NULL OR c.category='unclassified') AND m.handled_at IS NULL
            AND julianday(COALESCE(m.date_utc, m.fetched_at))>=julianday(?) AND julianday(COALESCE(m.date_utc, m.fetched_at))<julianday(?)""" + scope,
            params).fetchone()[0]
        if unclassified:
            items.append({"id": "unclassified", "severity": "info", "count": unclassified, "href": "/inbox?category=unclassified",
                          "label": "Unclassified messages", "detail": f"Open messages from the last {ATTENTION_DAYS} days that could not be categorized."})
    return items


# ---------------------------------------------------------------- payments

def payment_overview(conn, end: date, *, admin: bool, bidder=None) -> dict:
    """Gross, deductions, net payable and recorded payments for the payment week containing
    the given day. Outstanding is reported only once the week is reconciled: it has ended
    and every bidder with work has a pay rate."""
    from . import payments
    report = payments.report(conn, end, admin=admin, bidder_id=bidder, read_only=True)
    bidders = report["bidders"]
    known = [b for b in bidders if b["gross_amount_cents"] is not None]
    missing_rate = [b["name"] for b in bidders if b["gross_amount_cents"] is None and b["total"]]
    recorded = sum(b["payment"]["amount_cents"] for b in bidders if b.get("payment"))
    payable = sum(b["payable_amount_cents"] or 0 for b in bidders)
    ended = date.fromisoformat(report["week_end"]) < payments.today()
    reconciled = ended and not missing_rate
    return {"week_start": report["week_start"], "week_end": report["week_end"], "currency": report["currency"],
            "gross_cents": sum(b["gross_amount_cents"] for b in known),
            "deductions_cents": sum(b["deduction_total_cents"] for b in known),
            "net_payable_cents": payable, "recorded_cents": recorded,
            "outstanding_cents": max(0, payable - recorded) if reconciled else None,
            "reconciled": reconciled, "week_ended": ended, "missing_rates": missing_rate,
            "checked": sum(b["total"] for b in bidders), "bidders": len(bidders)}


# ---------------------------------------------------------------- report

def report(conn, *, weeks: int | None = None, start: date | None = None, end: date | None = None,
           account: str | None = None, bidder: int | None = None, admin: bool = True, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    today = local_day(now)
    first, last = graph_range(today, weeks, start, end)
    data = outcome_data(conn, now, account=account, bidder=bidder)
    rows = work_rows(conn, now, account=account, bidder=bidder)
    return {
        "version": 2, "as_of": now.isoformat(), "timezone": ZONE.key, "today": today.isoformat(),
        "range": {"weeks": None if start else (weeks or DEFAULT_WEEKS), "start": first.isoformat(), "end": last.isoformat()},
        "filters": {"account": account, "bidder": bidder},
        "summaries": summaries(data, now),
        "profiles": profile_series(conn, data, first, last, now),
        "bidders": bidder_series(conn, rows, first, last, now, account=account, bidder=bidder),
        "attention": attention(conn, rows, now, today, admin=admin, account=account, bidder=bidder),
        "payments": payment_overview(conn, today, admin=admin, bidder=bidder),
    }
