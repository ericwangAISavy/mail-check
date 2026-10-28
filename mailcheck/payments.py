"""Bidder accounting: durable receipt counts and immutable weekly payment records."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator, model_validator

ZONE = ZoneInfo("America/Chicago")

SCHEMA = """
CREATE TABLE IF NOT EXISTS bidder_payment_edits (
 id INTEGER PRIMARY KEY AUTOINCREMENT,payment_id INTEGER NOT NULL REFERENCES bidder_payments(id),
 edited_at TEXT NOT NULL,before_json TEXT NOT NULL,after_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bidder_payment_amounts (
 bidder_id INTEGER NOT NULL REFERENCES bidders(id),week_start TEXT NOT NULL,
 amount_cents INTEGER NOT NULL,application_count INTEGER NOT NULL,
 PRIMARY KEY(bidder_id,week_start)
);

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
 category TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '', PRIMARY KEY(account_id, message_id)
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


class RateBody(BaseModel):
    pay_per_bid: Decimal = Field(ge=0,le=100,decimal_places=6)
    adjustment_percent: Decimal = Field(default=Decimal('20'),ge=0,le=1000,decimal_places=4)


def save_rate(conn,bidder_id,body):
    bidder(conn,bidder_id)
    conn.execute('UPDATE bidders SET pay_per_bid=?,adjustment_percent=? WHERE id=?',(str(body.pay_per_bid),str(body.adjustment_percent),bidder_id))


def calculate_amount(pay_per_bid,count,adjustment_percent):
    if pay_per_bid is None:return None
    amount=Decimal(str(pay_per_bid))*count*(1+Decimal(str(adjustment_percent))/100)
    return int(amount.quantize(Decimal('.01'),rounding=ROUND_HALF_UP)*100)


class AmountBody(BaseModel):
    week: date = Field(ge=date(1971,1,1),le=date(2100,12,31))
    expected_count: int = Field(ge=0)
    amount: Decimal | None = Field(default=None,ge=0,le=1000000,decimal_places=2)


def save_amount(conn,bidder_id,body):
    bidder(conn,bidder_id)
    start=monday(body.week)
    if start+timedelta(days=6)>=today():raise ValueError('Edit the final payment amount after the week has ended')
    row=next(b for b in report(conn,start)['bidders'] if b['id']==bidder_id)
    if row['payment']:raise ValueError('This payment is already recorded; its paid amount remains saved')
    if row['total']!=body.expected_count:raise ValueError('Counts changed. Refresh and review before saving the amount.')
    if body.amount is None:
        conn.execute('DELETE FROM bidder_payment_amounts WHERE bidder_id=? AND week_start=?',(bidder_id,start.isoformat()))
    else:
        conn.execute('INSERT INTO bidder_payment_amounts VALUES(?,?,?,?) ON CONFLICT(bidder_id,week_start) DO UPDATE SET amount_cents=excluded.amount_cents,application_count=excluded.application_count',(bidder_id,start.isoformat(),int(body.amount*100),row['total']))


class WalletBody(BaseModel):
    wallet_network: str = Field(default='USDT.BEP20',max_length=40)
    wallet_address: str = Field(default='',max_length=128)

    @model_validator(mode='after')
    def clean_wallet(self):
        self.wallet_address=self.wallet_address.strip()
        self.wallet_network=self.wallet_network.strip().upper()
        if not self.wallet_address:
            self.wallet_network=''
            return self
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{0,39}',self.wallet_network):
            raise ValueError('Enter a payment network such as USDT.BEP20')
        if not re.fullmatch(r'[A-Za-z0-9]{16,128}',self.wallet_address):
            raise ValueError('Enter a wallet address without spaces or separators')
        if self.wallet_network in ('USDT.BEP20','USDT.ERC20') and not re.fullmatch(r'0x[0-9a-fA-F]{40}',self.wallet_address):
            raise ValueError('BEP20 and ERC20 addresses must start with 0x followed by 40 hexadecimal characters')
        return self


def save_wallet(conn,bidder_id,body):
    bidder(conn,bidder_id)
    conn.execute('UPDATE bidders SET wallet_network=?,wallet_address=? WHERE id=?',(body.wallet_network,body.wallet_address,bidder_id))


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


class EditPayBody(PayBody):
    expected_revision: int = Field(ge=0)


def edit_payment(conn,bidder_id,body):
    bidder(conn,bidder_id)
    start=monday(body.week)
    if start+timedelta(days=6)>=today():raise ValueError('Edit recorded payments after the week has ended')
    current=next(b for b in report(conn,start)['bidders'] if b['id']==bidder_id)
    if current['total']!=body.expected_count:raise ValueError('Counts changed. Refresh and review before editing payment.')
    previous=current['payment']
    if not previous:raise ValueError('No recorded payment exists for this bidder and week')
    if previous['revision']!=body.expected_revision:raise ValueError('This payment was edited elsewhere. Refresh and review before saving.')
    updated={**previous,'application_count':current['total'],'amount_cents':int(body.amount*100),'note':body.note.strip(),'revision':previous['revision']+1}
    changed=conn.execute('UPDATE bidder_payments SET amount_cents=?,application_count=?,note=?,revision=revision+1 WHERE id=? AND revision=?',(updated['amount_cents'],updated['application_count'],updated['note'],previous['id'],body.expected_revision))
    if changed.rowcount!=1:raise ValueError('This payment changed. Refresh and review before saving.')
    conn.execute('INSERT INTO bidder_payment_edits(payment_id,edited_at,before_json,after_json) VALUES(?,?,?,?)',(previous['id'],datetime.now(timezone.utc).isoformat(),json.dumps(previous),json.dumps(updated)))


def sync_receipts(conn: sqlite3.Connection, message_pk: int | None = None) -> None:
    """Upsert receipt metadata, including company and role; never store email bodies."""
    from .db import LATEST_CLASSIFICATION
    conn.execute("""INSERT INTO application_receipts(account_id, message_id, received_at, category, company, role)
        SELECT m.account_id, m.message_id, COALESCE(m.date_utc, m.fetched_at), c.category, COALESCE(c.company,''), COALESCE(c.role,'')
        FROM messages m """ + LATEST_CLASSIFICATION + """
        WHERE (c.category = 'application_ack' OR EXISTS (
          SELECT 1 FROM application_receipts r WHERE r.account_id=m.account_id AND r.message_id=m.message_id))
        """ + (" AND m.id=? " if message_pk is not None else "") + """
        ON CONFLICT(account_id, message_id) DO UPDATE SET
          received_at=excluded.received_at, category=excluded.category, company=excluded.company, role=excluded.role""", (message_pk,) if message_pk is not None else ())


def monday(value: date) -> date:
    return value - timedelta(days=value.weekday())


def today() -> date:
    return datetime.now(ZONE).date()


def received_today(conn: sqlite3.Connection) -> int:
    """Count each confirmation once on its Chicago receipt date, across accounts."""
    day=today()
    lower=datetime.combine(day,datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    upper=datetime.combine(day+timedelta(days=1),datetime.min.time(),ZONE).astimezone(timezone.utc).isoformat()
    return conn.execute("""SELECT COUNT(*) FROM application_receipts
        WHERE category='application_ack' AND julianday(received_at)>=julianday(?)
        AND julianday(received_at)<julianday(?)""",(lower,upper)).fetchone()[0]


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
    assignments = [dict(row) for row in conn.execute("SELECT * FROM bidder_assignments WHERE bidder_id IN (SELECT id FROM bidders WHERE removed_at IS NULL) ORDER BY start_date,id")]
    payments = {r["bidder_id"]: dict(r) for r in conn.execute("SELECT * FROM bidder_payments WHERE week_start=? AND (? IS NULL OR bidder_id=?)", (start.isoformat(),bidder_id,bidder_id))}
    from .sourcing_verification import completed_account_counts
    account_checks = completed_account_counts(conn, start.isoformat(), end.isoformat())
    checked = {}
    for (who, _account_id, day), count in account_checks.items():
        checked[who, day] = checked.get((who, day), 0) + count
    allocations = {}
    unallocated = {day: 0 for day in dates}
    for (account_id, day), total in counts.items():
        owners = sorted({a["bidder_id"] for a in assignments if a["account_id"] == account_id
                         and a["start_date"] <= day and (not a["end_date"] or a["end_date"] >= day)})
        if len(owners) == 1:
            shares = {owners[0]: total}
        elif len(owners) > 1:
            weights = {who: account_checks.get((who, account_id, day), 0) for who in owners}
            weight_sum = sum(weights.values())
            if not weight_sum:
                unallocated[day] += total
                continue
            # Largest remainders preserve the account total with integer shares.
            shares = {who: total * weights[who] // weight_sum for who in owners}
            remainder_order = sorted(owners, key=lambda who: (-(total * weights[who] % weight_sum), who))
            for who in remainder_order[:total - sum(shares.values())]:
                shares[who] += 1
        else:
            continue
        for who, count in shares.items():
            allocations[who, day] = allocations.get((who, day), 0) + count
    bidders = []
    for row in conn.execute("SELECT * FROM bidders WHERE removed_at IS NULL AND (? IS NULL OR id=?) ORDER BY name", (bidder_id,bidder_id)):
        assigned = [a for a in assignments if a["bidder_id"] == row["id"]]
        daily = [allocations.get((row["id"], day), 0) for day in dates]
        total = sum(daily)
        override=conn.execute('SELECT amount_cents,application_count FROM bidder_payment_amounts WHERE bidder_id=? AND week_start=?',(row['id'],start.isoformat())).fetchone()
        calculated=calculate_amount(row['pay_per_bid'],total,row['adjustment_percent'])
        paid=payments.get(row['id'])
        payable=paid['amount_cents'] if paid else override['amount_cents'] if override else calculated
        bidders.append({"id": row["id"], "name": row["name"],
            **({"wallet_network":row["wallet_network"],"wallet_address":row["wallet_address"]} if admin else {}),
            "pay_per_bid":row['pay_per_bid'],"adjustment_percent":row['adjustment_percent'],
            "calculated_amount_cents":calculated,"payable_amount_cents":payable,
            "amount_override_cents":override['amount_cents'] if override else None,
            "override_application_count":override['application_count'] if override else None,
            "assignments": assigned, "daily": daily, "total": total,
            "application_total": total,
            "checked_daily": [checked.get((row["id"], day), 0) for day in dates],
            "payment": payments.get(row["id"])})
    # Shared assignments expose the same receipts in multiple bidder rows.
    # Count each account/day once for the report overview and footer.
    unique_daily = [sum(counts.get((account_id, day), 0) for account_id in {
        a["account_id"] for a in assignments
        if a["start_date"] <= day and (not a["end_date"] or a["end_date"] >= day)
    }) for day in dates]
    return {"week_start": start.isoformat(), "week_end": end.isoformat(), "today": today().isoformat(),
        "timezone": ZONE.key, "currency": "USD", "dates": dates, "bidders": bidders,
        "daily": unique_daily if bidder_id is None else [sum(b["daily"][i] for b in bidders) for i in range(7)],
        "unallocated_daily": [unallocated[day] for day in dates] if admin and bidder_id is None else [0] * 7,
        "checked_daily": [sum(b["checked_daily"][i] for b in bidders) for i in range(7)],
        "unassigned": sum(count for (account_id, day), count in counts.items()
                          if not any(a["account_id"] == account_id and a["start_date"] <= day
                                     and (not a["end_date"] or a["end_date"] >= day)
                                     for a in assignments)) if admin else 0,
        "accounts": [{"id": a["id"], "label": a["label"]} for a in conn.execute("SELECT id,label FROM accounts ORDER BY label")] if admin else []}


def bidder(conn, bidder_id):
    if not conn.execute("SELECT 1 FROM bidders WHERE id=? AND removed_at IS NULL", (bidder_id,)).fetchone():
        raise LookupError("Bidder not found")


def remove_bidder(conn, bidder_id: int):
    bidder(conn, bidder_id)
    conn.execute("UPDATE bidders SET removed_at=?,login_enabled=0 WHERE id=?",
                 (datetime.now(timezone.utc).isoformat(), bidder_id))
    conn.execute("UPDATE native_tabs SET archived=1 WHERE book_id IN (SELECT id FROM native_books WHERE bidder_id=?)", (bidder_id,))


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
    if row["application_total"] != body.expected_count:
        raise ValueError("Counts changed. Refresh and review before recording payment.")
    if row["payment"]:
        raise ValueError("Payment already recorded for this bidder and week")
    conn.execute("INSERT INTO bidder_payments(bidder_id,week_start,application_count,amount_cents,paid_at,note) VALUES(?,?,?,?,?,?)",
        (bidder_id,start.isoformat(),row["application_total"],int(body.amount * 100),datetime.now(timezone.utc).isoformat(),body.note.strip()))
