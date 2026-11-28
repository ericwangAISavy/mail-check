import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { usePageState } from "@/lib/page-state"
import { useSearchParams } from "react-router-dom"
import { Ban, ChevronDown, ChevronLeft, ChevronRight, Columns2, Download, Expand, Filter, Globe, Link, Minimize, MoreHorizontal, Printer, TriangleAlert } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { CalendarAccount, InterviewEvent } from "@/lib/types"
import { calendarCounts, dayKey, exportInterviews, fallsOnDay, HOUR_HEIGHT, parseDay, placeEvents, shiftDays, startOfDay, viewDays, type CalendarView } from "@/lib/interview-calendar"
import { CALENDAR_TIMEZONE_KEY, calendarParts, calendarTimezone, calendarWallTime, savedCalendarTimezone, validTimezone } from "@/lib/calendar-timezone"
import TimezonePicker from "@/components/timezone-picker"
import CalendarColors, { calendarColorOf } from "@/components/calendar-colors"
import { useToast } from "@/components/common"
import {FeedbackIndicator} from './interview-feedback-badges'

const labels: Record<CalendarView,string> = {workweek:"Work week",week:"Week",month:"Month",day:"Day"}
const clock = (value: string, timeZone?:string) => new Date(value).toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit",timeZone})
/** "9:30 – 10:00 AM": the shared AM/PM is written once. */
const timeRange = (event: InterviewEvent, timeZone?:string) => {
  const start = clock(event.start_at!, timeZone)
  if (!event.end_at) return `${start} · End time unknown`
  const end = clock(event.end_at, timeZone), suffix = /\s([AP]M)$/i
  const a = start.match(suffix), b = end.match(suffix)
  return a && b && a[1] === b[1] ? `${start.replace(suffix, "")} – ${end}` : `${start} – ${end}`
}
const statusClass = (event: InterviewEvent) => {
  const status = event.display_status.toLowerCase().replaceAll(" ","-")
  return event.analysis_pending
    ? `${status} analysis-deferred`
    : status
}
/** Over: its end has passed (or its start, when the end time is unknown). */
const pastClass = (event: InterviewEvent, now: Date) => { const end = Date.parse(event.end_at || event.start_at || ""); return Number.isFinite(end) && end <= now.getTime() ? "is-past" : "" }
const feedbackLabel = (event: InterviewEvent) => event.feedback_tags?.length ? ` · ${event.feedback_tags.join(', ')}` : ''
const title = (event: InterviewEvent) => `${event.company || "Unknown company"}${event.role ? " · " + event.role : ""} · ${event.stage}${feedbackLabel(event)}`
const timeLabel = (event: InterviewEvent, timeZone?:string) => `${event.start_at ? new Date(event.start_at).toLocaleString(undefined,{dateStyle:"medium",timeStyle:"short",timeZone}) : "Time unknown"}${event.end_at ? " – " + clock(event.end_at,timeZone) : " · End time unknown"}`
const eventAccount = (event: InterviewEvent, accounts: CalendarAccount[], account: string) =>
  accounts.filter(a=>account ? a.label===account : event.account_labels?.includes(a.label)).sort((a,b)=>a.id-b.id)[0]

const accountIdentity = (account?: CalendarAccount) => account && (account.label === account.email
  ? account.email : `${account.label} (${account.email})`)

function eventLabels(event: InterviewEvent, timeZone: string, account?: CalendarAccount) {
  const identity = accountIdentity(account) || event.account_labels?.join(", ")
  const time = timeLabel(event, timeZone)
  const review = event.needs_review && event.display_status !== "Needs review" ? "Needs review" : null
  const analysis = event.analysis_pending ? "Analysis pending" : null
  return {
    "aria-label": [`${event.company || "Unknown company"}, ${event.stage}, ${time}, ${event.display_status}${feedbackLabel(event)}`, event.role, review, analysis, identity && `Account: ${identity}`].filter(Boolean).join(", "),
    title: [title(event), time, event.display_status, review, analysis, event.meeting_platform || event.location, identity && `Account: ${identity}`].filter(Boolean).join("\n"),
  }
}

function EventIndicators({ event }: { event: InterviewEvent }) {
  if (event.display_status.toLowerCase() === "cancelled") {
    return <Ban className="calendar-event-cancelled" size={12} role="img" aria-label="Cancelled"><title>Cancelled</title></Ban>
  }
  return <FeedbackIndicator tags={event.feedback_tags} />
}

/** Intro (30 minutes or less) or technical (longer); unknown when the length is unknown. */
/** A short timezone name ("CST") for the compact picker; the full name stays in its title. */
const zoneAbbreviation = (timeZone: string) => {
  try { return new Intl.DateTimeFormat("en-US", { timeZone, timeZoneName: "short" }).formatToParts(new Date()).find(part => part.type === "timeZoneName")?.value || timeZone } catch { return timeZone }
}

type Account = CalendarAccount
/** menuItems join the top of the "More" menu (e.g. retrying analysis). commandBar is accepted for
 * older callers; its controls now live in the toolbar and the "More" menu. */
type Props = { events: InterviewEvent[]; accounts: Account[]; account: string; filterCount: number; filters: ReactNode; actions?: ReactNode; menuItems?: ReactNode; onSelect:(id:number)=>void; commandBar?: boolean; onVisibleCompaniesChange?:(companies:string[])=>void }
export default function InterviewCalendar({events:allEvents,accounts,account,filterCount,filters,actions,menuItems,onSelect,onVisibleCompaniesChange}:Props) {
  const [params,setParams]=useSearchParams(), toast=useToast()
  const [preference,setPreference]=useState(savedCalendarTimezone)
  const timeZone=calendarTimezone(params,preference)
  const [now,setNow]=useState(()=>new Date())
  const today=calendarParts(now,timeZone).key
  const requestedZone=params.get("calendar_tz")
  const selectedZone=requestedZone==="local"||validTimezone(requestedZone)?requestedZone:preference
  const changeZone=(value:string)=>{
    setPreference(value)
    try{
      localStorage.setItem(CALENDAR_TIMEZONE_KEY,value)
      if(localStorage.getItem(CALENDAR_TIMEZONE_KEY)!==value)throw new Error("Storage unavailable")
      toast("Timezone saved for this browser.","success")
    }catch{toast("Timezone changed for this visit only.","error")}
    const next=new URLSearchParams(params);next.set("calendar_tz",value);setParams(next)
  }
  const viewParam=params.get("calendar_view"), dayParam=params.get("calendar_date")
  const view:CalendarView = viewParam && Object.keys(labels).includes(viewParam) ? viewParam as CalendarView : "workweek"
  const date=useMemo(()=>parseDay(dayParam)||parseDay(today)!,[dayParam,today])
  const days=useMemo(()=>viewDays(date,view),[date,view])
  const events=allEvents
  const visibleCompanies=JSON.stringify([...new Set(allEvents.filter(event=>!event.analysis_pending&&days.some(day=>fallsOnDay(event,day,timeZone))).map(event=>event.company).filter((value):value is string=>!!value))].sort())
  useEffect(()=>onVisibleCompaniesChange?.(JSON.parse(visibleCompanies)),[visibleCompanies,onVisibleCompaniesChange])
  const [filterOpen,setFilterOpen]=usePageState("/interviews","calendarFilterOpen",false), [split,setSplit]=usePageState("/interviews","calendarSplit",false), [expanded,setExpanded]=useState(false)
  const [moreOpen,setMoreOpen]=useState(false), [dateOpen,setDateOpen]=useState(false)
  const moreRef=useRef<HTMLDivElement>(null), dateRef=useRef<HTMLDivElement>(null), calendarRef=useRef<HTMLElement>(null)
  useEffect(()=>{const timer=window.setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(timer)},[])
  useEffect(()=>{
    const escape=(event:KeyboardEvent)=>{
      if(document.querySelector(".interview-dialog"))return
      if(event.key==="Escape"){setExpanded(false);setMoreOpen(false);setDateOpen(false)}
      if(expanded&&event.key==="Tab"){
        const controls=Array.from(calendarRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled),input,select,[tabindex='0']")||[]).filter(el=>el.getClientRects().length)
        const first=controls[0],last=controls[controls.length-1]
        if(first&&last&&(event.shiftKey&&document.activeElement===first||!event.shiftKey&&document.activeElement===last||!calendarRef.current?.contains(document.activeElement))){event.preventDefault();(event.shiftKey?last:first).focus()}
      }
    }
    const outside=(event:PointerEvent)=>{if(!moreRef.current?.contains(event.target as Node))setMoreOpen(false);if(!dateRef.current?.contains(event.target as Node))setDateOpen(false)}
    document.addEventListener("keydown",escape);document.addEventListener("pointerdown",outside)
    return()=>{document.removeEventListener("keydown",escape);document.removeEventListener("pointerdown",outside)}
  },[expanded])
  const update=(nextView:CalendarView,nextDate:Date)=>{const next=new URLSearchParams(params);next.set("calendar_view",nextView);next.set("calendar_date",dayKey(nextDate));setParams(next)}
  const navigate=(direction:number)=>update(view,view==="month"?new Date(date.getFullYear(),date.getMonth()+direction,1):shiftDays(date,direction*(view==="day"?1:7)))
  const jumpDay=(day:Date)=>update("day",day)
  const heading=view==="month"?date.toLocaleDateString(undefined,{month:"long",year:"numeric"}):view==="day"?date.toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric",year:"numeric"}):new Intl.DateTimeFormat(undefined,{month:"short",day:"numeric",year:"numeric"}).formatRange(days[0],days[days.length-1])
  const counts=calendarCounts(allEvents,view==="month"?days.filter(day=>day.getMonth()===date.getMonth()):days,timeZone)
  const splitAccounts=accounts.filter(a=>!account||a.label===account)
  const hiddenWeekend=view==="workweek"?events.filter(e=>!days.some(day=>fallsOnDay(e,day,timeZone)) && [5,6].some(offset=>fallsOnDay(e,shiftDays(days[0],offset),timeZone))).length:0
  const copyLink=async()=>{try{const url=new URL(window.location.href);url.search=params.toString();url.searchParams.delete("event");url.searchParams.set("calendar_view",view);url.searchParams.set("calendar_date",dayKey(date));url.searchParams.set("calendar_tz",timeZone);await navigator.clipboard.writeText(url.toString());toast("Calendar link copied.","success");setMoreOpen(false)}catch{toast("Could not copy the link. Copy this page’s address from your browser.","error")}}
  const download=()=>{const file=new Blob([exportInterviews(events)],{type:"text/calendar;charset=utf-8"});const url=URL.createObjectURL(file),link=document.createElement("a");link.href=url;link.download="mailcheck-interviews.ics";link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);setMoreOpen(false)}
  return <section ref={calendarRef} className={`outlook-calendar oc-panel ${expanded?"calendar-expanded":""}`} aria-label="Interview calendar">
    {/* One toolbar: navigate on the left with the period's summary; view settings, alerts and
        the overflow menu on the right. The page header already names the page. */}
    <div className="outlook-date-bar oc-toolbar">
      <Button variant="outline" size="sm" className="oc-today" onClick={()=>update(view,startOfDay(calendarWallTime(new Date(),timeZone)))}>Today</Button>
      <Button variant="ghost" size="icon" aria-label="Previous calendar period" onClick={()=>navigate(-1)}><ChevronLeft size={17}/></Button>
      <Button variant="ghost" size="icon" aria-label="Next calendar period" onClick={()=>navigate(1)}><ChevronRight size={17}/></Button>
      <div className="outlook-menu-anchor" ref={dateRef}><button className="outlook-period" aria-expanded={dateOpen} aria-controls="calendar-date-picker" onClick={()=>setDateOpen(!dateOpen)}><span aria-live="polite">{heading}</span><ChevronDown size={14}/></button>{dateOpen&&<div className="outlook-menu" id="calendar-date-picker"><label>Go to date<input type="date" aria-label="Go to date" value={dayKey(date)} onChange={e=>{const chosen=parseDay(e.target.value);if(chosen){update(view,chosen);setDateOpen(false)}}}/></label></div>}</div>
      <span className="calendar-interview-counts" role="status" aria-label="Interview counts" title={`Intro (30 min or less) ${counts.intro} · Technical ${counts.tech}${counts.unknown?` · Unknown length ${counts.unknown}`:""}`}>
        <strong>{counts.total} {counts.total===1?"interview":"interviews"}</strong>
      </span>
      <div className="oc-toolbar-end">
        <span className="oc-select"><select aria-label="Calendar view" value={view} onChange={e=>update(e.target.value as CalendarView,date)}>{(["workweek","week","month","day"] as const).map(v=><option key={v} value={v}>{labels[v]}</option>)}</select><ChevronDown size={14} aria-hidden="true"/></span>
        <div className="oc-zone" title={`Timezone: ${timeZone}`}><Globe size={14} aria-hidden="true"/><TimezonePicker value={selectedZone} onChange={changeZone} display={zoneAbbreviation(timeZone)}/></div>
        <CalendarColors accounts={accounts}/>
        <Button variant="ghost" size="icon" className="oc-filter" aria-label="Filter" aria-expanded={filterOpen} aria-controls="calendar-filter-panel" onClick={()=>setFilterOpen(!filterOpen)}><Filter size={15}/>{filterCount>0&&<span className="calendar-filter-count">{filterCount}</span>}</Button>
        {actions}
        <div className="outlook-menu-anchor" ref={moreRef}>
          <Button variant="ghost" size="icon" aria-label="More calendar options" aria-expanded={moreOpen} aria-controls="calendar-more-menu" onClick={()=>setMoreOpen(!moreOpen)}><MoreHorizontal size={18}/></Button>
          {moreOpen&&<div className="outlook-menu oc-more-menu" id="calendar-more-menu">{menuItems&&<div className="oc-menu-extra" onClick={()=>setMoreOpen(false)}>{menuItems}</div>}
            <button type="button" aria-pressed={split} onClick={()=>{setSplit(!split);setMoreOpen(false)}} title="Show each connected account’s calendar side by side"><Columns2 size={15}/>Split view</button>
            <button type="button" onClick={()=>void copyLink()}><Link size={15}/>Copy calendar link</button>
            <button type="button" onClick={download}><Download size={15}/>Download calendar (.ics)</button>
            <button type="button" onClick={()=>{setMoreOpen(false);window.print()}}><Printer size={15}/>Print</button>
            <button type="button" aria-pressed={expanded} onClick={()=>{setExpanded(!expanded);setMoreOpen(false)}}>{expanded?<Minimize size={15}/>:<Expand size={15}/>}{expanded?"Restore calendar size":"Expand calendar"}</button>
          </div>}
        </div>
      </div>
    </div>
    {filterOpen&&<div id="calendar-filter-panel" className="outlook-filter-panel">{filters}</div>}
    <div className={`outlook-calendars oc-frame ${split&&splitAccounts.length>1?"is-split":""}`}>
      {(split&&splitAccounts.length?splitAccounts:[null]).map(a=>{
        const grid = { days, events: a ? events.filter(e=>e.account_labels?.includes(a.label)) : events,
          accounts, account: a?.label || account, now, timeZone, onSelect, onDay: jumpDay,
          selected: Number(params.get("event")) || undefined }
        return <div className="outlook-account-calendar" key={a?.id||"all"}>
          {a&&<div className="outlook-account-name"><i className={`calendar-color-chip account-color-${calendarColorOf(a)}`} aria-hidden="true"/>{a.label}<span>{a.email}</span></div>}
          {view==="month" ? <MonthGrid {...grid} date={date}/> : <TimeGrid {...grid} view={view}/>}
        </div>
      })}
    </div>
    {view!=="month"&&<div className="oc-legend" aria-label="Calendar key">
      <span><TriangleAlert size={12} className="oc-legend-warn" aria-hidden="true"/>Feedback warning</span>
      <span><Ban size={12} aria-hidden="true"/>Cancelled</span>
      <span className="oc-legend-zone">Times in {timeZone.replaceAll("_"," ")}</span>
    </div>}
    {(hiddenWeekend>0)&&<div className="outlook-calendar-notices">{hiddenWeekend>0&&<button onClick={()=>update("week",date)}>{hiddenWeekend} {hiddenWeekend===1?"interview is":"interviews are"} on the weekend · Show week</button>}</div>}
  </section>
}


type GridProps = {
  days: Date[]
  events: InterviewEvent[]
  accounts: Account[]
  account: string
  now: Date
  timeZone: string
  onSelect: (id: number) => void
  onDay: (day: Date) => void
  selected?: number
}

function TimeGrid({ days, view, events, accounts, account, now, timeZone, onSelect, onDay, selected }: GridProps & { view: CalendarView }) {
  const scroll = useRef<HTMLDivElement>(null)
  const period = dayKey(days[0])
  const today = calendarParts(now, timeZone)
  useEffect(()=>{ if (scroll.current) scroll.current.scrollTop = 8 * HOUR_HEIGHT - 10 }, [period, view])
  const style = { "--calendar-days": days.length, "--hour-height": `${HOUR_HEIGHT}px` } as CSSProperties
  const syncScroll = () => {
    const current = scroll.current
    if (current) current.closest(".outlook-calendars.is-split")?.querySelectorAll<HTMLDivElement>(".outlook-scroll").forEach(other=>{
      if (other !== current && Math.abs(other.scrollTop - current.scrollTop) > 1) other.scrollTop = current.scrollTop
    })
  }
  return <div className="outlook-scroll" ref={scroll} onScroll={syncScroll} style={style} aria-label={`${labels[view].toLowerCase()} calendar`} tabIndex={0}>
    <div className="outlook-day-headers">
      <div className="outlook-axis-heading"/>
      {days.map((day, index)=><button key={dayKey(day)} className={`outlook-day-heading ${dayKey(day) === today.key ? "is-today" : ""}`}
        onClick={()=>onDay(day)} aria-label={`Show ${day.toLocaleDateString(undefined,{dateStyle:"full"})}`} aria-current={dayKey(day) === today.key ? "date" : undefined}>
        <span className="oc-weekday">{day.toLocaleDateString(undefined,{weekday:"short"})}</span>
        <span className="oc-date">{index === 0 || day.getDate() === 1 ? `${day.toLocaleDateString(undefined,{month:"short"})} ` : ""}{day.getDate()}</span>
      </button>)}
    </div>
    <div className="outlook-time-grid">
      <div className="outlook-time-axis" aria-hidden="true">{Array.from({length:24},(_,hour)=>
        <div key={hour} className="outlook-hour-label"><span>{new Date(2000,0,1,hour).toLocaleTimeString(undefined,{hour:"numeric"})}</span></div>)}</div>
      {days.map(day=><section key={dayKey(day)} className={`calendar-day outlook-day-column ${dayKey(day) === today.key ? "is-today" : ""}`}
        aria-label={day.toLocaleDateString(undefined,{dateStyle:"full"})}>
        {Array.from({length:24},(_,hour)=><div key={hour} className="outlook-hour-line" aria-hidden="true"/>)}
        {placeEvents(events, day, timeZone).map(placed=>{
          const { event, start, end, lane, lanes, continuesBefore, continuesAfter, unknownEnd } = placed
          const owner = eventAccount(event, accounts, account)
          const height = Math.max(18, (end - start) * HOUR_HEIGHT / 60 - 3)
          const density = height < 32 ? "is-short" : height < 49 ? "is-medium" : ""
          const compactTime = continuesBefore ? "Continues" : clock(event.start_at!, timeZone)
          return <button key={event.id} data-event-id={event.id} data-start-minute={start} data-lane={lane}
            className={`interview-event outlook-time-event account-color-${owner ? calendarColorOf(owner) : 0} ${statusClass(event)} ${pastClass(event, now)} ${unknownEnd ? "duration-unknown" : ""} ${density} ${selected === event.id ? "is-selected" : ""}`}
            aria-current={selected === event.id ? "true" : undefined} {...eventLabels(event, timeZone, owner)}
            onClick={()=>onSelect(event.id)} style={{
              top: `min(calc(var(--hour-height) * ${start/60}), calc(var(--hour-height) * 24 - 18px))`,
              height: `max(18px, calc(var(--hour-height) * ${(end-start)/60} - 3px))`,
              left: `calc(${lane*100/lanes}% + 3px)`, width: `calc(${100/lanes}% - 6px)`,
            }}>
            <span className="oc-ev-body">
              <strong><span className="oc-ev-title">{continuesBefore ? "Continues · " : ""}{event.company || "Unknown company"}{event.role ? " · " + event.role : ""}</span><EventIndicators event={event}/></strong>
              <span className="oc-time">
                {density === "is-short" ? compactTime : <>
                  <span className="oc-time-range">{timeRange(event, timeZone)}{continuesAfter ? " · Continues" : ""}</span>
                  <span className="oc-time-start">{compactTime.replace(/\s[AP]M$/i, "")}</span>
                </>}
              </span>
              {density === "" && (event.meeting_platform || event.stage) && <span className="oc-meta">{event.meeting_platform || event.stage}</span>}
            </span>
          </button>
        })}
        {dayKey(day) === today.key && <div className="outlook-now-line" role="img" style={{top:`calc(var(--hour-height) * ${today.minutes/60})`}} aria-label={`Current time ${clock(now.toISOString(),timeZone)}`}/>}
      </section>)}
    </div>
  </div>
}

function MonthGrid({ date, days, events, accounts, account, now, timeZone, onSelect, onDay, selected }: GridProps & { date: Date }) {
  return <div className="outlook-month-grid calendar-grid view-month" aria-label="month calendar">
    {["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"].map(day=>
      <div className="outlook-month-weekday" key={day}><span>{day}</span><abbr title={day}>{day.slice(0,3)}</abbr></div>)}
    {days.map(day=>{
      const items = events.filter(event=>fallsOnDay(event,day,timeZone))
      return <section key={dayKey(day)} className={`calendar-day outlook-month-day ${day.getMonth()!==date.getMonth()?"other-month":""} ${dayKey(day)===calendarParts(now,timeZone).key?"is-today":""}`}
        aria-label={day.toLocaleDateString(undefined,{dateStyle:"full"})}>
        <button className="calendar-day-label" onClick={()=>onDay(day)} aria-label={`Show ${day.toLocaleDateString(undefined,{dateStyle:"full"})}`}>{day.getDate()}</button>
        <div>{items.slice(0,3).map(event=>{
          const owner = eventAccount(event, accounts, account)
          return <button key={event.id} data-event-id={event.id}
            className={`interview-event outlook-month-event account-color-${owner ? calendarColorOf(owner) : 0} ${statusClass(event)} ${pastClass(event, now)} ${selected === event.id ? "is-selected" : ""}`}
            aria-current={selected === event.id ? "true" : undefined} {...eventLabels(event, timeZone, owner)} onClick={()=>onSelect(event.id)}>
            <time>{clock(event.start_at!,timeZone)}</time>
            <strong className="oc-ev-title">{event.company || "Unknown company"}</strong>
            <EventIndicators event={event}/>
          </button>
        })}{items.length>3&&<button className="calendar-more" onClick={()=>onDay(day)}>+{items.length-3} more</button>}</div>
      </section>
    })}
  </div>
}
