import { useEffect, useMemo, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { CalendarDays, ChevronLeft, ChevronRight, Clock3, ExternalLink, RefreshCw, ScanSearch } from "lucide-react"
import { api, request } from "@/lib/api"
import type { Bootstrap, InterviewData, InterviewEvent, InterviewSource } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Loading, PageHeading, useToast } from "@/components/common"
import { Reader } from "@/pages/triage"
import "./interviews.css"

type View = "month" | "week" | "day"
const key = (date: Date) => `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`
const addDays = (date: Date, days: number) => new Date(date.getFullYear(), date.getMonth(), date.getDate()+days)
const weekStart = (date: Date) => addDays(date, -((date.getDay()+6)%7))
const time = (value: string | null) => value ? new Intl.DateTimeFormat(undefined,{hour:"numeric",minute:"2-digit"}).format(new Date(value)) : "Time unknown"
const dateTime = (value: string | null) => value ? new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "Unknown"
const stateClass = (event: InterviewEvent) => event.display_status.toLowerCase().replaceAll(" ","-")
const onDay = (event: InterviewEvent, date: Date) => {
  if (!event.start_at) return false
  const start = new Date(event.start_at), end = event.end_at ? new Date(event.end_at) : start
  return start < addDays(date,1) && (end > date || key(start) === key(date))
}

function EventCard({ event, onSelect, compact = false }: {event: InterviewEvent; onSelect: (id: number) => void; compact?: boolean}) {
  return <button className={`interview-event ${stateClass(event)} ${compact ? "compact" : ""}`} onClick={() => onSelect(event.id)} aria-label={`${event.company || "Unknown company"}, ${event.stage}, ${dateTime(event.start_at)}, ${event.display_status}`}>
    <span className="event-time">{time(event.start_at)}</span><strong>{event.company || "Unknown company"}</strong>{event.role && <span className="event-role">{event.role}</span>}<span className="event-stage">{event.stage}</span>{event.display_status !== "Scheduled" && <span className="event-status">{event.display_status}</span>}
  </button>
}

export default function InterviewsPage({ bootstrap }: {bootstrap: Bootstrap}) {
  const toast = useToast(), client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [reviewPage, setReviewPage] = useState(0)
  const [view, setView] = useState<View>("month")
  const [date, setDate] = useState(() => new Date(new Date().setHours(0,0,0,0)))
  const [selected, setSelected] = useState<number | null>(() => Number(params.get("event")) || null)
  const account = params.get("account") || "", status = params.get("status") || "", company = params.get("company") || ""
  const queryParams = new URLSearchParams()
  if (account) queryParams.set("account",account)
  if (status) queryParams.set("status",status)
  if (company) queryParams.set("company",company)
  const query = useQuery({queryKey:["interviews", "list", queryParams.toString()],queryFn:()=>request<InterviewData>(`/api/interviews?${queryParams}`)})
  const scan = useQuery({queryKey:["interviews", "scan"],queryFn:()=>request<{running:boolean;processed:number;total:number;found:number;errors:number}>("/api/interviews/scan"),refetchInterval: q=>q.state.data?.running ? 1000 : 10000})
  const seenJob = useRef<number | null>(null)
  const job = useQuery({queryKey:["interview-job"],queryFn:api.status,refetchInterval:2000})
  useEffect(() => {
    if (job.data && seenJob.current !== job.data.completion_id) {
      if (seenJob.current !== null) void client.invalidateQueries({queryKey:["interviews"]})
      seenJob.current = job.data.completion_id
    }
  }, [job.data?.completion_id,client])
  useEffect(() => { if (scan.data && !scan.data.running && scan.data.processed) void client.invalidateQueries({queryKey:["interviews","list"]}) },[scan.data?.running,scan.data?.processed,client])
  useEffect(() => { setSelected(Number(params.get("event")) || null) },[params])
  const setFilter = (name: string,value: string) => { const next = new URLSearchParams(params); value ? next.set(name,value) : next.delete(name); setParams(next) }
  const select = (id: number | null) => { setSelected(id); const next = new URLSearchParams(params); id ? next.set("event",String(id)) : next.delete("event"); setParams(next,{replace:true}) }
  useEffect(() => setReviewPage(0), [account,status,company])
  const events = query.data?.events || []
  const now = new Date(), today = key(now), startWeek = weekStart(now), endWeek = addDays(startWeek,7)
  const upcoming = events.filter(e=>e.start_at && new Date(e.start_at)>=now && !["Cancelled","Completed","Needs review"].includes(e.display_status))
  const review = events.filter(e=>e.needs_review || e.display_status === "Needs review")
  useEffect(() => setReviewPage(p=>Math.min(p, Math.max(0,Math.ceil(review.length/10)-1))), [review.length])
  const summary = [ ["Upcoming",upcoming.length], ["This Week",events.filter(e=>e.start_at && new Date(e.start_at)>=startWeek && new Date(e.start_at)<endWeek && e.display_status!=="Cancelled").length], ["Needs Review",review.length], ["Completed",events.filter(e=>e.display_status==="Completed").length] ] as const
  const days = useMemo(()=>{
    const first = view === "month" ? weekStart(new Date(date.getFullYear(),date.getMonth(),1)) : view === "week" ? weekStart(date) : date
    return Array.from({length:view === "month" ? 42 : view === "week" ? 7 : 1},(_,i)=>addDays(first,i))
  },[date,view])
  const navigate = (direction: number) => setDate(view === "month" ? new Date(date.getFullYear(),date.getMonth()+direction,1) : addDays(date,direction*(view === "week" ? 7 : 1)))
  const refresh = async () => { const result = await query.refetch(); toast(result.error ? result.error.message : "Interviews refreshed.",result.error ? "error" : "success") }
  const check = useMutation({mutationFn:api.startCheck,onSuccess:()=>{toast("Check started. Your inbox stays read-only.","info");void job.refetch()},onError:e=>toast(e.message,"error")})
  const backfill = useMutation({mutationFn:()=>api.post("/api/interviews/scan"),onSuccess:()=>{toast("Scanning existing local mail for interviews.","info");void scan.refetch();void job.refetch()},onError:e=>toast(e.message,"error")})
  const heading = view === "month" ? date.toLocaleDateString(undefined,{month:"long",year:"numeric"}) : view === "week" ? `${days[0].toLocaleDateString(undefined,{month:"short",day:"numeric"})} – ${days[6].toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"})}` : date.toLocaleDateString(undefined,{weekday:"long",month:"long",day:"numeric",year:"numeric"})
  return <div className="page-wrap interviews-page">
    <PageHeading eyebrow="INTERVIEW PIPELINE" title="Interviews" description="Interview schedules detected across your connected accounts." action={<div className="interview-actions"><Button variant="outline" onClick={()=>void refresh()} disabled={query.isFetching}><RefreshCw size={16}/>Refresh</Button><Button onClick={()=>check.mutate()} disabled={check.isPending || job.isPending || job.isError || job.data?.running || !bootstrap.readiness.model || !bootstrap.readiness.accounts}>Check now</Button><Button variant="outline" onClick={()=>setDate(new Date(new Date().setHours(0,0,0,0)))}>Today</Button></div>}/>
    <Card className="interview-filters"><label>Account<select aria-label="Account" value={account} onChange={e=>setFilter("account",e.target.value)}><option value="">All accounts</option>{query.data?.accounts.map(a=><option key={a.id} value={a.label}>{a.label}</option>)}</select></label><label>Status<select aria-label="Status" value={status} onChange={e=>setFilter("status",e.target.value)}><option value="">All statuses</option>{query.data?.statuses.map(s=><option key={s}>{s}</option>)}</select></label><label>Company<select aria-label="Company" value={company} onChange={e=>setFilter("company",e.target.value)}><option value="">All companies</option>{query.data?.companies.map(c=><option key={c}>{c}</option>)}</select></label><Button variant="outline" onClick={()=>backfill.mutate()} disabled={backfill.isPending || job.data?.running || scan.data?.running}><ScanSearch size={16}/>Scan existing mail</Button></Card>
    {scan.data && (scan.data.running || scan.data.processed>0) && <p className="scan-progress" role="status">{scan.data.running ? "Scanning" : "Last scan"}: {scan.data.processed} of {scan.data.total} messages · {scan.data.found} interview updates{scan.data.errors ? ` · ${scan.data.errors} need retry; run scan again to retry` : ""}{scan.data.running && <progress max={scan.data.total || 1} value={scan.data.processed}/>}</p>}
    {query.isPending ? <Loading/> : query.error ? <div role="alert" className="inline-error">{query.error.message}<Button variant="outline" onClick={()=>void refresh()}>Try again</Button></div> : <>
    <div className="interview-summary">{summary.map(([label,count])=><Card key={label}><span>{label}</span><strong>{count}</strong></Card>)}</div>
    <div className="interview-layout"><Card className="interview-calendar"><div className="calendar-toolbar"><div className="calendar-navigation"><Button variant="ghost" size="icon" aria-label="Previous calendar period" onClick={()=>navigate(-1)}><ChevronLeft/></Button><h2 aria-live="polite">{heading}</h2><Button variant="ghost" size="icon" aria-label="Next calendar period" onClick={()=>navigate(1)}><ChevronRight/></Button></div><div className="calendar-views" role="group" aria-label="Calendar view">{(["month","week","day"] as const).map(v=><Button key={v} size="sm" variant={view===v?"secondary":"ghost"} aria-pressed={view===v} onClick={()=>setView(v)}>{v[0].toUpperCase()+v.slice(1)}</Button>)}</div></div>
      <p className="calendar-timezone"><Clock3 size={14}/>Times shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}. Original timezone is retained in event details.</p>
      <div className={`calendar-grid view-${view}`} aria-label={`${view} calendar`}>{view==="month" && ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map(day=><div className="calendar-weekday" key={day}>{day}</div>)}{days.map(day=>{const dayEvents=events.filter(e=>onDay(e,day));return <section key={key(day)} className={`calendar-day ${key(day)===today?"is-today":""} ${view==="month" && day.getMonth()!==date.getMonth()?"other-month":""}`} aria-label={day.toLocaleDateString(undefined,{dateStyle:"full"})}><button className="calendar-day-label" onClick={()=>{setDate(day);setView("day")}}>{view==="month" ? day.getDate() : day.toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"})}{key(day)===today && <span className="sr-only"> Today</span>}</button><div className="calendar-events">{(view==="month"?dayEvents.slice(0,3):dayEvents).map(event=><EventCard key={event.id} event={event} compact={view==="month"} onSelect={select}/>)}{view==="month" && dayEvents.length>3 && <button className="calendar-more" onClick={()=>{setDate(day);setView("day")}}>+{dayEvents.length-3} more</button>}{view!=="month" && !dayEvents.length && <p className="calendar-no-events">No interviews</p>}</div></section>})}</div>
      {!events.length && <div className="calendar-empty"><CalendarDays size={24}/><p>No interviews match this view. Check your inbox or scan existing mail to discover schedules.</p></div>}
    </Card><aside className="interview-rail"><Card><p className="eyebrow">UPCOMING INTERVIEWS</p>{upcoming.slice(0,8).map(event=><div key={event.id} className="upcoming-item"><p>{key(new Date(event.start_at!))===today?"TODAY":key(new Date(event.start_at!))===key(addDays(now,1))?"TOMORROW":new Date(event.start_at!).toLocaleDateString(undefined,{month:"short",day:"numeric"})}</p><EventCard event={event} onSelect={select}/></div>)}{!upcoming.length && <p className="rail-empty">No confirmed upcoming interviews.</p>}</Card><Card><p className="eyebrow">NEEDS REVIEW</p><p className="rail-context">Uncertain dates and details stay here until verified.</p>{review.slice(reviewPage*10,(reviewPage+1)*10).map(event=><EventCard key={event.id} event={event} onSelect={select}/>)}{review.length>10 && <div className="review-pagination"><Button size="sm" variant="ghost" disabled={reviewPage===0} onClick={()=>setReviewPage(p=>p-1)}>Previous</Button><span>{reviewPage*10+1}–{Math.min((reviewPage+1)*10,review.length)} of {review.length}</span><Button size="sm" variant="ghost" disabled={(reviewPage+1)*10>=review.length} onClick={()=>setReviewPage(p=>p+1)}>Next</Button></div>}{!review.length && <p className="rail-empty">No interviews need review.</p>}</Card></aside></div></>}
    <Dialog open={selected!==null} onOpenChange={open=>{if(!open)select(null)}}>{selected!==null && <InterviewDetails id={selected} stages={query.data?.stages||[]} statuses={query.data?.statuses||[]}/>}</Dialog>
  </div>
}

function localInput(value: string | null, zone: string) {
  if (!value) return ""
  try {
    const parts = new Intl.DateTimeFormat("en-CA",{timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date(value))
    const p = Object.fromEntries(parts.map(x=>[x.type,x.value]))
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
  } catch { return "" }
}
function InterviewDetails({id,stages,statuses}:{id:number;stages:string[];statuses:string[]}) {
  const query = useQuery({queryKey:["interviews","detail",id],queryFn:()=>request<{event:InterviewEvent;sources:InterviewSource[]}>(`/api/interviews/${id}`)})
  const [editing,setEditing] = useState(false), [sourcePk,setSourcePk] = useState<number|null>(null)
  const source = useQuery({queryKey:["reader",sourcePk],queryFn:()=>api.reader(sourcePk!),enabled:sourcePk!==null})
  const event = query.data?.event
  return <DialogContent className="interview-dialog"><DialogHeader><DialogTitle>{sourcePk ? "Source email" : event?.company || "Interview details"}</DialogTitle><DialogDescription>{sourcePk ? "Original mail in the existing Mailcheck reader." : "Detected schedule, source emails, and local corrections."}</DialogDescription></DialogHeader>
    {query.isPending ? <Loading/> : query.error ? <p role="alert" className="inline-error">{query.error.message}</p> : event && (sourcePk ? <><Button variant="outline" onClick={()=>setSourcePk(null)}>Back to interview</Button>{source.isPending ? <Loading/> : source.error ? <p role="alert">{source.error.message}</p> : source.data && <Reader message={source.data.message} mobile onBack={()=>setSourcePk(null)} onDone={()=>undefined} busy={false} readOnly/>}</> : <>
    <div className="interview-detail-status"><span className={`interview-status ${stateClass(event)}`}>{event.display_status}</span><Button variant="outline" onClick={()=>setEditing(!editing)}>{editing?"Cancel editing":"Edit details"}</Button></div>
    {editing ? <InterviewEditor event={event} stages={stages} statuses={statuses} onSaved={()=>setEditing(false)}/> : <>
      {event.needs_review && <p className="review-note">Needs review: {event.review_reason || "Verify details against the source email."}</p>}
      <dl className="interview-details">{[["Company",event.company],["Role",event.role],["Interview stage",event.stage],["Start",dateTime(event.start_at)],["End",dateTime(event.end_at)],["Original timezone",event.timezone],["Display timezone",Intl.DateTimeFormat().resolvedOptions().timeZone],["Meeting platform",event.meeting_platform],["Location",event.location],["Organizer",[event.organizer_name,event.organizer_email].filter(Boolean).join(" · ")],["Participants",event.participants.join(", ")],["Detected status",event.status],["Last updated",dateTime(event.updated_at)],["Notes",event.notes]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value||"Unknown"}</dd></div>)}</dl>
      {event.meeting_url && <a className="interview-meeting-link" href={event.meeting_url} target="_blank" rel="noopener noreferrer">Open {event.meeting_platform || "meeting"} link <ExternalLink size={14}/></a>}
      {!!event.manual_fields.length && <p className="form-hint">Manually corrected fields are protected from later automated updates.</p>}
    </>}
    <div className="interview-sources"><h2>Source emails</h2>{query.data?.sources.map(s=><article key={s.id}><strong>{s.source_subject}</strong><p>{s.account_email} · {s.source_sender}</p><p>{dateTime(s.source_received_at)}</p>{s.message_pk ? <Button size="sm" variant="outline" onClick={()=>setSourcePk(s.message_pk)}>View source email</Button> : <p className="form-hint">Email aged out of local retention. Source metadata is preserved.</p>}</article>)}</div>
    </>)}
  </DialogContent>
}
function InterviewEditor({event,stages,statuses,onSaved}:{event:InterviewEvent;stages:string[];statuses:string[];onSaved:()=>void}) {
  const client=useQueryClient(), toast=useToast()
  const initialZone=(()=>{try{new Intl.DateTimeFormat(undefined,{timeZone:event.timezone||""});return event.timezone!}catch{return Intl.DateTimeFormat().resolvedOptions().timeZone}})()
  const [draft,setDraft]=useState<Record<string,string|boolean>>({company:event.company||"",role:event.role||"",stage:event.stage,status:event.status,start_at:localInput(event.start_at,initialZone),end_at:localInput(event.end_at,initialZone),timezone:initialZone,meeting_url:event.meeting_url||"",location:event.location||"",notes:event.notes||"",needs_review:event.needs_review})
  const [dirty,setDirty]=useState<Set<string>>(new Set())
  const set=(name:string,value:string|boolean)=>{setDraft(d=>({...d,[name]:value}));setDirty(d=>new Set([...d,name]))}
  const save=useMutation({mutationFn:()=>{const fields=new Set(dirty);if(fields.has("timezone")){fields.add("start_at");if(draft.end_at)fields.add("end_at")}const changes=Object.fromEntries([...fields].map(k=>[k,draft[k]===""?null:draft[k]]));return api.post(`/api/interviews/${event.id}`,changes)},onSuccess:async()=>{await client.invalidateQueries({queryKey:["interviews"]});toast("Interview corrections saved locally.","success");onSaved()},onError:e=>toast(e.message,"error")})
  return <form className="interview-editor" onSubmit={e=>{e.preventDefault();save.mutate()}}><p className="form-hint">Date and time fields use the timezone below. Use an IANA name, such as America/Chicago.</p><div className="interview-editor-grid">{[["company","Company"],["role","Role"],["start_at","Start date/time"],["end_at","End date/time"],["timezone","Timezone"],["meeting_url","Meeting URL"],["location","Location"]].map(([name,label])=><label key={name}>{label}<input type={name.endsWith("_at")?"datetime-local":name==="meeting_url"?"url":"text"} value={String(draft[name])} onChange={e=>set(name,e.target.value)} maxLength={1000}/></label>)}<label>Interview stage<select aria-label="Interview stage" value={String(draft.stage)} onChange={e=>set("stage",e.target.value)}>{stages.map(s=><option key={s}>{s}</option>)}</select></label><label>Status<select aria-label="Status" value={String(draft.status)} onChange={e=>set("status",e.target.value)}>{statuses.map(s=><option key={s}>{s}</option>)}</select></label></div><label>Notes<textarea value={String(draft.notes)} onChange={e=>set("notes",e.target.value)} maxLength={8000}/></label><label className="interview-review-checkbox"><input type="checkbox" checked={Boolean(draft.needs_review)} onChange={e=>set("needs_review",e.target.checked)}/>Needs review</label>{save.error && <p role="alert" className="inline-error">{save.error.message}</p>}<Button type="submit" disabled={save.isPending||!dirty.size}>{save.isPending?"Saving…":"Save corrections"}</Button></form>
}
