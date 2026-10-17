"""Manual name matching and domain-based timelines from saved events and mail."""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from email.utils import parseaddr

from . import db, interviews
from .normalize import _html_to_text

SERVICE_DOMAINS = ("google.com", "teams.microsoft.com", "teams.live.com", "teams.com", "zoom.us", "zoom.com")
DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")
SCHEMA = """
CREATE TABLE IF NOT EXISTS interview_manual_processes (
    organization TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_process_pins (
    organization TEXT PRIMARY KEY NOT NULL,
    pinned_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interview_process_removals (
    organization TEXT PRIMARY KEY NOT NULL,
    removed_at TEXT NOT NULL
);
"""


def create_process(conn, name: str) -> None:
    name = " ".join(name.split())
    if not name or len(name) > 253 or not re.search(r"[^\W_]", name):
        raise ValueError("Enter a company or organization name (up to 253 characters)")
    key = name.casefold()
    try:
        conn.execute("INSERT INTO interview_manual_processes(organization,name,created_at) VALUES(?,?,?)", (key, name, db._now()))
    except sqlite3.IntegrityError:
        raise ValueError("An interview process with this name already exists") from None
    conn.execute("DELETE FROM interview_process_removals WHERE organization=?", (key,))


def _manual_matches(manual: dict[str, str], text: str) -> list[str]:
    text = text.casefold()
    return [key for key, name in manual.items()
            if any(piece in text for piece in re.findall(r"[^\W_]+", name.casefold()))]


def _organization_key(conn, organization: str | None) -> str:
    key = organization.strip().casefold() if organization else ""
    if key and not DOMAIN.fullmatch(key) and not conn.execute("SELECT 1 FROM interview_manual_processes WHERE organization=?", (key,)).fetchone():
        raise ValueError("Use a valid organization domain")
    return key


def set_pin(conn, organization: str | None, pinned: bool) -> None:
    key = _organization_key(conn, organization)
    if pinned:
        conn.execute("INSERT INTO interview_process_pins(organization,pinned_at) VALUES(?,?) ON CONFLICT(organization) DO NOTHING", (key, db._now()))
    else:
        conn.execute("DELETE FROM interview_process_pins WHERE organization=?", (key,))


def set_removed(conn, organization: str | None, removed: bool) -> None:
    key = _organization_key(conn, organization)
    if removed:
        conn.execute("INSERT INTO interview_process_removals(organization,removed_at) VALUES(?,?) ON CONFLICT(organization) DO NOTHING", (key, db._now()))
    else:
        conn.execute("DELETE FROM interview_process_removals WHERE organization=?", (key,))


def list_removed(conn) -> list[dict]:
    return [{"organization": row["name"] or row["organization"] or None, "removed_at": row["removed_at"]}
            for row in conn.execute("SELECT r.*,m.name FROM interview_process_removals r LEFT JOIN interview_manual_processes m USING(organization) ORDER BY removed_at DESC,organization")]


def _preview_summary(value: str | None) -> str:
    """Normalize saved HTML before truncation; never render provider markup."""
    text = value or ""
    if re.search(r"</?(?:html|head|body|div|span|p|br|a|ul|ol|li|table|tr|td|th|strong|em|b|i|script|style)\b", text, re.I):
        text = _html_to_text(text).strip()
    return text[:1000]


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
    manual = {row["organization"]: row["name"] for row in conn.execute("SELECT organization,name FROM interview_manual_processes")}
    def group_for(key):
        return groups.setdefault(key, {"organization": manual.get(key, key), "events": [], "milestones": [], "message_count": 0, "pinned": (key or "") in pins})
    for key in manual:
        if key not in removed:
            group_for(key)
    labels: dict[int, list[str]] = {}
    for source in conn.execute("SELECT DISTINCT s.event_id,a.label FROM interview_sources s JOIN accounts a ON a.id=s.account_id WHERE a.enabled=1 ORDER BY a.label"):
        labels.setdefault(source["event_id"], []).append(source["label"])
    for event in interviews.list_events(conn, now=now):
        # Match the Interview page's calendar evidence boundary.
        if event["extraction_rank"] < 2 or not event["start_at"]:
            continue
        domains = organization_domains(event["participants"], event["organizer_email"], own_emails=own)
        organization = domains[0] if len(domains) == 1 else None
        matches = _manual_matches(manual, " ".join(str(event.get(field) or "") for field in
            ("company", "role", "stage", "notes", "organizer_email", "participants", "location")))
        if matches:
            organization = matches[0] if len(matches) == 1 else None
        if (organization or "") in removed:
            continue
        event["organization_domains"] = domains
        event["assignment_reason"] = "Multiple matching manual processes" if len(matches) > 1 else None if organization else "Multiple organization domains" if domains else "No eligible organization domain"
        event["account_labels"] = labels.get(event["id"], [])
        group = group_for(organization)
        group["events"].append(event)
        group["milestones"].append({
            "id": f"event:{event['id']}", "kind": "event", "occurred_at": event["start_at"],
            "title": event["company"] or event["stage"], "summary": _preview_summary(event["notes"]),
            "status": event["display_status"], "sender": event["organizer_email"],
            "account_labels": event["account_labels"], "href": f"/interviews?event={event['id']}",
            "organization_domains": domains, "assignment_reason": event["assignment_reason"],
        })

    # Manual names can match saved mail without a calendar event. Domain-only
    # mail still requires an established calendar group. No provider/model calls.
    messages = conn.execute("""SELECT m.id,m.from_addr,m.from_name,m.subject,m.body_text,m.snippet,c.summary AS classification_summary,
        COALESCE(m.date_utc,m.fetched_at) AS occurred_at,
        COALESCE(NULLIF(c.summary,''),NULLIF(m.snippet,''),m.body_text,'') AS summary,
        m.provider_url,a.label,c.category
        FROM messages m JOIN accounts a ON a.id=m.account_id AND a.enabled=1
        LEFT JOIN classifications c ON c.id=(SELECT id FROM classifications
            WHERE message_pk=m.id ORDER BY created_at DESC,id DESC LIMIT 1)
        ORDER BY m.id"""
    )
    for message in messages:
        domains = organization_domains([], message["from_addr"], own_emails=own)
        matches = _manual_matches(manual, " ".join(str(message[field] or "") for field in
            ("from_addr", "from_name", "subject", "body_text", "snippet", "classification_summary")))
        organization = matches[0] if len(matches) == 1 else None if matches else domains[0] if len(domains) == 1 else None
        if (organization or "") in removed:
            continue
        if not matches and (organization is None or organization not in groups):
            continue
        try:
            occurred_at = _instant(message["occurred_at"]).isoformat()
        except (TypeError, ValueError):
            continue
        group = group_for(organization)
        group["message_count"] += 1
        group["milestones"].append({
            "id": f"message:{message['id']}", "kind": "message", "occurred_at": occurred_at,
            "title": message["subject"] or "(No subject)", "summary": _preview_summary(message["summary"]),
            "status": "Email", "sender": message["from_addr"], "account_labels": [message["label"]],
            "href": interviews.safe_url(message["provider_url"]),
            "organization_domains": domains, "assignment_reason": "Multiple matching manual processes" if len(matches) > 1 else None,
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
