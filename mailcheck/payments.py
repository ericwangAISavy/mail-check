"""Bidder accounting: durable receipt counts and immutable weekly payment records."""
from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

ZONE = ZoneInfo("America/Chicago")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bidders (
 id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL COLLATE NOCASE UNIQUE,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS bidder_assignments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, bidder_id INTEGER NOT NULL REFERENCES bidders(id),
 account_id INTEGER NOT NULL, account_label TEXT NOT NULL,
 start_date TEXT NOT NULL, end_date TEXT,
 CHECK(end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX IF NOT EXISTS idx_bidder_assignments_account ON bidder_assignments(account_id, start_date);
CREATE TABLE IF NOT EXISTS application_receipts (
 account_id INTEGER NOT NULL, message_id TEXT NOT NULL, received_at TEXT NOT NULL,
 category TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', PRIMARY KEY(account_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_receipts_week ON application_receipts(category, julianday(received_at));
CREATE TABLE IF NOT EXISTS bidder_payments (
 id INTEGER PRIMARY KEY AUTOINCREMENT, bidder_id INTEGER NOT NULL REFERENCES bidders(id),
 week_start TEXT NOT NULL, application_count INTEGER NOT NULL,
 amount_cents INTEGER NOT NULL, paid_at TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
 UNIQUE(bidder_id, week_start)
);
"""


class BidderBody(BaseModel):
    name: str = Field(min_length=1, max_length=100)

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip():
            raise ValueError("Enter a bidder name")
        return value.strip()


class AssignmentBody(BaseModel):
    account_id: int
    start_date: date = Field(ge=date(1971, 1, 1), le=date(2100, 12, 31))
    end_date: date | None = Field(default=None, ge=date(1971, 1, 1), le=date(2100, 12, 31))


class EndAssignmentBody(BaseModel):
    end_date: date = Field(ge=date(1971, 1, 1), le=date(2100, 12, 31))


class PayBody(BaseModel):
    week: date = Field(ge=date(1971, 1, 1), le=date(2100, 12, 31))
    expected_count: int = Field(ge=0)
    amount: Decimal = Field(gt=0, le=1000000, decimal_places=2)
    note: str = Field(default="", max_length=500)


def sync_receipts(conn: sqlite3.Connection, message_pk: int | None = None) -> None:
    """Upsert receipt metadata, including company; never store email bodies."""
    from .db import LATEST_CLASSIFICATION
    conn.execute("""INSERT INTO application_receipts(account_id, message_id, received_at, category, company)
        SELECT m.account_id, m.message_id, COALESCE(m.date_utc, m.fetched_at), c.category, COALESCE(c.company,'')
        FROM messages m """ + LATEST_CLASSIFICATION + """
        WHERE (c.category = 'application_ack' OR EXISTS (
          SELECT 1 FROM application_receipts r WHERE r.account_id=m.account_id AND r.message_id=m.message_id))
        """ + (" AND m.id=? " if message_pk is not None else "") + """
        ON CONFLICT(account_id, message_id) DO UPDATE SET
          received_at=excluded.received_at, category=excluded.category, company=excluded.company""", (message_pk,) if message_pk is not None else ())


def monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def today() -> date:
    return datetime.now(ZONE).date()


def report(conn: sqlite3.Connection, week: date | None = None, *, admin: bool = False, bidder_id: int | None = None) -> dict:
    sync_receipts(conn)
    start = monday(week or today())
    end = start + timedelta(days=6)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(7)]
    # Bound in UTC, then bucket in the accounting timezone, including DST days.
    lower = datetime.combine(start, datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    counts = {}
    for row in conn.execute("""SELECT account_id, received_at FROM application_receipts
        WHERE category='application_ack' AND julianday(received_at)>=julianday(?)
        AND julianday(received_at)<julianday(?)""", (lower, upper)):
        stamp = datetime.fromisoformat(row["received_at"])
        day = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).astimezone(ZONE).date().isoformat()
        key = (row["account_id"], day)
        counts[key] = counts.get(key, 0) + 1
    assignments = [dict(row) for row in conn.execute("SELECT * FROM bidder_assignments WHERE (? IS NULL OR bidder_id=?) ORDER BY start_date,id", (bidder_id,bidder_id))]
    payments = {r["bidder_id"]: dict(r) for r in conn.execute("SELECT * FROM bidder_payments WHERE week_start=? AND (? IS NULL OR bidder_id=?)", (start.isoformat(),bidder_id,bidder_id))}
    from .sourcing_verification import checked_counts
    checked = checked_counts(conn, start.isoformat(), end.isoformat())
    bidders = []
    for row in conn.execute("SELECT * FROM bidders WHERE (? IS NULL OR id=?) ORDER BY name", (bidder_id,bidder_id)):
        assigned = [a for a in assignments if a["bidder_id"] == row["id"]]
        daily = [sum(counts.get((a["account_id"], day), 0) for a in assigned
                     if a["start_date"] <= day and (not a["end_date"] or a["end_date"] >= day)) for day in dates]
        total = sum(daily)
        bidders.append({"id": row["id"], "name": row["name"],
            "assignments": assigned, "daily": daily, "total": total,
            "checked_daily": [checked.get((row["id"], day), 0) for day in dates],
            "payment": payments.get(row["id"])})
    return {"week_start": start.isoformat(), "week_end": end.isoformat(), "today": today().isoformat(),
        "timezone": ZONE.key, "currency": "USD", "dates": dates, "bidders": bidders,
        "daily": [sum(b["daily"][i] for b in bidders) for i in range(7)],
        "checked_daily": [sum(b["checked_daily"][i] for b in bidders) for i in range(7)],
        "unassigned": sum(count for (account_id, day), count in counts.items()
                          if not any(a["account_id"] == account_id and a["start_date"] <= day
                                     and (not a["end_date"] or a["end_date"] >= day)
                                     for a in assignments)) if admin else 0,
        "accounts": [{"id": a["id"], "label": a["label"]} for a in conn.execute("SELECT id,label FROM accounts ORDER BY label")] if admin else []}


def bidder(conn, bidder_id):
    if not conn.execute("SELECT 1 FROM bidders WHERE id=?", (bidder_id,)).fetchone():
        raise LookupError("Bidder not found")


def assign(conn, bidder_id: int, body: AssignmentBody):
    bidder(conn, bidder_id)
    if body.end_date and body.end_date < body.start_date:
        raise ValueError("End date must be on or after start date")
    account = conn.execute("SELECT label FROM accounts WHERE id=?", (body.account_id,)).fetchone()
    if not account:
        raise ValueError("Account not found")
    if conn.execute("""SELECT 1 FROM bidder_assignments WHERE account_id=? AND bidder_id=?
        AND start_date<=? AND COALESCE(end_date,'9999-12-31')>=?""",
        (body.account_id, bidder_id, (body.end_date or date.max).isoformat(), body.start_date.isoformat())).fetchone():
        raise ValueError("This bidder already has an assignment for this account during those dates.")
    # Accounting for a paid week cannot be reassigned after settlement.
    reject_paid_overlap(conn, body.start_date, body.end_date, bidder_id)
    conn.execute("INSERT INTO bidder_assignments(bidder_id,account_id,account_label,start_date,end_date) VALUES(?,?,?,?,?)",
        (bidder_id, body.account_id, account["label"], body.start_date.isoformat(), body.end_date.isoformat() if body.end_date else None))


def reject_paid_overlap(conn, start: date, end: date | None, bidder_id: int):
    if conn.execute("SELECT 1 FROM bidder_payments WHERE bidder_id=? AND week_start<=? AND date(week_start,'+6 days')>=?",
        (bidder_id, (end or date.max).isoformat(), start.isoformat())).fetchone():
        raise ValueError("Assignments cannot change a week with a recorded payment")


def assignment_row(conn, assignment_id: int):
    row = conn.execute("SELECT * FROM bidder_assignments WHERE id=?", (assignment_id,)).fetchone()
    if not row:
        raise LookupError("Assignment not found")
    return row


def protect_assignment_payments(conn, old, new: AssignmentBody | None):
    """Allow edits outside settled weeks, while preserving their exact assignments."""
    old_start = date.fromisoformat(old["start_date"])
    old_end = date.fromisoformat(old["end_date"]) if old["end_date"] else date.max
    for payment in conn.execute("SELECT week_start FROM bidder_payments WHERE bidder_id=?", (old["bidder_id"],)):
        week = date.fromisoformat(payment["week_start"])
        end = week + timedelta(days=6)
        def portion(start, stop):
            lower, upper = max(start, week), min(stop, end)
            return (lower, upper) if lower <= upper else None
        before = portion(old_start, old_end)
        after = portion(new.start_date, new.end_date or date.max) if new else None
        if before != after or (before and new and old["account_id"] != new.account_id):
            raise ValueError("This change would affect a week with a recorded payment")


def edit_assignment(conn, assignment_id: int, body: AssignmentBody):
    old = assignment_row(conn, assignment_id)
    if body.end_date and body.end_date < body.start_date:
        raise ValueError("End date must be on or after start date")
    account = conn.execute("SELECT label FROM accounts WHERE id=?", (body.account_id,)).fetchone()
    if not account and body.account_id != old["account_id"]:
        raise ValueError("Account not found")
    if conn.execute("""SELECT 1 FROM bidder_assignments WHERE account_id=? AND bidder_id=? AND id!=?
        AND start_date<=? AND COALESCE(end_date,'9999-12-31')>=?""",
        (body.account_id, old["bidder_id"], assignment_id, (body.end_date or date.max).isoformat(), body.start_date.isoformat())).fetchone():
        raise ValueError("This bidder already has an assignment for this account during those dates")
    protect_assignment_payments(conn, old, body)
    conn.execute("UPDATE bidder_assignments SET account_id=?,account_label=?,start_date=?,end_date=? WHERE id=?",
        (body.account_id, account["label"] if account else old["account_label"], body.start_date.isoformat(),
         body.end_date.isoformat() if body.end_date else None, assignment_id))


def remove_assignment(conn, assignment_id: int):
    old = assignment_row(conn, assignment_id)
    protect_assignment_payments(conn, old, None)
    conn.execute("DELETE FROM bidder_assignments WHERE id=?", (assignment_id,))


def record_payment(conn, bidder_id: int, body: PayBody):
    bidder(conn, bidder_id)
    start = monday(body.week)
    if start + timedelta(days=6) >= today():
        raise ValueError("Record payment after the week has ended")
    row = next(b for b in report(conn, start)["bidders"] if b["id"] == bidder_id)
    if row["total"] != body.expected_count:
        raise ValueError("Counts changed. Refresh and review before recording payment.")
    if row["payment"]:
        raise ValueError("Payment already recorded for this bidder and week")
    conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(?,?,?,?,?,?)",
        (bidder_id,start.isoformat(),row["total"],int(body.amount * 100),datetime.now(timezone.utc).isoformat(),body.note.strip()))
