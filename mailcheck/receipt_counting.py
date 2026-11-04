"""Conservative, reversible suppression of proven platform receipt copies.

The ledger remains raw evidence. Only a positive, durable source-job proof can
exclude a platform copy; ambiguous or incomplete evidence counts normally.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

from .prefilter import DEFAULT_ALERT_DOMAINS, DEFAULT_ALERT_SENDERS

_ZONE = ZoneInfo('America/Chicago')
_POLICY = 1
_REFERENCE = re.compile(
    r'\bapplication\s+(?:id|reference|ref|number|no\.?)\s*'
    r'(?:(?P<delimiter>[:#=])\s*|[-]?\s*)'
    r'(?P<token>[a-z0-9][a-z0-9_-]{0,63})(?![a-z0-9_-])', re.I)


def _references(text):
    return {m.group('token').casefold() for m in _REFERENCE.finditer(text or '')
            if m.group('delimiter') or any(c.isdigit() for c in m.group('token'))}


def application_reference(text: str) -> str | None:
    """Extract one explicit reference; alphabetic IDs require a label delimiter."""
    values = _references(text)
    return next(iter(values)) if len(values) == 1 else None


def _day(stamp):
    try:
        value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(_ZONE).date()
    except (ValueError, AttributeError, TypeError):
        return None


def _text(value):
    # Whitespace and case are safe aliases. Preserve punctuation and numbers:
    # C++, C#, Developer 2 and Developer remain distinct.
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def _role(value):
    value = _text(value)
    return re.sub(r'(?<!\w)(sr|jr)\.?(?!\w)',
                  lambda m: {'sr': 'senior', 'jr': 'junior'}[m.group(1)], value)


def _sender(value):
    return parseaddr(value or '')[1].strip().casefold()


def _platform(sender):
    return sender in DEFAULT_ALERT_SENDERS or sender.rsplit('@', 1)[-1] in DEFAULT_ALERT_DOMAINS


def _signature(row):
    return {key: row.get(key) for key in
            ('account_id', 'message_id', 'received_at', 'category', 'company', 'role', 'sender')}


def _bodies(conn, account, keys):
    columns = {r[1] for r in conn.execute('PRAGMA table_info(messages)')}
    fields = [c for c in ('body_text', 'interview_text') if c in columns]
    if not fields:
        return {}
    result = {}
    for row in conn.execute('SELECT message_id,' + ','.join(fields) +
                            ' FROM messages WHERE account_id=? AND message_id IN (?,?)',
                            (account, *keys)):
        result[row[0]] = '\n'.join(v or '' for v in row[1:])
    return result


def _jobs(conn, account, day):
    """Bound source dates below, retain all future candidate rows and archives."""
    return [dict(r) for r in conn.execute('''WITH candidates AS MATERIALIZED (
        SELECT r.id,r.tab_id,r.work_date FROM native_rows r
        JOIN native_tabs t ON t.id=r.tab_id
        WHERE t.account_id=? AND r.work_date>=?
        ) SELECT r.id,r.work_date,t.account_id,b.bidder_id,
        company.value AS company,role.value AS role,link.value AS link,
        checked.value AS checked,e.message_id,e.confirmed_at
        FROM candidates r JOIN native_tabs t ON t.id=r.tab_id
        JOIN native_books b ON b.id=t.book_id
        LEFT JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
        LEFT JOIN native_columns rc ON rc.tab_id=t.id AND rc.kind='role'
        LEFT JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
        LEFT JOIN native_columns xc ON xc.tab_id=t.id AND xc.kind='check'
        LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=cc.id
        LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=rc.id
        LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=lc.id
        LEFT JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=xc.id
        LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
        ''',
        (account, (day-timedelta(days=6)).isoformat()))]


def _effective(conn, start, end, account_id):
    lower = datetime.combine(start, datetime.min.time(), _ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), _ZONE).astimezone(timezone.utc).isoformat()
    # Enumerating category keys permits the (category, julianday) index to bound
    # each category's range, while retaining reclassified rows for flag resets.
    query = """SELECT * FROM application_receipts
        WHERE category IN (SELECT DISTINCT category FROM application_receipts)
        AND julianday(received_at)>=julianday(?) AND julianday(received_at)<julianday(?)"""
    params = (lower, upper)
    if account_id is not None:
        query += ' AND account_id=?'
        params += (account_id,)
    rows = [dict(r) for r in conn.execute(query, params)
            if (day := _day(r['received_at'])) is not None and start <= day <= end]
    original = {(r['account_id'], r['message_id']): dict(r) for r in rows}
    groups = defaultdict(list)
    for row in rows:
        row['duplicate_of'], row['counting_evidence'] = None, ''
        if row['category'] == 'application_ack' and _text(row['company']) and _role(row['role']):
            groups[(row['account_id'], _day(row['received_at']), _text(row['company']), _role(row['role']))].append(row)
    jobs_cache = {}
    for (account, day, company, role), members in groups.items():
        employers = [r for r in members if _sender(r['sender']) and not _platform(_sender(r['sender']))]
        platforms = [r for r in members if _platform(_sender(r['sender']))]
        # Multiple copies themselves are ambiguous: retain for review.
        if len(employers) != 1 or len(platforms) != 1 or len(members) != 2:
            continue
        parent, child = employers[0], platforms[0]
        bodies = _bodies(conn, account, (parent['message_id'], child['message_id']))
        refs = set().union(*(_references(body) for body in bodies.values()))
        if len(refs) > 1:
            continue
        saved = original[(account, child['message_id'])]
        try:
            evidence = json.loads(saved['counting_evidence'] or '{}')
        except (ValueError, TypeError):
            evidence = {}
        if not isinstance(evidence, dict):
            evidence = {}
        if (account, day) not in jobs_cache:
            jobs_cache[(account, day)] = _jobs(conn, account, day)
        jobs = jobs_cache[(account, day)]
        candidates = [j for j in jobs if _text(j['company']) == company and _role(j['role']) == role]
        if (saved['duplicate_of'] == parent['message_id'] and evidence.get('policy_version') == _POLICY
                and evidence.get('parent') == _signature(parent)
                and evidence.get('child') == _signature(child)
                and evidence.get('day') == day.isoformat()
                and evidence.get('job_identity')):
            captured = evidence['job_identity']
            source_exists = isinstance(captured, dict) and conn.execute(
                'SELECT 1 FROM native_rows WHERE id=?', (captured.get('id'),)).fetchone()
            if not source_exists and not candidates:
                child['duplicate_of'] = parent['message_id']
                child['counting_evidence'] = saved['counting_evidence']
                continue
            # A durable snapshot survives pruning, never contradictory live work.
            # A changed or moved source must not silently generate a fresh proof.
            if (not source_exists or len(candidates) != 1
                    or any(candidates[0].get(k) != v for k, v in captured.items())):
                continue
        if len(candidates) != 1:
            continue
        job = candidates[0]
        if (job['checked'] != 'true' or not (job['link'] or '').strip()
                or job['message_id'] not in (parent['message_id'], child['message_id'])
                or _day(job['confirmed_at']) != day):
            continue
        # Reserve claims across metadata too; one receipt cannot prove two rows.
        if sum(j['message_id'] == job['message_id'] for j in jobs) != 1:
            continue
        assigned = conn.execute('''SELECT 1 FROM bidder_assignments WHERE bidder_id=?
            AND account_id=? AND start_date<=? AND (end_date IS NULL OR end_date>=?) LIMIT 1''',
            (job['bidder_id'], account, day.isoformat(), day.isoformat())).fetchone()
        if not assigned:
            continue
        evidence = {'policy_version': _POLICY, 'day': day.isoformat(),
                    'parent': _signature(parent), 'child': _signature(child),
                    'job_identity': {k: job[k] for k in ('id','work_date','bidder_id','account_id','link','message_id','confirmed_at')}}
        child['duplicate_of'] = parent['message_id']
        child['counting_evidence'] = json.dumps(evidence, sort_keys=True, separators=(',', ':'))
    return rows, original


def effective_receipts(conn, start: date, end: date, *, account_id=None) -> list[dict]:
    """Return raw ACK ledger rows with effective copy flags, without any writes."""
    rows, _ = _effective(conn, start, end, account_id)
    return [r for r in rows if r['category'] == 'application_ack']


def materialize(conn, start: date, end: date, *, account_id=None) -> int:
    """Store changed proofs and clear stale flags, including reclassified rows."""
    rows, original = _effective(conn, start, end, account_id)
    changed = 0
    for row in rows:
        old = original[(row['account_id'], row['message_id'])]
        if (row['duplicate_of'], row['counting_evidence']) != (old['duplicate_of'], old['counting_evidence']):
            conn.execute('''UPDATE application_receipts SET duplicate_of=?,counting_evidence=?
                WHERE account_id=? AND message_id=?''',
                (row['duplicate_of'], row['counting_evidence'], row['account_id'], row['message_id']))
            changed += 1
    return changed
