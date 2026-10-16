"""Bounded calendar/header capture at the existing provider normalization boundary."""
from __future__ import annotations

import base64
import re

MAX_CALENDAR_BYTES = 256_000


def message_references(headers: dict) -> list[str]:
    values = []
    for name in ("in-reply-to", "references"):
        raw = headers.get(name) or headers.get(name.title()) or []
        values.extend([raw] if isinstance(raw, str) else raw)
    return re.findall(r"<[^<>\s]+>", " ".join(values))[-50:]


def imap_calendars(msg) -> list[str]:
    obj = getattr(msg, "obj", None)
    if obj is None:
        return []
    calendars = []
    for part in obj.walk():
        filename = part.get_filename() or ""
        if part.get_content_type() == "text/calendar" or filename.lower().endswith(".ics"):
            payload = part.get_payload(decode=True) or b""
            if len(payload) <= MAX_CALENDAR_BYTES:
                try:
                    calendars.append(payload.decode(part.get_content_charset() or "utf-8", errors="replace"))
                except LookupError:
                    calendars.append(payload.decode("utf-8", errors="replace"))
        if len(calendars) >= 10:
            break
    return calendars


def graph_calendars(item: dict) -> list[str]:
    calendars = []
    for attachment in item.get("attachments") or []:
        if attachment.get("contentType") == "text/calendar" or str(attachment.get("name", "")).lower().endswith(".ics"):
            encoded = attachment.get("contentBytes") or ""
            if len(encoded) > MAX_CALENDAR_BYTES * 1.4:
                continue
            try:
                calendars.append(base64.b64decode(encoded, validate=True).decode("utf-8", errors="replace"))
            except (ValueError, UnicodeError):
                continue
        if len(calendars) >= 10:
            break
    return calendars
