"""Deterministic free-time calculation; no language model or mail mutations."""
from datetime import date, datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo
from .calendar_events import CalendarBooking


def _utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc)


def business_window(now, *, zone='America/Chicago', days=5, start_hour=9,end_hour=17,friday_end_hour=16,duration=30):
    tz=ZoneInfo(zone);local=_utc(now).astimezone(tz);day=local.date();result=[]
    while len(result)<days:
        finish=friday_end_hour if day.weekday()==4 else end_hour
        start=datetime.combine(day,time(),tz)+timedelta(hours=start_hour)
        end=datetime.combine(day,time(),tz)+timedelta(hours=finish)
        if day.weekday()<5 and _utc(end)>=_utc(now)+timedelta(minutes=duration):result.append((_utc(start),_utc(end)))
        day+=timedelta(days=1)
    return result


def calculate(bookings, *, now=None,zone='America/Chicago',days=5,duration=30,buffer=15,start_hour=9,end_hour=17,friday_end_hour=16):
    now=_utc(now or datetime.now(timezone.utc));tz=ZoneInfo(zone)
    windows=business_window(now,zone=zone,days=days,start_hour=start_hour,end_hour=end_hour,friday_end_hour=friday_end_hour,duration=duration)
    busy=[]
    for item in bookings:
        if item.cancelled or item.show_as.casefold()=='free':continue
        start=_utc(item.start)
        if item.end is None:
            if windows[0][0]<=start<windows[-1][1]:raise ValueError('A calendar event has no reliable end time. Correct it before sharing availability.')
            continue
        end=_utc(item.end)
        if end<=start:raise ValueError('A calendar event has an invalid end time. Correct it before sharing availability.')
        busy.append((start-timedelta(minutes=buffer),end+timedelta(minutes=buffer)))
    merged=[]
    for start,end in sorted(busy):
        if merged and start<=merged[-1][1]:merged[-1]=(merged[-1][0],max(end,merged[-1][1]))
        else:merged.append((start,end))
    ranges=[]
    current=datetime.fromtimestamp(math.ceil(now.timestamp()/900)*900,timezone.utc)
    for start,end in windows:
        cursor=max(start,current)
        available=[]
        for left,right in merged:
            if right<=cursor or left>=end:continue
            if left>cursor:available.append((cursor,min(left,end)))
            cursor=max(cursor,right)
            if cursor>=end:break
        if cursor<end:available.append((cursor,end))
        for left,right in available:
            if right-left<timedelta(minutes=duration):continue
            local_left,local_right=left.astimezone(tz),right.astimezone(tz)
            def clock(stamp):return f"{stamp.hour%12 or 12}:{stamp.minute:02d} {'AM' if stamp.hour<12 else 'PM'}"
            label=f"{local_left:%a, %b} {local_left.day}: {clock(local_left)}–{clock(local_right)} {local_left:%Z}"
            ranges.append({'date':local_left.date().isoformat(),'start':left.isoformat(),'end':right.isoformat(),'label':label})
    return {'ranges':ranges,'timezone':zone,'checked_at':now.isoformat(),'calendar_labels':[]}


def refresh(conn,account_id,preferences,cfg, *, now=None,duration=None):
    """Read complete selected provider calendars for the automatic window."""
    from . import db
    from .pipeline import build_source
    from .sources import SourceError
    now=_utc(now or datetime.now(timezone.utc));duration=duration or preferences['duration_minutes']
    kwargs=dict(zone=preferences['timezone'],days=preferences['lookahead_business_days'],duration=duration,buffer=preferences['buffer_minutes'],start_hour=preferences['start_hour'],end_hour=preferences['end_hour'],friday_end_hour=preferences['friday_end_hour'])
    windows=business_window(now,**{k:v for k,v in kwargs.items() if k!='buffer'})
    account=conn.execute('SELECT * FROM accounts WHERE id=?',(account_id,)).fetchone()
    ids=list(dict.fromkeys(([account_id] if account and account['provider']=='outlook' else [])+preferences.get('calendar_account_ids',[])))
    query_start=windows[0][0]-timedelta(minutes=kwargs['buffer'])
    query_end=windows[-1][1]+timedelta(minutes=kwargs['buffer'])
    if not ids:raise ValueError('Link a calendar account in assistant preferences before sharing availability.')
    bookings=[];labels=[]
    for identity in ids:
        row=conn.execute("SELECT label FROM accounts WHERE id=? AND provider='outlook' AND enabled=1",(identity,)).fetchone()
        if not row:raise ValueError('A linked calendar account is unavailable. Update assistant preferences before sharing availability.')
        source=build_source(db.get_account(conn,row['label']),cfg)
        try:collected=list(source.fetch_calendar(query_start.date(),until=query_end))
        except SourceError as exc:raise ValueError(f"Calendar refresh failed for {row['label']}: {exc}. Availability was not generated.") from exc
        bookings.extend(collected);labels.append(row['label'])
    # Native bookings above are live. Only add stored email/manual events, not stale native copies.
    marks=','.join('?'*len(ids))
    for row in conn.execute(f"""SELECT DISTINCT e.* FROM interview_events e JOIN interview_sources s ON s.event_id=e.id
        WHERE s.account_id IN ({marks}) AND e.status!='Cancelled' AND e.start_at IS NOT NULL
        AND NOT EXISTS(SELECT 1 FROM interview_event_removals r WHERE r.event_id=e.id)
        AND (s.external_message_id NOT LIKE 'graph-event:%' OR e.manual_fields!='[]')
        AND julianday(e.start_at)<julianday(?) AND (julianday(e.end_at)>julianday(?) OR
            (e.end_at IS NULL AND julianday(e.start_at)>=julianday(?)))""",(*ids,query_end.isoformat(),query_start.isoformat(),query_start.isoformat())):
        bookings.append(CalendarBooking(str(row['id']),str(row['id']),row['company'] or 'Interview',datetime.fromisoformat(row['start_at']),datetime.fromisoformat(row['end_at']) if row['end_at'] else None))
    result=calculate(bookings,now=now,**kwargs);result['calendar_labels']=labels
    return result
