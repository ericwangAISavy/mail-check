"""Provider-neutral calendar records. No email text or classification is involved."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import re


@dataclass
class CalendarBooking:
    provider_id: str
    uid: str
    title: str
    start: datetime
    end: datetime | None
    timezone: str = "UTC"
    recurrence_id: str = ""
    cancelled: bool = False
    location: str | None = None
    meeting_url: str | None = None
    meeting_platform: str | None = None
    organizer_name: str | None = None
    organizer_email: str | None = None
    participants: list[str] = field(default_factory=list)
    updated_at: datetime | None = None
    calendar_name: str = ""
    original_timezone: str = ""
    show_as: str = "busy"
    all_day: bool = False
    categories: list[str] = field(default_factory=list)


_INTERVIEW = re.compile(
    r"\binterviews?\b|\b(?:phone|recruiter|technical|hr|hiring)\s+(?:screen(?:ing)?|round)\b|"
    r"\bhiring manager\b|\b(?:recruiter|talent acquisition)\s+(?:call|chat|meeting)\b|"
    r"\b(?:technical|coding)\s+assessment\b", re.I)
_UNRELATED = re.compile(
    r"\b(?:holiday|birthday|anniversary|vacation|dentist|doctor|out of office|"
    r"christmas|thanksgiving|new year|constitution day|independence day|labor day|memorial day)\b", re.I)


def interview_evidence(title, categories=(), *, organizer=''):
    """Require recruiting context; a meeting URL or organizer alone is not proof."""
    if _INTERVIEW.search(title or ''):
        return True
    if _UNRELATED.search(title or ''):
        return False
    if any(_INTERVIEW.search(value) for value in categories if isinstance(value,str)):
        return True
    # Some genuine interviews are simply titled 'Company Phone Meeting'.
    # Require both call/meeting wording and an explicitly recruiting organizer.
    return bool(re.search(r"\b(?:call|meeting|chat|screening)\b", title or '', re.I)
                and re.search(r"\b(?:recruiter|recruiting|talent|hiring|careers)\b", organizer or '', re.I))


def unrelated_booking(title):
    return bool(_UNRELATED.search(title or ''))
