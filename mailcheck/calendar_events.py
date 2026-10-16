"""Provider-neutral calendar records. No email text or classification is involved."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


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
