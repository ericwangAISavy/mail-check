"""Read-only, account-scoped suggestions from sparse native sourcing history.

Confidence describes evidence quality, not a statistical probability. The scan retains
only one page of ranked matches; historical rows are never loaded as editor snapshots.
"""
import base64
from datetime import datetime, timezone
from difflib import SequenceMatcher
import heapq
import html
import json
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

_ZONE = ZoneInfo('America/Chicago')
_GENERIC = {'a', 'an', 'the', 'at', 'for', 'of', 'and', 'or', 'senior', 'junior', 'lead', 'staff', 'principal', 'ii', 'iii'}
_BROAD_ROLE = {'engineer', 'engineering', 'developer', 'development', 'software', 'specialist', 'analyst', 'manager', 'architect', 'administrator', 'consultant', 'associate', 'professional', 'position', 'role'}
_SUFFIXES = {'inc', 'incorporated', 'llc', 'ltd', 'limited', 'corp', 'corporation', 'company', 'co'}
_GENERIC_COMPANY = {'unknown', 'confidential', 'company', 'client', 'staffing', 'recruitment', 'recruiting', 'recruiter', 'undisclosed', 'n a', 'na', 'none', 'not specified', 'not provided', 'hiring company'}
_URL = re.compile(r'https?://[^\s<>"\']+', re.I)


def _normal(value):
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', str(value or '')).casefold()))


def _company(value):
    return ' '.join(w for w in _normal(value).split() if w not in _SUFFIXES)


def _tokens(value):
    return set(_normal(value).split()) - _GENERIC


def _safe_url(value):
    value = html.unescape(str(value or '')).strip()
    if not value or len(value) > 4000 or re.search(r'[\x00-\x20\x7f]', value):
        return None
    try:
        p = urlsplit(value)
        if p.scheme.lower() not in ('http', 'https') or not p.hostname or p.username is not None or p.password is not None:
            return None
        _ = p.port
        query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith('utm_') and k.lower() not in ('gclid', 'fbclid')]
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', urlencode(sorted(query)), p.fragment))
    except ValueError:
        return None


def _date(value):
    try:
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return (stamp.replace(tzinfo=_ZONE) if stamp.tzinfo is None else stamp).astimezone(_ZONE).date()
    except (ValueError, TypeError):
        return None


def _cursor(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 2048:
            raise ValueError()
        result = json.loads(base64.urlsafe_b64decode(value + '=' * (-len(value) % 4)))
        if (not isinstance(result, list) or len(result) != 4 or type(result[0]) is not int
                or type(result[1]) is not int or result[1] not in (0, 1)
                or not isinstance(result[2], str) or not isinstance(result[3], str)
                or len(result[2]) > 32 or len(result[3]) > 512):
            raise ValueError()
        return tuple(result)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ValueError('Invalid job match cursor') from exc


def _evidence(conn, event, source):
    chunks = [str(source.get(k) or '')[:16384] for k in ('source_subject', 'source_sender', 'body_text', 'body', 'description')]
    if source.get('message_pk'):
        message = conn.execute('SELECT body_text,snippet FROM messages WHERE id=? AND account_id=?', (source['message_pk'], source['account_id'])).fetchone()
        if message:
            chunks.extend(str(v or '')[:16384] for v in message)
    if source.get('id') and conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='interview_source_details'").fetchone():
        detail = conn.execute('SELECT description FROM interview_source_details WHERE source_id=?', (source['id'],)).fetchone()
        if detail:
            chunks.append(str(detail[0] or '')[:16384])
    external = source.get('external_message_id')
    if external:
        task = conn.execute('SELECT booking FROM calendar_analysis_tasks WHERE account_id=? AND external_id=?', (source['account_id'], external)).fetchone()
        if task and task[0]:
            try:
                booking = json.loads(task[0])
                if isinstance(booking, dict):
                    chunks.append(str(booking.get('description') or '')[:16384])
            except (ValueError, TypeError):
                pass
    text = '\n'.join(chunks)[:32768]
    urls = {u for raw in _URL.findall(text) if (u := _safe_url(raw.rstrip('.,);]')))}
    dates = [_date(datetime.now(timezone.utc).isoformat()), _date(event.get('start_at')), _date(source.get('source_received_at'))]
    return {'text': _normal(text), 'urls': urls, 'cutoff': min(d for d in dates if d)}


def match_jobs(conn, event: dict, sources: list[dict], *, cursor: str | None = None, limit: int = 25) -> dict:
    """Suggest every plausible historical row, paginated by evidence and recency."""
    seek = _cursor(cursor)
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Job match limit must be between 1 and 100')
    scoped = {}
    for source in sources:
        if type(source.get('account_id')) is int and source['account_id'] > 0:
            scoped.setdefault(source['account_id'], []).append(_evidence(conn, event, source))
    if not scoped:
        return {'matches': [], 'total': 0, 'next_cursor': None}
    company = _company(event.get('company'))
    role = _tokens(event.get('role'))
    sql = """SELECT r.id AS row_id,r.tab_id,r.work_date,t.account_id,t.account_label,t.archived,
        b.bidder_id,COALESCE(p.name,'Historical bidder') AS bidder_name,
        company.value AS company,role.value AS role,link.value AS link,checked.value AS checked,
        e.confirmed_at,e.detected_at
        FROM native_tabs t JOIN native_books b ON b.id=t.book_id
        LEFT JOIN bidders p ON p.id=b.bidder_id JOIN native_rows r ON r.tab_id=t.id
        LEFT JOIN native_columns cc ON cc.tab_id=t.id AND cc.kind='company'
        LEFT JOIN native_columns rc ON rc.tab_id=t.id AND rc.kind='role'
        LEFT JOIN native_columns lc ON lc.tab_id=t.id AND lc.kind='link'
        LEFT JOIN native_columns kc ON kc.tab_id=t.id AND kc.kind='check'
        LEFT JOIN native_cells company ON company.row_id=r.id AND company.column_id=cc.id
        LEFT JOIN native_cells role ON role.row_id=r.id AND role.column_id=rc.id
        LEFT JOIN native_cells link ON link.row_id=r.id AND link.column_id=lc.id
        LEFT JOIN native_cells checked ON checked.row_id=r.id AND checked.column_id=kc.id
        LEFT JOIN sourcing_check_activity e ON e.row_id=r.id
        WHERE t.account_id IN (""" + ','.join('?' for _ in scoped) + ')'
    top = []
    total = 0
    for record in conn.execute(sql, tuple(scoped)):
        row = dict(record)
        link = _safe_url(row['link'])
        if not link:
            continue
        candidate_company = _company(row['company'])
        candidate_role = _tokens(row['role'])
        applied = str(row['checked'] or '').lower() == 'true'
        overlap = len(role & candidate_role)
        role_match = bool(overlap and overlap / max(1, min(len(role), len(candidate_role))) >= .5)
        role_specialties = role - _BROAD_ROLE
        candidate_specialties = candidate_role - _BROAD_ROLE
        role_conflict = bool(role and candidate_role and not overlap or
                             role_specialties and candidate_specialties and not (role_specialties & candidate_specialties))
        exact_company = bool(company and company == candidate_company)
        fuzzy = bool(company and candidate_company and min(len(company),len(candidate_company)) >= 5 and SequenceMatcher(None, company, candidate_company).ratio() >= .88)
        company_related = bool(exact_company or fuzzy or (company and candidate_company and
            ((' ' + company + ' ') in (' ' + candidate_company + ' ') or
             (' ' + candidate_company + ' ') in (' ' + company + ' '))))
        company_conflict = bool(company and candidate_company and company not in _GENERIC_COMPANY
                                and candidate_company not in _GENERIC_COMPANY and not company_related)
        best = None
        for evidence in scoped[row['account_id']]:
            explicit = link in evidence['urls']
            phrase = bool(candidate_company and len(candidate_company) >= 3 and (' '+candidate_company+' ') in (' '+evidence['text']+' '))
            text_role = bool(candidate_role & set(evidence['text'].split()))
            meaningful_company = candidate_company and candidate_company not in _GENERIC_COMPANY
            company_evidence = meaningful_company and (exact_company or phrase or (fuzzy and role_match))
            if not (explicit or (company_evidence and (not role or role_match or text_role))):
                continue
            confirmed = _date(row['confirmed_at'])
            work = _date(row['work_date'])
            observed = _date(row['detected_at']) if applied else None
            day = confirmed or (work if work and work <= evidence['cutoff'] else observed)
            if day and day > evidence['cutoff']:
                continue
            if not day and work:
                continue
            if not day and not (explicit or exact_company and role_match):
                continue
            strong = bool(day and (explicit or exact_company and role_match) and not role_conflict and not company_conflict)
            reasons = ['Matching job URL'] if explicit else [('Matching company' if exact_company else 'Company mentioned in invitation' if phrase else 'Similar company name')]
            if not explicit and (role_match or text_role):
                reasons.append('Matching role')
            elif not explicit:
                reasons.append('Invitation role unavailable')
            if company_conflict:
                reasons.append('Company differs from invitation')
            if role_conflict:
                reasons.append('Role differs from invitation')
            if day is None:
                reasons.append('Application date unavailable')
            if not applied:
                reasons.append('Saved link; application unverified')
            score = (100 if explicit else 70 if exact_company else 55 if phrase else 45) + (10 if role_match else 0)
            rank = (score, int(applied), day.isoformat() if day else '', row['row_id'])
            item = {k: row[k] for k in ('row_id','tab_id','account_id','account_label','bidder_id','bidder_name','company','role','work_date')}
            item.update(company=row['company'] or '', role=row['role'] or '', link=link, applied=applied,
                        application_date=day.isoformat() if day else None, archived=bool(row['archived']),
                        confidence='strong' if strong else 'possible', reasons=reasons)
            if best is None or rank > best[0]:
                best = (rank, item)
        if best is None:
            continue
        total += 1
        if seek is not None and best[0] >= seek:
            continue
        if len(top) < limit + 1:
            heapq.heappush(top, best)
        elif best[0] > top[0][0]:
            heapq.heapreplace(top, best)
    ordered = sorted(top, key=lambda x: x[0], reverse=True)
    page = ordered[:limit]
    next_cursor = None
    if len(ordered) > limit:
        next_cursor = base64.urlsafe_b64encode(json.dumps(page[-1][0], separators=(',', ':')).encode()).decode().rstrip('=')
    return {'matches': [item for _, item in page], 'total': total, 'next_cursor': next_cursor}
