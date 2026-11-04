"""Conservative receipt ownership: ambiguous mail never checks several jobs."""
from collections import defaultdict
from datetime import datetime, timedelta
from .payments import ZONE


def unique_matches(conn, proposals, *, early_since):
    """Filter row_id -> (received UTC datetime, message_id) without writing data.

    Inspect other active tabs too, even for a single-tab check. Existing checked
    claims reserve a receipt across historical source dates. Several candidate
    jobs with the same metadata require review; email count alone cannot tell
    duplicate confirmations from separate applications.
    """
    if not proposals:
        return {}
    from .sourcing_verification import company_key, match_key, receipt_match
    ids = list(proposals)
    row_accounts = {}
    for offset in range(0, len(ids), 400):
        chunk = ids[offset:offset + 400]
        for row in conn.execute('SELECT r.id,t.account_id FROM native_rows r JOIN native_tabs t ON t.id=r.tab_id '
                                'WHERE r.id IN (' + ','.join('?' for _ in chunk) + ')', chunk):
            row_accounts[row['id']] = row['account_id']
    wanted = {(row_accounts[row], match[1]) for row, match in proposals.items() if row in row_accounts}
    receipts = {}
    pairs = list(wanted)
    for offset in range(0, len(pairs), 300):
        chunk = pairs[offset:offset + 300]
        sql = 'SELECT account_id,message_id,company,role FROM application_receipts WHERE category=\'application_ack\' AND (account_id,message_id) IN (' + ','.join('(?,?)' for _ in chunk) + ')'
        for row in conn.execute(sql, [value for pair in chunk for value in pair]):
            receipts[row['account_id'], row['message_id']] = row
    accounts = sorted({account for account, _ in wanted if account is not None})
    lower = (min(value[0].astimezone(ZONE).date() for value in proposals.values()) - timedelta(days=6)).isoformat()
    candidates = defaultdict(list)
    reservations = defaultdict(set)
    for offset in range(0, len(accounts), 400):
        chunk = accounts[offset:offset + 400]
        marks = ','.join('?' for _ in chunk)
        for row in conn.execute("""WITH candidate_rows AS MATERIALIZED (
            SELECT id,tab_id,work_date FROM native_rows WHERE work_date>=?
            AND tab_id IN (SELECT id FROM native_tabs WHERE account_id IN (""" + marks + "))" + """
            ) SELECT r.id,r.work_date,t.account_id,c.value AS company,p.value AS role
            FROM candidate_rows r JOIN native_tabs t ON t.id=r.tab_id
            JOIN native_books b ON b.id=t.book_id JOIN bidders bidder ON bidder.id=b.bidder_id
            JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
            JOIN native_columns pc ON pc.tab_id=t.id AND pc.kind='role'
            JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
            LEFT JOIN native_cells c ON c.row_id=r.id AND c.column_id=cc.id
            LEFT JOIN native_cells p ON p.row_id=r.id AND p.column_id=pc.id
            JOIN native_cells l ON l.row_id=r.id AND l.column_id=lc.id AND trim(l.value)!=''
            WHERE t.archived=0 AND bidder.removed_at IS NULL""", [lower, *chunk]):
            candidates[row['account_id'], company_key(row['company'])].append(row)
        messages = list({message for account, message in wanted if account in chunk})
        for batch_start in range(0, len(messages), 300):
            batch = messages[batch_start:batch_start + 300]
            for row in conn.execute("""WITH claimed AS MATERIALIZED (
                SELECT row_id,message_id FROM sourcing_check_activity WHERE message_id IN (""" + ','.join('?' for _ in batch) + ")" + """
                ) SELECT e.row_id,e.message_id,t.account_id FROM claimed e
                JOIN native_rows r ON r.id=e.row_id JOIN native_tabs t ON t.id=r.tab_id
                JOIN native_columns col ON col.tab_id=t.id AND col.kind='check'
                JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=col.id AND checked.value='true'
                WHERE t.account_id IN (""" + marks + ')', [*batch, *chunk]):
                identity = row['account_id'], row['message_id']
                if identity in wanted:
                    reservations[identity].add(row['row_id'])
    proposed_rows = defaultdict(set)
    for row_id, proposal in proposals.items():
        proposed_rows[row_accounts.get(row_id), proposal[1]].add(row_id)
    accepted = {}
    candidate_cache = {}
    for row_id, proposal in proposals.items():
        identity = row_accounts.get(row_id), proposal[1]
        receipt = receipts.get(identity)
        if receipt is None:
            continue
        if identity not in candidate_cache:
            received_day = proposal[0].astimezone(ZONE).date()
            metadata = match_key(receipt['company'], receipt['role'])
            if metadata is None:
                continue
            lookup = {metadata: proposal}
            possible = reservations[identity] | proposed_rows[identity]
            for row in candidates[identity[0], company_key(receipt['company'])]:
                try:
                    work_day = datetime.fromisoformat(row['work_date']).date()
                except (TypeError, ValueError):
                    continue
                within_window = 0 <= (received_day - work_day).days <= 6
                early = work_day > received_day and received_day >= early_since
                if (within_window or early) and receipt_match(row['company'], row['role'], lookup):
                    possible.add(row['id'])
            candidate_cache[identity] = possible
        possible = candidate_cache[identity] | {row_id}
        # Include the explicitly selected candidate (e.g. archived week rebuild)
        # while still reserving claims made in any other tab/date.
        if possible == {row_id}:
            accepted[row_id] = proposal
    return accepted
