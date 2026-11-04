"""Read-only receipt accounting. Suspected duplicates never erase evidence."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re
import unicodedata

from .sourcing_filters import company_key, role_key

ZONE = ZoneInfo('America/Chicago')
COUNTS = ('raw_receipts', 'verified_applications', 'possible_extra_confirmations',
          'unmatched_receipts', 'ambiguous_rows', 'counted_receipts', 'confirmed_platform_copies')


def link_key(value):
    """Remove tracking while retaining every potentially meaningful job ID."""
    value = value.strip()
    try:
        url = urlsplit(value)
        if url.scheme.lower() not in ('http', 'https') or not url.hostname:
            return value
        query = sorted((key, val) for key, val in parse_qsl(url.query, keep_blank_values=True)
                       if not key.lower().startswith('utm_') and key.lower() not in ('gclid', 'fbclid'))
        return urlunsplit(('https', url.netloc.lower(), url.path.rstrip('/'), urlencode(query), url.fragment))
    except ValueError:
        return value


def _day(stamp):
    try:
        value = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(ZONE).date()
    except (ValueError, TypeError, AttributeError):
        return None


def _metadata(company, role):
    # A blank role must never make every role at the company look duplicated.
    if not (company or '').strip() or not (role or '').strip():
        return None
    company = company_key(unicodedata.normalize('NFKC', company))
    role = unicodedata.normalize('NFKC', role).casefold().strip()
    role = re.sub(r'^sr\.?\s+', 'senior ', role)
    role = re.sub(r'^jr\.?\s+', 'junior ', role)
    role = role_key(role)
    return (company, role) if company and role else None


def reconcile(conn, start, end, *, bidder_id=None):
    """Partition weekly acknowledgements without changing receipts or saved checks.

    Explicit claims survive metadata disagreement, which is reported for review.
    A stored event whose Chicago date differs from its receipt needs review and
    receives no credit; this report never silently moves recorded completion dates.
    Conflicts include other bidders' claims, but scoped output exposes only the
    requested bidder's rows and assigned account/date receipts.
    """
    lower = datetime.combine(start, datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), ZONE).astimezone(timezone.utc).isoformat()
    assignments = defaultdict(list)
    active_bidders = {r['id'] for r in conn.execute('SELECT id FROM bidders WHERE removed_at IS NULL')}
    assignment_labels = {}
    for row in conn.execute('SELECT bidder_id,account_id,account_label,start_date,end_date FROM bidder_assignments'):
        if row['bidder_id'] in active_bidders:
            assignment_labels.setdefault(row['account_id'], row['account_label'] or 'Removed account')
            assignments[row['bidder_id'], row['account_id']].append((row['start_date'], row['end_date']))

    def assigned(who, account, day):
        return day is not None and any(first <= day.isoformat() and (last is None or last >= day.isoformat())
                                      for first, last in assignments[who, account])

    account_info = {r['id']: dict(r) for r in conn.execute('SELECT id,label,email FROM accounts')}
    visible = set(account_info) if bidder_id is None else {
        account for (who, account), periods in assignments.items() if who == bidder_id
        and any(first <= end.isoformat() and (last is None or last >= start.isoformat()) for first, last in periods)}
    from .receipt_counting import effective_receipts
    receipts = {(row['account_id'], row['message_id']): row
                for row in effective_receipts(conn, start, end)}
    def canonical(account, message):
        receipt = receipts.get((account, message))
        return (account, receipt['duplicate_of'] if receipt and receipt['duplicate_of'] else message)
    for account, _message in receipts:
        if bidder_id is None:
            visible.add(account)
        account_info.setdefault(account, {'id': account, 'label': assignment_labels.get(account, 'Removed account'), 'email': ''})
    for account in visible:
        account_info.setdefault(account, {'id': account, 'label': assignment_labels.get(account, 'Removed account'), 'email': ''})
    # Materialize IDs before loading cell values. A broad lexical confirmation
    # range can use the existing timestamp index; julianday remains authoritative
    # for mixed UTC offsets and Chicago/DST boundaries within that range.
    rows = conn.execute("""WITH weekly_receipts AS MATERIALIZED (
            SELECT account_id,message_id FROM application_receipts
            WHERE category='application_ack' AND julianday(received_at)>=julianday(?)
            AND julianday(received_at)<julianday(?)),
        candidate_ids AS MATERIALIZED (
            SELECT id FROM native_rows WHERE work_date BETWEEN ? AND ?
            UNION
            SELECT row_id FROM sourcing_check_activity
            WHERE confirmed_at>=? AND confirmed_at<?
            AND julianday(confirmed_at)>=julianday(?) AND julianday(confirmed_at)<julianday(?)
            UNION
            SELECT e.row_id FROM weekly_receipts a
            JOIN sourcing_check_activity e ON e.message_id=a.message_id
            JOIN native_rows nr ON nr.id=e.row_id JOIN native_tabs nt ON nt.id=nr.tab_id
            WHERE nt.account_id=a.account_id)
        SELECT r.id,r.work_date,t.account_id,b.bidder_id,
        e.message_id,e.confirmed_at,e.source,c.value AS company,p.value AS role,l.value AS link
        FROM candidate_ids candidates JOIN native_rows r ON r.id=candidates.id
        JOIN native_tabs t ON t.id=r.tab_id
        JOIN native_books b ON b.id=t.book_id
        JOIN native_columns ck ON ck.tab_id=t.id AND ck.kind='check'
        JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=ck.id AND checked.value='true'
        LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
        LEFT JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
        LEFT JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id
        LEFT JOIN native_columns pc ON pc.tab_id=t.id AND pc.kind='role'
        LEFT JOIN native_cells p ON p.row_id=r.id AND p.column_id=pc.id
        LEFT JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
        LEFT JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id
        """, (lower, upper, start.isoformat(), end.isoformat(),
              (start - timedelta(days=2)).isoformat(), (end + timedelta(days=3)).isoformat(),
              lower, upper)).fetchall()
    claims, links = defaultdict(list), defaultdict(set)
    for row in rows:
        if row['message_id']:
            claims[canonical(row['account_id'], row['message_id'])].append(row['id'])
        if (row['link'] or '').strip():
            links[row['account_id'], link_key(row['link'])].add(row['id'])
    # Historical checks can repeat this week's URL even when their receipt and
    # sourcing dates fall outside the window. Load only link identities from
    # relevant accounts; keep current-week rows as the sole reporting candidates.
    relevant_accounts = sorted({account for account, _link in links if account in visible})
    for offset in range(0, len(relevant_accounts), 500):
        batch = relevant_accounts[offset:offset + 500]
        placeholders = ','.join('?' for _ in batch)
        for historical in conn.execute("""SELECT r.id,t.account_id,l.value AS link
            FROM native_tabs t JOIN native_rows r ON r.tab_id=t.id
            JOIN native_columns ck ON ck.tab_id=t.id AND ck.kind='check'
            JOIN native_cells c ON c.row_id=r.id AND c.column_id=ck.id AND c.value='true'
            JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
            JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id AND trim(l.value)!=''
            WHERE t.account_id IN (""" + placeholders + ')', batch):
            identity = (historical['account_id'], link_key(historical['link']))
            if identity in links:
                links[identity].add(historical['id'])
    accounts = {}
    for identity in sorted(visible):
        if identity not in account_info:
            continue
        accounts[identity] = dict(account_id=identity, account_label=account_info[identity]['label'],
            bidder_ids=sorted({who for who, account in assignments if account == identity
                and (bidder_id is None or who == bidder_id)
                and any(first <= end.isoformat() and (last is None or last >= start.isoformat())
                        for first,last in assignments[who,account])}),
            **{key: 0 for key in COUNTS}, missing_metadata_receipts=0, duplicate_link_rows=0,
            conflicting_receipt_rows=0, review_reason_counts=Counter())
    bidders = {who: {'verified_daily': [0] * 7, 'verified_total': 0}
               for who in sorted(active_bidders) if bidder_id is None or who == bidder_id}
    verified = set()
    verified_metadata = defaultdict(set)
    for row in rows:
        account, who = row['account_id'], row['bidder_id']
        if account not in accounts or who not in bidders:
            continue
        claim = canonical(account, row['message_id'])
        receipt = receipts.get(claim)
        receipt_day = _day(receipt['received_at']) if receipt else None
        event_day = _day(row['confirmed_at'])
        if not (receipt_day and assigned(who, account, receipt_day)):
            review_day = event_day
            if review_day is None:
                try: review_day = datetime.fromisoformat(row['work_date']).date()
                except (ValueError, TypeError): continue
            if not start <= review_day <= end or not assigned(who, account, review_day):
                continue
        item = accounts[account]
        reasons = item['review_reason_counts']
        conflict = len(claims[claim]) > 1 if row['message_id'] else False
        duplicate = bool((row['link'] or '').strip()) and len(links[account, link_key(row['link'])]) > 1
        item['conflicting_receipt_rows'] += int(conflict)
        item['duplicate_link_rows'] += int(duplicate)
        item['ambiguous_rows'] += int(conflict or duplicate)
        for reason, applies in (('conflicting_receipt_rows', conflict), ('duplicate_link_rows', duplicate),
                ('manual_checks', not row['message_id']), ('missing_receipt_claims', not receipt),
                ('missing_job_links', not (row['link'] or '').strip()),
                ('receipt_date_mismatch_rows', bool(receipt and receipt_day != event_day)),
                ('unassigned_claim_rows', bool(receipt and not assigned(who, account, receipt_day)))):
            if applies: reasons[reason] += 1
        if receipt and _metadata(row['company'], row['role']) != _metadata(receipt['company'], receipt['role']):
            reasons['metadata_mismatch_rows'] += 1
        if not receipt or not assigned(who, account, receipt_day) or conflict or duplicate or not (row['link'] or '').strip() or receipt_day != event_day:
            continue
        verified.add(claim)
        metadata = _metadata(receipt['company'], receipt['role'])
        if metadata: verified_metadata[account].add(metadata)
        item['verified_applications'] += 1
        bidders[who]['verified_total'] += 1
        bidders[who]['verified_daily'][(receipt_day-start).days] += 1
    for claim, receipt in receipts.items():
        account = claim[0]
        if account not in accounts or (bidder_id is not None and not assigned(bidder_id, account, _day(receipt['received_at']))):
            continue
        item = accounts[account]
        item['raw_receipts'] += 1
        if receipt['duplicate_of']:
            item['confirmed_platform_copies'] += 1
            continue
        item['counted_receipts'] += 1
        metadata = _metadata(receipt['company'], receipt['role'])
        if not metadata:
            item['missing_metadata_receipts'] += 1
            item['review_reason_counts']['missing_metadata_receipts'] += 1
        if claim in verified: continue
        extra = not claims[claim] and metadata and metadata in verified_metadata[account]
        item['possible_extra_confirmations' if extra else 'unmatched_receipts'] += 1
    emails = Counter(account_info[a]['email'].strip().casefold() for a in accounts if account_info[a]['email'].strip())
    return {**{key: sum(a[key] for a in accounts.values()) for key in COUNTS},
            'duplicate_connection_groups': sum(count > 1 for count in emails.values()),
            'accounts': list(accounts.values()), 'bidders': bidders}
