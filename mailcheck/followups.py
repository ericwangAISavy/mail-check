"""Read-only follow-up discovery and local, explicit snooze/dismiss controls."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field

from . import db, interview_processes, interviews

SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_followup_state (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    snoozed_until TEXT,
    contact_snapshot TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class FollowupAction(BaseModel):
    action: Literal['snooze', 'dismiss', 'restore']
    days: int = Field(default=3, ge=1, le=30)


def _now():
    return datetime.now(timezone.utc)


def _instant(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _business_days(start, end):
    """Count weekdays after the anchor date through today's UTC date."""
    days = max(0, (end.date() - start.date()).days)
    weeks, remainder = divmod(days, 7)
    return weeks * 5 + sum((start.weekday() + offset) % 7 < 5 for offset in range(1, remainder + 1))


def _table(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def _threshold(conn, account_id):
    if _table(conn, 'agent_preferences'):
        row = conn.execute('SELECT settings FROM agent_preferences WHERE account_id=?', (account_id,)).fetchone()
        if row:
            try:
                value = json.loads(row['settings']).get('followup_business_days', 3)
                if isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= 30:
                    return value
            except (ValueError, TypeError, AttributeError):
                pass
    return 3


def _related_pks(all_mail, pks, account_id):
    seeds = [m for m in all_mail if m['id'] in pks and m['account_id'] == account_id]
    threads = {m['thread_id'] for m in seeds if m.get('thread_id')}
    identifiers = {m['message_id'] for m in seeds}
    result = set(pks)
    for m in all_mail:
        if m['account_id'] != account_id:
            continue
        try:
            references = json.loads(m.get('references_json') or '[]')
        except (ValueError, TypeError):
            references = []
        if m.get('thread_id') in threads or isinstance(references, list) and any(r in identifiers for r in references):
            result.add(m['id'])
    return result


def _snapshot(messages):
    values = sorted((m['id'], m['message_id'], m['contact_at']) for m in messages)
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()


def list_followups(conn, account_id=None, now=None):
    now = _instant(now.isoformat()) if isinstance(now, datetime) else _instant(now)
    now = now or _now()
    accounts = {a.id: a for a in db.list_accounts(conn, only_enabled=True)}
    all_mail = [dict(row) for row in conn.execute('''SELECT m.*, COALESCE(m.date_utc,m.fetched_at) AS contact_at,
        c.category,c.company,c.role FROM messages m LEFT JOIN classifications c ON c.id=(
        SELECT id FROM classifications WHERE message_pk=m.id ORDER BY created_at DESC,id DESC LIMIT 1)''')]
    mail = {m['id']: m for m in all_mail}
    groups = interview_processes.list_processes(conn, now=now)
    # Retained interview-classified mail is evidence even without a booked event.
    own = {a.email for a in db.list_accounts(conn)}
    for m in all_mail:
        if m['category'] != 'interview_invite' or m['account_id'] not in accounts:
            continue
        domains = interview_processes.organization_domains([], m['from_addr'], own_emails=own)
        if len(domains) != 1:
            continue
        org = domains[0]
        state = conn.execute('SELECT removed FROM interview_account_process_state WHERE organization=? AND account_id=?', (org, m['account_id'])).fetchone()
        removed = state['removed'] if state and state['removed'] is not None else bool(conn.execute('SELECT 1 FROM interview_process_removals WHERE organization=?', (org,)).fetchone())
        if removed:
            continue
        represented = any(p['account_id'] == m['account_id'] and (
            p['organization'] == org or any(
                source['message_pk'] == m['id'] and source['account_id'] == m['account_id']
                for event in p['events'] for source in interviews.event_sources(conn, event['id'])))
            for p in groups)
        # Removed events cannot be recreated from their retained source email.
        removed_source = conn.execute('''SELECT 1 FROM interview_sources s JOIN interview_event_removals r ON r.event_id=s.event_id
            WHERE s.account_id=? AND s.message_pk=?''', (m['account_id'], m['id'])).fetchone()
        if not represented and not removed_source:
            groups.append({'id': f"{m['account_id']}:{org}", 'account_id': m['account_id'], 'organization': org, 'events': [], 'milestones': []})
    items = []
    for p in groups:
        aid = p['account_id']
        if aid not in accounts or account_id is not None and aid != account_id:
            continue
        pks = {int(m['id'].split(':')[1]) for m in p['milestones'] if m['kind'] == 'message'}
        event_ids = [e['id'] for e in p['events']]
        for eid in event_ids:
            pks.update(s['message_pk'] for s in interviews.event_sources(conn, eid) if s['account_id'] == aid and s['message_pk'] is not None)
        for m in all_mail:
            domains = interview_processes.organization_domains([], m['from_addr'], own_emails=own)
            if m['account_id'] == aid and domains == [p['organization']]:
                pks.add(m['id'])
        pks = _related_pks(all_mail, pks, aid)
        messages = [mail[pk] for pk in pks if pk in mail and mail[pk]['account_id'] == aid and _instant(mail[pk]['contact_at']) and _instant(mail[pk]['contact_at']) <= now]
        evidence_mail = [m for m in messages if m['category'] == 'interview_invite']
        eligible = []
        for e in p['events']:
            start = _instant(e['start_at'])
            end = _instant(e.get('end_at')) or start
            if e['status'] == 'Cancelled' or not start or end > now:
                continue
            text = ' '.join(str(e.get(k) or '') for k in ('stage', 'notes', 'company'))
            if e.get('stage') != 'Other' or interviews.INTERVIEW_CONTEXT.search(text) or evidence_mail:
                eligible.append(e)
        if not eligible and not evidence_mail:
            continue
        # A cancelled/future event must not be resurrected by its invitation email.
        if p['events'] and not eligible:
            continue
        last = max(eligible, key=lambda e: _instant(e['start_at'])) if eligible else None
        interview_at = _instant(last['start_at']) if last else None
        latest = max(messages, key=lambda m: (_instant(m['contact_at']), m['id'])) if messages else None
        contacts = [_instant(m['contact_at']) for m in messages]
        sent = []
        if messages and _table(conn, 'mail_replies'):
            for m in messages:
                for r in conn.execute("SELECT sent_at FROM mail_replies WHERE message_pk=? AND account_id=? AND original_message_id=? AND status='sent'", (m['id'], aid, m['message_id'])):
                    stamp = _instant(r['sent_at'])
                    if stamp and stamp <= now:
                        sent.append(stamp)
        contact_at = max(contacts + sent, default=None)
        anchor = max([t for t in (interview_at, contact_at) if t is not None])
        elapsed = _business_days(anchor, now)
        status = 'suggested' if elapsed >= _threshold(conn, aid) else 'awaiting_response'
        reason = 'Review the past scheduled interview and conversation before following up.' if last and last['status'] != 'Completed' else 'Review the interview conversation before following up.'
        if status == 'awaiting_response':
            reason = 'Waiting for a response after recent interview or contact.'
        if latest is None:
            reason += ' No retained message is available to reply to.'
        if latest and _table(conn, 'agent_drafts'):
            draft = conn.execute('SELECT created_at FROM agent_drafts WHERE message_pk=? AND account_id=? AND original_message_id=? AND length(trim(body))>0 ORDER BY created_at DESC LIMIT 1', (latest['id'], aid, latest['message_id'])).fetchone()
            if draft and (_instant(draft['created_at']) or anchor) >= anchor:
                status = 'draft_ready'
        snoozed_until = None
        state = conn.execute('SELECT * FROM agent_followup_state WHERE id=?', (p['id'],)).fetchone()
        if state and state['contact_snapshot'] == _snapshot(messages):
            if state['status'] == 'dismissed':
                status = 'dismissed'
            elif _instant(state['snoozed_until']) and _instant(state['snoozed_until']) > now:
                status, snoozed_until = 'snoozed', state['snoozed_until']
        items.append(dict(id=p['id'], account_id=aid, account_label=accounts[aid].label,
            company=(last or {}).get('company') or (latest or {}).get('company') or p['organization'],
            role=(last or {}).get('role') or (latest or {}).get('role'),
            last_interview_at=interview_at.isoformat() if interview_at else None,
            last_contact_at=contact_at.isoformat() if contact_at else None,
            elapsed_business_days=elapsed, status=status, reason=reason,
            target_message_pk=latest['id'] if latest else None, snoozed_until=snoozed_until))
    return {'items': items, 'accounts': [dict(id=a.id, label=a.label, email=a.email) for a in accounts.values()],
            'threshold_business_days': _threshold(conn, account_id) if account_id is not None else 3}


def update_state(conn, key: str, body: FollowupAction) -> None:
    item = next((item for item in list_followups(conn)['items'] if item['id'] == key), None)
    if item is None:
        raise ValueError('Follow-up item not found')
    if body.action == 'restore':
        conn.execute('DELETE FROM agent_followup_state WHERE id=?', (key,))
        return
    # Snapshot exactly the same scoped inbound set used by discovery.
    now = _now()
    # Persist the inbound fingerprint, so a new response restores discovery.
    snapshot = _item_snapshot(conn, key, now)
    conn.execute('''INSERT INTO agent_followup_state(id,status,snoozed_until,contact_snapshot,updated_at)
        VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,
        snoozed_until=excluded.snoozed_until,contact_snapshot=excluded.contact_snapshot,updated_at=excluded.updated_at''',
        (key, 'snoozed' if body.action == 'snooze' else 'dismissed',
         (now + timedelta(days=body.days)).isoformat() if body.action == 'snooze' else None, snapshot, now.isoformat()))


def _item_snapshot(conn, key, now):
    # Capture discovery's fingerprint without persisting anything on a GET.
    aid, org = key.split(':', 1)
    own = {a.email for a in db.list_accounts(conn)}
    pks = set()
    for p in interview_processes.list_processes(conn, now=now):
        if p['id'] == key:
            pks.update(int(m['id'].split(':')[1]) for m in p['milestones'] if m['kind'] == 'message')
            for e in p['events']:
                pks.update(s['message_pk'] for s in interviews.event_sources(conn, e['id']) if s['account_id'] == int(aid))
    all_mail = [dict(row) for row in conn.execute('SELECT *,COALESCE(date_utc,fetched_at) AS contact_at FROM messages WHERE account_id=?', (int(aid),))]
    pks.update(m['id'] for m in all_mail if interview_processes.organization_domains([], m['from_addr'], own_emails=own) == [org])
    pks = _related_pks(all_mail, pks, int(aid))
    messages = []
    for row in all_mail:
        m = dict(row)
        if (m['id'] in pks or interview_processes.organization_domains([], m['from_addr'], own_emails=own) == [org]) and _instant(m['contact_at']) and _instant(m['contact_at']) <= now:
            messages.append(m)
    return _snapshot(messages)
