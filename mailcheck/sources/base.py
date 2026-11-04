"""Provider interfaces: legacy mail transport and separate native calendar bookings.

Adding Gmail API or Microsoft Graph later means a new module here that
satisfies this protocol — not a refactor of the pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from typing import Iterator, Protocol, runtime_checkable

from ..models import RawMessage
from ..calendar_events import CalendarBooking


_collection_status = ContextVar("mail_collection_status",default=None)


@contextmanager
def collection_scope(callback):
    token=_collection_status.set(callback)
    try:yield
    finally:_collection_status.reset(token)


def collection_status(message):
    logging.getLogger("mailcheck.collection").info(message)
    callback=_collection_status.get()
    if callback:callback(message)


class SourceError(RuntimeError):
    """Anything that stops one account from being read.

    The pipeline catches these per-account so one broken mailbox cannot abort
    a whole run.
    """


@runtime_checkable
class MailSource(Protocol):
    def test(self) -> None:
        """Connect and authenticate. Raises SourceError on failure."""

    def fetch_unread(self, since: date | datetime, *, include_read: bool = False) -> Iterator[RawMessage]:
        """Yield messages since the date, including read mail when requested; never mutate them."""

    def fetch_calendar(self, since: date, *, until=None) -> Iterator[CalendarBooking]:
        """Read native calendar bookings without consulting email."""
