"""Microsoft Graph mail source for personal Outlook.com accounts.

Collection calls are GET-only and never mark messages read or move them.
Explicit user replies are handled separately by mailcheck.replies.

https://learn.microsoft.com/en-us/graph/api/user-list-messages
"""

from __future__ import annotations

import random
import time
from datetime import date, datetime, timezone, timedelta
from typing import Iterator

import httpx

from ..models import RawMessage
from ..calendar_events import CalendarBooking
from ..interview_metadata import graph_calendars, message_references
from ..outlook_auth import OutlookAuthError, ReconnectRequired, acquire_token, CALENDAR_SCOPES
from .base import SourceError

GRAPH = "https://graph.microsoft.com/v1.0"
MESSAGES_URL = f"{GRAPH}/me/mailFolders/inbox/messages"

#: Only the fields the pipeline consumes. Bodies dominate the payload, so an
#: explicit $select keeps responses small.
SELECT = (
    "id,internetMessageId,subject,from,receivedDateTime,isRead,webLink,bodyPreview,body,conversationId,internetMessageHeaders"
)
PAGE_SIZE = 50
MAX_PAGES = 40  # a hard stop so a pathological mailbox cannot loop forever


class OutlookGraphSource:
    def __init__(
        self,
        *,
        label: str,
        client_id: str,
        email: str = "",
        timeout: int = 45,
        max_retries: int = 4,
    ) -> None:
        self.label = label
        self.client_id = client_id
        self.email = email
        self.timeout = timeout
        self.max_retries = max_retries

    # ------------------------------------------------------------------ http

    def _token(self, *, calendar: bool = False) -> str:
        try:
            return acquire_token(self.label, self.client_id, scopes=CALENDAR_SCOPES) if calendar else acquire_token(self.label, self.client_id)
        except ReconnectRequired as exc:
            raise SourceError(str(exc)) from exc
        except OutlookAuthError as exc:
            raise SourceError(str(exc)) from exc

    def _get(self, client: httpx.Client, url: str, params: dict | None = None) -> dict:
        for attempt in range(self.max_retries):
            try:
                resp = client.get(url, params=params)
            except httpx.TransportError as exc:
                if attempt == self.max_retries - 1:
                    raise SourceError(f"Could not reach Microsoft Graph: {exc}") from exc
                time.sleep(_backoff(attempt))
                continue

            if resp.status_code in (429, 503, 504) or 500 <= resp.status_code < 600:
                if attempt == self.max_retries - 1:
                    raise SourceError(
                        f"Microsoft Graph is unavailable (HTTP {resp.status_code})."
                    )
                time.sleep(_retry_after(resp) or _backoff(attempt))
                continue

            if resp.status_code in (401, 403):
                raise SourceError(
                    f"Microsoft rejected the stored sign-in for '{self.label}' "
                    f"(HTTP {resp.status_code}). Reconnect the account in Accounts; calendar collection requires read-only Calendars.Read access."
                )
            if resp.status_code >= 400:
                raise SourceError(
                    f"Microsoft Graph error {resp.status_code}: {resp.text[:200]}"
                )
            try:
                return resp.json()
            except ValueError as exc:
                raise SourceError("Microsoft Graph returned a non-JSON response.") from exc
        raise SourceError("Microsoft Graph request failed after retries.")

    def _client(self, *, calendar: bool = False) -> httpx.Client:
        return httpx.Client(
            timeout=self.timeout,
            headers={
                "Authorization": f"Bearer {self._token(calendar=calendar)}",
                "Accept": "application/json",
                # Keep original HTML for the reader; normalization separately
                # produces the short plain-text input used for classification.
                "Prefer": 'outlook.timezone="UTC", IdType="ImmutableId"' if calendar else 'outlook.body-content-type="html"',
            },
        )

    # ---------------------------------------------------------- MailSource API

    def test(self) -> None:
        with self._client() as client:
            data = self._get(client, f"{GRAPH}/me", {"$select": "mail,userPrincipalName"})
        if not (data.get("mail") or data.get("userPrincipalName")):
            raise SourceError("Signed in, but Microsoft returned no mailbox address.")

    def fetch_calendar(self, since: date) -> Iterator[CalendarBooking]:
        """Read native bookings from every calendar, never inbox messages.

        calendarView expands recurring occurrences and includes bookings regardless
        of online-meeting vendor, invitation wording, or email read state.
        """
        start = datetime(since.year,since.month,since.day,tzinfo=timezone.utc)
        end = datetime.now(timezone.utc) + timedelta(days=365)
        fields = "id,iCalUId,subject,start,end,originalStart,originalStartTimeZone,isCancelled,location,onlineMeeting,onlineMeetingUrl,onlineMeetingProvider,organizer,attendees,lastModifiedDateTime,type"
        invalid_events = 0
        with self._client(calendar=True) as client:
            url, params, pages = f"{GRAPH}/me/calendars", {"$select":"id,name", "$top":"100"}, 0
            while url:
                if pages >= MAX_PAGES:
                    raise SourceError("Calendar listing exceeded the paging limit; collection is incomplete.")
                data = self._get(client,url,params)
                for calendar in data.get("value") or []:
                    calendar_id = calendar.get("id")
                    if not calendar_id:
                        continue
                    from urllib.parse import quote
                    event_url = f"{GRAPH}/me/calendars/{quote(calendar_id,safe='')}/calendarView"
                    event_params = {"startDateTime":start.isoformat(),"endDateTime":end.isoformat(),"$select":fields,"$top":"100"}
                    event_pages = 0
                    while event_url:
                        if event_pages >= MAX_PAGES:
                            raise SourceError(f"Calendar '{calendar.get('name','')}' exceeded the paging limit; collection is incomplete.")
                        events = self._get(client,event_url,event_params)
                        for item in events.get("value") or []:
                            try:
                                yield _calendar_booking(item,calendar)
                            except (ValueError,TypeError,KeyError):
                                invalid_events += 1
                        event_url, event_params = events.get("@odata.nextLink"), None
                        event_pages += 1
                url, params = data.get("@odata.nextLink"), None
                pages += 1
        if invalid_events:
            raise SourceError(f"Microsoft returned {invalid_events} invalid calendar events; other valid bookings were collected.")

    def fetch_unread(self, since: date, *, include_read: bool = False) -> Iterator[RawMessage]:
        since_iso = datetime(
            since.year, since.month, since.day, tzinfo=timezone.utc
        ).isoformat().replace("+00:00", "Z")

        params = {
            # Graph requires the $orderby property to appear first in $filter,
            # or the messages endpoint rejects the query with InefficientFilter.
            "$filter": f"receivedDateTime ge {since_iso}" + ("" if include_read else " and isRead eq false"),
            "$select": "id,internetMessageId,subject,from,receivedDateTime,conversationId,internetMessageHeaders" if include_read else SELECT,
            # Invitation attachments arrive with this same read-only mailbox request.
            "$expand": "attachments",
            "$top": str(PAGE_SIZE),
            "$orderby": "receivedDateTime desc",
        }
        with self._client() as client:
            url, pages = MESSAGES_URL, 0
            while url and pages < MAX_PAGES:
                data = self._get(client, url, params)
                for item in data.get("value") or []:
                    yield _to_raw(item)
                # nextLink already carries every query parameter.
                url, params, pages = data.get("@odata.nextLink"), None, pages + 1


def _to_raw(item: dict) -> RawMessage:
    sender = ((item.get("from") or {}).get("emailAddress")) or {}
    body = item.get("body") or {}
    text = body.get("content") or item.get("bodyPreview") or ""

    received = item.get("receivedDateTime")
    dt = None
    if received:
        try:
            dt = datetime.fromisoformat(received.replace("Z", "+00:00"))
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        except ValueError:
            dt = None

    # internetMessageId is the cross-provider identity; the Graph id is a stable
    # per-mailbox fallback when a sender omitted the header.
    message_id = (item.get("internetMessageId") or "").strip()
    if not message_id:
        message_id = f"<graph-{item.get('id', '')}>"

    return RawMessage(
        message_id=message_id,
        uid=str(item.get("id") or ""),
        folder="Inbox",
        from_addr=(sender.get("address") or "").lower(),
        from_name=sender.get("name") or "",
        subject=item.get("subject") or "(no subject)",
        date_utc=dt,
        text=text,
        original_html=text if body.get("contentType", "").lower() == "html" else None,
        calendar_data=graph_calendars(item),
        thread_id=item.get("conversationId"),
        references=message_references({h["name"].lower(): h.get("value", "") for h in item.get("internetMessageHeaders") or []}),
        provider_url=item.get("webLink"),
    )


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(float(value), 60.0)
    except ValueError:
        return None


def _backoff(attempt: int) -> float:
    return min(2**attempt, 30) + random.uniform(0, 1)


def _calendar_booking(item: dict, calendar: dict) -> CalendarBooking:
    """Convert only event metadata returned in UTC by Microsoft Graph."""
    def instant(value: dict) -> datetime:
        raw = value.get("dateTime")
        if not raw:
            raise ValueError("missing event time")
        parsed = datetime.fromisoformat(raw.replace("Z","+00:00"))
        if parsed.tzinfo is None:
            if value.get("timeZone") not in ("UTC","Etc/UTC"):
                raise ValueError("calendar response did not honor the requested UTC timezone")
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    start = instant(item.get("start") or {})
    end = instant(item["end"]) if item.get("end",{}).get("dateTime") else None
    if end and end <= start:
        raise ValueError("event end must follow start")
    identity = str(item["id"])
    organizer = (item.get("organizer") or {}).get("emailAddress") or {}
    location = (item.get("location") or {}).get("displayName") or None
    from ..interviews import meeting_link, safe_url
    link = safe_url((item.get("onlineMeeting") or {}).get("joinUrl")) or safe_url(item.get("onlineMeetingUrl"))
    found, platform = meeting_link(link or location or "")
    provider = item.get("onlineMeetingProvider")
    if provider == "teamsForBusiness":
        platform = "Microsoft Teams"
    elif provider in ("skypeForBusiness","skypeForConsumer"):
        platform = "Skype"
    modified = item.get("lastModifiedDateTime")
    return CalendarBooking(provider_id="graph-event:"+identity,
        uid=item.get("iCalUId") or f"graph:{calendar['id']}:{identity}",
        title=item.get("subject") or "Meeting",start=start,end=end,
        recurrence_id=item.get("originalStart") or "",cancelled=bool(item.get("isCancelled")),
        location=location,meeting_url=link or found,meeting_platform=platform,
        organizer_name=organizer.get("name"),organizer_email=organizer.get("address"),
        participants=[a["emailAddress"]["address"] for a in item.get("attendees") or [] if (a.get("emailAddress") or {}).get("address")],
        updated_at=datetime.fromisoformat(modified.replace("Z","+00:00")) if modified else None,
        calendar_name=calendar.get("name") or "",original_timezone=item.get("originalStartTimeZone") or "")
