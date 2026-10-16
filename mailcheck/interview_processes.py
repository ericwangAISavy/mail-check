"""Organization timelines derived from saved calendar event identities."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from email.utils import parseaddr

from . import db, interviews

SERVICE_DOMAINS = ("google.com", "teams.microsoft.com", "teams.live.com", "teams.com", "zoom.us", "zoom.com")
DOMAIN = re.compile(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


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
    labels: dict[int, list[str]] = {}
    for source in conn.execute("SELECT DISTINCT s.event_id,a.label FROM interview_sources s JOIN accounts a ON a.id=s.account_id WHERE a.enabled=1 ORDER BY a.label"):
        labels.setdefault(source["event_id"], []).append(source["label"])
    for event in interviews.list_events(conn, now=now):
        # Match the Interview page's calendar evidence boundary.
        if event["extraction_rank"] < 2 or not event["start_at"]:
            continue
        domains = organization_domains(event["participants"], event["organizer_email"], own_emails=own)
        organization = domains[0] if len(domains) == 1 else None
        event["organization_domains"] = domains
        event["assignment_reason"] = None if organization else "Multiple organization domains" if domains else "No eligible organization domain"
        event["account_labels"] = labels.get(event["id"], [])
        group = groups.setdefault(organization, {"organization": organization, "events": []})
        group["events"].append(event)

    result = []
    for key in sorted(groups, key=lambda value: (value is None, value or "")):
        group = groups[key]
        group["events"].sort(key=lambda event: (datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")), event["id"]))
        group["event_count"] = len(group["events"])
        group["next_interview"] = next((event for event in group["events"] if event["display_status"] in ("Scheduled", "Rescheduled") and datetime.fromisoformat(event["start_at"].replace("Z", "+00:00")) >= now), None)
        result.append(group)
    return result
