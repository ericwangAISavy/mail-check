"""Organization timelines derived from saved calendar event identities."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parseaddr

from . import db, interviews

SERVICE_DOMAINS = ("google.com", "teams.microsoft.com", "teams.live.com", "teams.com", "zoom.us", "zoom.com")
DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
SCHEMA = """
CREATE TABLE IF NOT EXISTS interview_process_pins (
    organization TEXT PRIMARY KEY NOT NULL,
    pinned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_process_removals (
    organization TEXT PRIMARY KEY NOT NULL,
    removed_at TEXT NOT NULL
);
"""


def _organization_key(organization: str | None) -> str:
    key = organization.strip().casefold() if organization else ""
    if key and not DOMAIN.fullmatch(key):
        raise ValueError("Use a valid organization domain")
    return key


def set_pin(conn, organization: str | None, pinned: bool) -> None:
    key = _organization_key(organization)
    if pinned:
        conn.execute("INSERT INTO interview_process_pins(organization,pinned_at) VALUES(?,?) ON CONFLICT(organization) DO NOTHING", (key, db._now()))
    else:
        conn.execute("DELETE FROM interview_process_pins WHERE organization=?", (key,))


def set_removed(conn, organization: str | None, removed: bool) -> None:
    key = _organization_key(organization)
    if removed:
        conn.execute("INSERT INTO interview_process_removals(organization,removed_at) VALUES(?,?) ON CONFLICT(organization) DO NOTHING", (key, db._now()))
    else:
        conn.execute("DELETE FROM interview_process_removals WHERE organization=?", (key,))


def list_removed(conn) -> list[dict]:
    return [{"organization": row["organization"] or None, "removed_at": row["removed_at"]}
            for row in conn.execute("SELECT * FROM interview_process_removals ORDER BY removed_at DESC,organization")]


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def organization_domains(participants: list[str], organizer: str | None, *, own_emails: set[str]) -> list[str]:
    """Preserve the full domain; multiple distinct domains remain ambiguous."""
    own = {email.strip().casefold() for email in own_emails}
    domains = set()
    for value in [*participants, organizer]:
        if not isinstance(value, str):
            continue
        address = parseaddr(value.removeprefix("mailto:"))[1].casefold()
        if address in own or address.count("@") != 1:
            continue
        local, domain = address.rsplit("@", 1)
        if not local or not DOMAIN.fullmatch(domain):
            continue
        if any(domain == service or domain.endswith("." + service) for service in SERVICE_DOMAINS):
            continue
        domains.add(domain)
    return sorted(domains)


def list_processes(conn, *, now: datetime | None = None) -> list[dict]:
    """Existing and newly collected events share groups without duplicate storage."""
    now = now or datetime.now(timezone.utc)
    own = {account.email for account in db.list_accounts(conn)}
    groups: dict[str | None, dict] = {}
    pins = {row[0] for row in conn.execute("SELECT organization FROM interview_process_pins")}
    removed = {row[0] for row in conn.execute("SELECT organization FROM interview_process_removals")}
    labels: dict[int, list[str]] = {}
    for source in conn.execute("SELECT DISTINCT s.event_id,a.label FROM interview_sources s JOIN accounts a ON a.id=s.account_id WHERE a.enabled=1 ORDER BY a.label"):
        labels.setdefault(source["event_id"], []).append(source["label"])
    for event in interviews.list_events(conn, now=now):
        # Match the Interview page's calendar evidence boundary.
        if event["extraction_rank"] < 2 or not event["start_at"]:
            continue
        domains = organization_domains(event["participants"], event["organizer_email"], own_emails=own)
        organization = domains[0] if len(domains) == 1 else None
        if (organization or "") in removed:
            continue
        event["organization_domains"] = domains
        event["assignment_reason"] = None if organization else "Multiple organization domains" if domains else "No eligible organization domain"
        event["account_labels"] = labels.get(event["id"], [])
        group = groups.setdefault(organization, {"organization": organization, "events": [], "milestones": [], "message_count": 0, "pinned": (organization or "") in pins})
        group["events"].append(event)
        group["milestones"].append({
            "id": f"event:{event['id']}", "kind": "event", "occurred_at": event["start_at"],
            "title": event["company"] or event["stage"], "summary": (event["notes"] or "")[:1000],
            "status": event["display_status"], "sender": event["organizer_email"],
            "account_labels": event["account_labels"], "href": f"/interviews?event={event['id']}",
            "organization_domains": domains, "assignment_reason": event["assignment_reason"],
        })

    # Add saved mail only to an established calendar organization. A newsletter
    # alone must not create an interview process. No mailbox or model calls.
    messages = conn.execute("""SELECT m.id,m.from_addr,m.subject,
        COALESCE(m.date_utc,m.fetched_at) AS occurred_at,
        substr(COALESCE(NULLIF(c.summary,''),NULLIF(m.snippet,''),m.body_text,''),1,1000) AS summary,
        m.provider_url,a.label,c.category
        FROM messages m JOIN accounts a ON a.id=m.account_id AND a.enabled=1
        LEFT JOIN classifications c ON c.id=(SELECT id FROM classifications
            WHERE message_pk=m.id ORDER BY created_at DESC,id DESC LIMIT 1)
        ORDER BY m.id"""
    )
    for message in messages:
        domains = organization_domains([], message["from_addr"], own_emails=own)
        if len(domains) != 1 or domains[0] not in groups:
            continue
        try:
            occurred_at = _instant(message["occurred_at"]).isoformat()
        except (TypeError, ValueError):
            continue
        group = groups[domains[0]]
        group["message_count"] += 1
        group["milestones"].append({
            "id": f"message:{message['id']}", "kind": "message", "occurred_at": occurred_at,
            "title": message["subject"] or "(No subject)", "summary": message["summary"][:1000],
            "status": "Email", "sender": message["from_addr"], "account_labels": [message["label"]],
            "href": interviews.safe_url(message["provider_url"]),
            "organization_domains": domains, "assignment_reason": None,
        })

    result = []
    for key in sorted(groups, key=lambda value: (value is None, value or "")):
        group = groups[key]
        group["events"].sort(key=lambda event: (datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")), event["id"]))
        group["event_count"] = len(group["events"])
        group["milestones"].sort(key=lambda milestone: (_instant(milestone["occurred_at"]), milestone["id"]))
        group["next_interview"] = next((event for event in group["events"] if event["display_status"] in ("Scheduled", "Rescheduled") and datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")) >= now), None)
        result.append(group)
    return sorted(result, key=lambda group: not group["pinned"])
