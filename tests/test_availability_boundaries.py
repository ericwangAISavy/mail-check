from datetime import datetime, timezone

import pytest

from mailcheck.availability import calculate
from mailcheck.calendar_events import CalendarBooking


def test_unknown_end_just_before_business_hours_cannot_be_claimed_free():
    # October Chicago business hours begin at 14:00 UTC. This event starts
    # in the padded calendar-query window and may still occupy the first slot.
    event=CalendarBooking('unknown','unknown','Uncertain end',
        datetime(2026,10,22,13,50,tzinfo=timezone.utc),None)
    with pytest.raises(ValueError,match='end time'):
        calculate([event],now=datetime(2026,10,22,12,tzinfo=timezone.utc),days=1,buffer=15)
