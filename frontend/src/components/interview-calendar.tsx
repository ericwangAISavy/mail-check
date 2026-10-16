import { useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react"
import { useSearchParams } from "react-router-dom"
import { CalendarCheck2, CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Circle, Columns2, Columns3, Download, Expand, Filter, Link, Minimize, PanelTop, Printer, Share2 } from "lucide-react"
import { Button } from "@/components/ui/button"
import type { InterviewEvent } from "@/lib/types"
import { dayKey, exportInterviews, fallsOnDay, HOUR_HEIGHT, parseDay, placeEvents, shiftDays, startOfDay, viewDays, type CalendarView } from "@/lib/interview-calendar"
import { useToast } from "@/components/common"

const labels: Record<CalendarView,string> = {workweek:"Work week",week:"Week",month:"Month",day:"Day"}
const icons = {workweek:PanelTop,week:Columns3,month:CalendarDays,day:PanelTop}
const clock = (value: string) => new Date(value).toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit"})
const statusClass = (event: InterviewEvent) => event.display_status.toLowerCase().replaceAll(" ","-")
const title = (event: InterviewEvent) => `${event.company || "Unknown company"}${event.role ? " · " + event.role : ""} · ${event.stage}`
const timeLabel = (event: InterviewEvent) => `${event.start_at ? new Date(event.start_at).toLocaleString(undefined,{dateStyle:"medium",timeStyle:"short"}) : "Time unknown"}${event.end_at ? " – " + clock(event.end_at) : " · End time unknown"}`
const accessible = (event: InterviewEvent) => `${event.company || "Unknown company"}, ${event.stage}, ${timeLabel(event)}, ${event.display_status}`
const accountColor = (event: InterviewEvent, accounts: Account[], account?: string) => Math.max(0,accounts.findIndex(a=>a.label===(account || event.account_labels?.[0]))) % 3

type Account = {id:number;label:string;email:string}
type Props = { events: InterviewEvent[]; accounts: Account[]; account: string; filterCount: number; filters: ReactNode; onSelect:(id:number)=>void }
export default function InterviewCalendar({events,accounts,account,filterCount,filters,onSelect}:Props) {
  const [params,setParams]=useSearchParams(), toast=useToast()
  const initialDay=useRef(startOfDay(new Date()))
  const viewParam=params.get("calendar_view"), dayParam=params.get("calendar_date")
  const view:CalendarView = viewParam && Object.keys(labels).includes(viewParam) ? viewParam as CalendarView : "workweek"
  const date=useMemo(()=>parseDay(dayParam)||initialDay.current,[dayParam])
  const days=useMemo(()=>viewDays(date,view),[date,view])
  const [filterOpen,setFilterOpen]=useState(false), [split,setSplit]=useState(false), [expanded,setExpanded]=useState(false)
  const [shareOpen,setShareOpen]=useState(false), [dateOpen,setDateOpen]=useState(false)
  const [now,setNow]=useState(()=>new Date())
  const shareRef=useRef<HTMLDivElement>(null), dateRef=useRef<HTMLDivElement>(null), calendarRef=useRef<HTMLElement>(null)
  useEffect(()=>{const timer=window.setInterval(()=>setNow(new Date()),60000);return()=>clearInterval(timer)},[])
  useEffect(()=>{
    const escape=(event:KeyboardEvent)=>{
      if(document.querySelector(".interview-dialog"))return
      if(event.key==="Escape"){setExpanded(false);setShareOpen(false);setDateOpen(false)}
      if(expanded&&event.key==="Tab"){
        const controls=Array.from(calendarRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled),input,select,[tabindex='0']")||[]).filter(el=>el.getClientRects().length)
        const first=controls[0],last=controls[controls.length-1]
        if(first&&last&&(event.shiftKey&&document.activeElement===first||!event.shiftKey&&document.activeElement===last||!calendarRef.current?.contains(document.activeElement))){event.preventDefault();(event.shiftKey?last:first).focus()}
      }
    }
    const outside=(event:PointerEvent)=>{if(!shareRef.current?.contains(event.target as Node))setShareOpen(false);if(!dateRef.current?.contains(event.target as Node))setDateOpen(false)}
    document.addEventListener("keydown",escape);document.addEventListener("pointerdown",outside)
    return()=>{document.removeEventListener("keydown",escape);document.removeEventListener("pointerdown",outside)}
  },[expanded])
  const update=(nextView:CalendarView,nextDate:Date)=>{const next=new URLSearchParams(params);next.set("calendar_view",nextView);next.set("calendar_date",dayKey(nextDate));setParams(next)}
  const navigate=(direction:number)=>update(view,view==="month"?new Date(date.getFullYear(),date.getMonth()+direction,1):shiftDays(date,direction*(view==="day"?1:7)))
  const jumpDay=(day:Date)=>update("day",day)
  const heading=view==="month"?date.toLocaleDateString(undefined,{month:"long",year:"numeric"}):view==="day"?date.toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric",year:"numeric"}):new Intl.DateTimeFormat(undefined,{month:"long",day:"numeric",year:"numeric"}).formatRange(days[0],days[days.length-1])
  const splitAccounts=accounts.filter(a=>!account||a.label===account)
  const hiddenWeekend=view==="workweek"?events.filter(e=>e.start_at && new Date(e.start_at)>=days[0] && new Date(e.start_at)<shiftDays(days[0],7) && !days.some(day=>fallsOnDay(e,day))).length:0
  const copyLink=async()=>{try{const url=new URL(window.location.href);url.search=params.toString();url.searchParams.delete("event");url.searchParams.set("calendar_view",view);url.searchParams.set("calendar_date",dayKey(date));await navigator.clipboard.writeText(url.toString());toast("Calendar link copied.","success");setShareOpen(false)}catch{toast("Could not copy the link. Copy this page’s address from your browser.","error")}}
  const download=()=>{const file=new Blob([exportInterviews(events)],{type:"text/calendar;charset=utf-8"});const url=URL.createObjectURL(file),link=document.createElement("a");link.href=url;link.download="mailcheck-interviews.ics";link.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);setShareOpen(false)}
  return <section ref={calendarRef} className={`outlook-calendar ${expanded?"calendar-expanded":""}`} aria-label="Interview calendar">
    <div className="outlook-command-bar"><div className="outlook-view-options" role="group" aria-label="Calendar view">{(["workweek","week","month","day"] as const).map(v=>{const Icon=icons[v];return <Button key={v} variant="ghost" size="sm" aria-pressed={view===v} onClick={()=>update(v,date)}><Icon size={15}/>{labels[v]}</Button>})}</div>
      <Button variant="ghost" size="sm" aria-pressed={split} onClick={()=>setSplit(!split)} title="Show each connected account’s calendar side by side"><Columns2 size={15}/>Split view</Button><span className="outlook-command-divider"/>
      <Button variant="ghost" size="sm" aria-expanded={filterOpen} aria-controls="calendar-filter-panel" onClick={()=>setFilterOpen(!filterOpen)}><Filter size={15}/>Filter{filterCount>0&&<span className="calendar-filter-count">{filterCount}</span>}<ChevronDown size={12}/></Button>
      <div className="outlook-menu-anchor" ref={shareRef}><Button variant="ghost" size="sm" aria-expanded={shareOpen} aria-controls="calendar-share-menu" onClick={()=>setShareOpen(!shareOpen)}><Share2 size={15}/>Share<ChevronDown size={12}/></Button>{shareOpen&&<div className="outlook-menu" id="calendar-share-menu"><button onClick={()=>void copyLink()}><Link size={15}/>Copy calendar link</button><button onClick={download}><Download size={15}/>Download calendar (.ics)</button></div>}</div>
      <Button variant="ghost" size="sm" onClick={()=>window.print()}><Printer size={15}/>Print</Button><Button className="calendar-expand-button" variant="ghost" size="icon" aria-label={expanded?"Restore calendar size":"Expand calendar"} aria-pressed={expanded} onClick={()=>setExpanded(!expanded)}>{expanded?<Minimize size={16}/>:<Expand size={16}/>}</Button>
    </div>
    {filterOpen&&<div id="calendar-filter-panel" className="outlook-filter-panel">{filters}</div>}
    <div className="outlook-date-bar"><Button variant="outline" size="sm" onClick={()=>update(view,startOfDay(new Date()))}><CalendarCheck2 size={15}/>Today</Button><Button variant="ghost" size="icon" aria-label="Previous calendar period" onClick={()=>navigate(-1)}><ChevronLeft size={18}/></Button><Button variant="ghost" size="icon" aria-label="Next calendar period" onClick={()=>navigate(1)}><ChevronRight size={18}/></Button><div className="outlook-menu-anchor" ref={dateRef}><button className="outlook-period" aria-expanded={dateOpen} aria-controls="calendar-date-picker" onClick={()=>setDateOpen(!dateOpen)}><span aria-live="polite">{heading}</span><ChevronDown size={13}/></button>{dateOpen&&<div className="outlook-menu" id="calendar-date-picker"><label>Go to date<input type="date" aria-label="Go to date" value={dayKey(date)} onChange={e=>{const chosen=parseDay(e.target.value);if(chosen){update(view,chosen);setDateOpen(false)}}}/></label></div>}</div><span className="outlook-zone">{Intl.DateTimeFormat().resolvedOptions().timeZone}</span></div>

    <div className={`outlook-calendars ${split&&splitAccounts.length>1?"is-split":""}`}>{(split&&splitAccounts.length?splitAccounts:[null]).map(a=><div className="outlook-account-calendar" key={a?.id||"all"}>{split&&a&&<div className="outlook-account-name"><Circle size={9} fill="currentColor"/>{a.label}<span>{a.email}</span></div>}{view==="month"?<MonthGrid date={date} days={days} events={a?events.filter(e=>e.account_labels?.includes(a.label)):events} accounts={accounts} account={a?.label||account} now={now} onSelect={onSelect} onDay={jumpDay}/>:<TimeGrid days={days} view={view} events={a?events.filter(e=>e.account_labels?.includes(a.label)):events} accounts={accounts} account={a?.label||account} now={now} onSelect={onSelect} onDay={jumpDay}/>}</div>)}</div>
    {(hiddenWeekend>0)&&<div className="outlook-calendar-notices">{hiddenWeekend>0&&<button onClick={()=>update("week",date)}>{hiddenWeekend} {hiddenWeekend===1?"interview is":"interviews are"} on the weekend · Show week</button>}</div>}
  </section>
}

function TimeGrid({days,view,events,accounts,account,now,onSelect,onDay}:{days:Date[];view:CalendarView;events:InterviewEvent[];accounts:Account[];account:string;now:Date;onSelect:(id:number)=>void;onDay:(day:Date)=>void}) {
  const scroll=useRef<HTMLDivElement>(null)
  const period=dayKey(days[0])
  useEffect(()=>{if(scroll.current)scroll.current.scrollTop=8*HOUR_HEIGHT},[period,view])
  const style={"--calendar-days":days.length,"--hour-height":`${HOUR_HEIGHT}px`} as CSSProperties
  const syncScroll=()=>{
    const current=scroll.current
    if(current)current.closest(".outlook-calendars.is-split")?.querySelectorAll<HTMLDivElement>(".outlook-scroll").forEach(other=>{if(other!==current&&Math.abs(other.scrollTop-current.scrollTop)>1)other.scrollTop=current.scrollTop})
  }
  return <div className="outlook-scroll" ref={scroll} onScroll={syncScroll} style={style} aria-label={`${labels[view].toLowerCase()} calendar`} tabIndex={0}>
    <div className="outlook-day-headers"><div className="outlook-axis-heading"/>{days.map(day=><button key={dayKey(day)} className={`outlook-day-heading ${dayKey(day)===dayKey(now)?"is-today":""}`} onClick={()=>onDay(day)} aria-label={`Show ${day.toLocaleDateString(undefined,{dateStyle:"full"})}`}><span>{day.getDate()}</span><span>{day.toLocaleDateString(undefined,{weekday:"long"})}</span></button>)}</div>
    <div className="outlook-time-grid"><div className="outlook-time-axis" aria-hidden="true">{Array.from({length:24},(_,hour)=><div key={hour} className="outlook-hour-label"><span>{new Date(2000,0,1,hour).toLocaleTimeString(undefined,{hour:"numeric"})}</span></div>)}</div>{days.map(day=><section key={dayKey(day)} className={`calendar-day outlook-day-column ${dayKey(day)===dayKey(now)?"is-today":""}`} aria-label={day.toLocaleDateString(undefined,{dateStyle:"full"})}>{Array.from({length:24},(_,hour)=><div key={hour} className="outlook-hour-line" aria-hidden="true"/>)}{placeEvents(events,day).map(p=>{const height=(p.end-p.start)*HOUR_HEIGHT/60;return <button key={p.event.id} data-event-id={p.event.id} data-start-minute={p.start} data-lane={p.lane} className={`interview-event outlook-time-event account-color-${accountColor(p.event,accounts,account)} ${statusClass(p.event)} ${p.unknownEnd?"duration-unknown":""} ${height<42?"is-short":height<64?"is-medium":""}`} aria-label={accessible(p.event)} title={`${title(p.event)}\n${timeLabel(p.event)}\n${p.event.meeting_platform||p.event.location||p.event.display_status}`} onClick={()=>onSelect(p.event.id)} style={{top:`min(calc(var(--hour-height) * ${p.start/60}), calc(var(--hour-height) * 24 - 18px))`,height:`max(18px, calc(var(--hour-height) * ${(p.end-p.start)/60} - 3px))`,left:`calc(${p.lane*100/p.lanes}% + 2px)`,width:`calc(${100/p.lanes}% - 5px)`}}><strong>{p.continuesBefore?"Continues · ":""}{p.event.company||"Unknown company"}{p.event.role?" · "+p.event.role:""}</strong><span>{p.event.stage}{p.event.meeting_platform?" · "+p.event.meeting_platform:""}</span><span>{clock(p.event.start_at!)}{p.event.end_at?" – "+clock(p.event.end_at):" · End time unknown"}{p.continuesAfter?" · Continues":""}</span></button>})}{dayKey(day)===dayKey(now)&&<div className="outlook-now-line" style={{top:`calc(var(--hour-height) * ${now.getHours()+now.getMinutes()/60})`}} aria-label={`Current time ${now.toLocaleTimeString(undefined,{hour:"numeric",minute:"2-digit"})}`}/>}</section>)}</div>
  </div>
}
function MonthGrid({date,days,events,accounts,account,now,onSelect,onDay}:{date:Date;days:Date[];events:InterviewEvent[];accounts:Account[];account:string;now:Date;onSelect:(id:number)=>void;onDay:(day:Date)=>void}) {
  return <div className="outlook-month-grid calendar-grid view-month" aria-label="month calendar">{["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"].map(day=><div className="outlook-month-weekday" key={day}><span>{day}</span><abbr title={day}>{day.slice(0,3)}</abbr></div>)}{days.map(day=>{const items=events.filter(e=>fallsOnDay(e,day));return <section key={dayKey(day)} className={`calendar-day outlook-month-day ${day.getMonth()!==date.getMonth()?"other-month":""} ${dayKey(day)===dayKey(now)?"is-today":""}`} aria-label={day.toLocaleDateString(undefined,{dateStyle:"full"})}><button className="calendar-day-label" onClick={()=>onDay(day)} aria-label={`Show ${day.toLocaleDateString(undefined,{dateStyle:"full"})}`}>{day.getDate()}</button><div>{items.slice(0,3).map(event=><button key={event.id} className={`interview-event outlook-month-event account-color-${accountColor(event,accounts,account)} ${statusClass(event)}`} onClick={()=>onSelect(event.id)} aria-label={accessible(event)} title={`${title(event)}\n${timeLabel(event)}`}><time>{clock(event.start_at!)}</time><strong>{event.company||"Unknown company"}</strong></button>)}{items.length>3&&<button className="calendar-more" onClick={()=>onDay(day)}>+{items.length-3} more</button>}</div></section>})}</div>
}
