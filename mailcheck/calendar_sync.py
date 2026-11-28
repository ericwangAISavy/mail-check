"""What was already collected from each calendar, so unchanged events cost nothing.

The state is a small file beside the database, not a table: it is only a
shortcut. Losing it, or restoring an older database, just means events are read
and checked again; an event is skipped only while its saved rows still exist.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path

from .calendar_content import SOURCE_LIMIT

log = logging.getLogger(__name__)
#: How often every calendar is read in full (secondary calendars, deletions, the date window).
FULL_READ_SECONDS = 30 * 60
FORMAT = 1


class SyncState:
    def __init__(self, conn, account):
        database = conn.execute("PRAGMA database_list").fetchone()[2]
        self.path = Path(database).parent / "calendar-sync" / f"{Path(database).stem}-{int(account.id)}.json" if database else None
        self.owner = account.email.casefold()
        data = {}
        if self.path:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = {}
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("owner") != self.owner:
            data = {}
        self.delta_link: str | None = data.get("delta_link")
        self.full_at: float = data.get("full_at") or 0
        self.events: dict = data.get("events") if isinstance(data.get("events"), dict) else {}

    def full_read_due(self, now: float | None = None) -> bool:
        age = (time.time() if now is None else now) - self.full_at
        return not self.delta_link or not 0 <= age < FULL_READ_SECONDS

    def save(self) -> None:
        if not self.path:
            return
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary.write_text(json.dumps(dict(format=FORMAT, owner=self.owner, delta_link=self.delta_link,
                full_at=self.full_at, events=self.events)), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        except OSError:
            # Only a shortcut: the next run simply reads more.
            log.warning("Could not save calendar sync progress; the next run reads the calendar again.")
            try:
                temporary.unlink()
            except OSError:
                pass


class Unchanged:
    """Decides whether a listed event was already fully handled in its current form."""

    def __init__(self, conn, account_id: int, state: SyncState, settings: tuple):
        self.state, self.settings = state, settings
        self.analyses = {row[0]: [row[1], row[2]] for row in conn.execute(
            "SELECT external_id,fingerprint,analyzed_at FROM calendar_analyses WHERE account_id=?", (account_id,))}
        self.queued = {row[0] for row in conn.execute(
            "SELECT external_id FROM calendar_analysis_tasks WHERE account_id=? AND state!='cancelled'", (account_id,))}
        self.saved = {row[0] for row in conn.execute(
            """SELECT s.external_message_id FROM interview_sources s JOIN interview_calendar_state c ON c.source_id=s.id
               WHERE s.account_id=? AND c.present=1""", (account_id,))}

    def signature(self, booking) -> str:
        from .calendar_queue import payload_version
        value = [payload_version(booking, SOURCE_LIMIT)[1], self.analyses.get(booking.provider_id), *self.settings]
        return hashlib.sha256(json.dumps(value).encode()).hexdigest()

    def previous(self, booking, signature: str) -> bool | None:
        """None when the event must be processed, else whether it is saved as an interview."""
        entry = self.state.events.get(booking.provider_id)
        if not entry or entry[0] != signature or booking.provider_id not in self.queued:
            return None
        if entry[1] and booking.provider_id not in self.saved:
            return None
        return bool(entry[1])
