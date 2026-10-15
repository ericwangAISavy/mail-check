import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink, RefreshCw, ScanSearch } from "lucide-react"
import { api, request } from "@/lib/api"
import type { Bootstrap, InterviewData, InterviewEvent, InterviewSource } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Loading, PageHeading, useToast } from "@/components/common"
import { Reader } from "@/pages/triage"
import InterviewCalendar from "@/components/interview-calendar"
import "./interviews.css"

const stateClass = (event: InterviewEvent) => event.display_status.toLowerCase().replaceAll(" ","-")
const dateTime = (value: string | null) => value ? new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "Unknown"
export default function InterviewsPage({ bootstrap }: {bootstrap: Bootstrap}) {
  const toast = useToast(), client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<number | null>(() => Number(params.get("event")) || null)
  const account = params.get("account") || "", status = params.get("status") || "", company = params.get("company") || ""
  const queryParams = new URLSearchParams()
  if (account) queryParams.set("account",account)
  if (status) queryParams.set("status",status)
  if (company) queryParams.set("company",company)
  const query = useQuery({queryKey:["interviews", "list", queryParams.toString()],queryFn:()=>request<InterviewData>(`/api/interviews?${queryParams}`),placeholderData:previous=>previous})
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
  const events = (query.data?.events || []).filter(event=>event.start_at)
  const refresh = async () => { const result = await query.refetch(); toast(result.error ? result.error.message : "Interviews refreshed.",result.error ? "error" : "success") }
  const check = useMutation({mutationFn:()=>api.post("/api/interviews/sync"),onSuccess:()=>{toast("Calendar collection started.","info");window.dispatchEvent(new Event("mailcheck:check-started"));void job.refetch()},onError:e=>toast(e.message,"error")})
  const backfill = useMutation({mutationFn:()=>api.post("/api/interviews/scan"),onSuccess:()=>{toast("Importing stored calendar invitations.","info");void scan.refetch();void job.refetch()},onError:e=>toast(e.message,"error")})
  const filterControls = <Card className="interview-filters"><label>Account<select aria-label="Account" value={account} onChange={e=>setFilter("account",e.target.value)}><option value="">All accounts</option>{query.data?.accounts.map(a=><option key={a.id} value={a.label}>{a.label}</option>)}</select></label><label>Status<select aria-label="Status" value={status} onChange={e=>setFilter("status",e.target.value)}><option value="">All statuses</option>{query.data?.statuses.map(s=><option key={s}>{s}</option>)}</select></label><label>Company<select aria-label="Company" value={company} onChange={e=>setFilter("company",e.target.value)}><option value="">All companies</option>{query.data?.companies.map(c=><option key={c}>{c}</option>)}</select></label><Button variant="outline" onClick={()=>backfill.mutate()} disabled={backfill.isPending || job.data?.running || scan.data?.running}><ScanSearch size={16}/>Import saved invitations</Button></Card>
  return <div className="page-wrap interviews-page">
    <PageHeading eyebrow="MEETING CALENDAR" title="Interviews" description="Meeting events from calendar invitations across your connected accounts." action={<div className="interview-actions"><Button variant="outline" onClick={()=>void refresh()} disabled={query.isFetching}><RefreshCw size={16}/>Refresh</Button><Button onClick={()=>check.mutate()} disabled={check.isPending || job.isPending || job.isError || job.data?.running || !bootstrap.readiness.accounts}>Check now</Button></div>}/>

    {scan.data && (scan.data.running || scan.data.processed>0) && <p className="scan-progress" role="status">{scan.data.running ? "Scanning" : "Last scan"}: {scan.data.processed} of {scan.data.total} invitations · {scan.data.found} event updates{scan.data.errors ? ` · ${scan.data.errors} need retry; run scan again to retry` : ""}{scan.data.running && <progress max={scan.data.total || 1} value={scan.data.processed}/>}</p>}
    {query.isPending ? <Loading/> : query.error ? <div role="alert" className="inline-error">{query.error.message}<Button variant="outline" onClick={()=>void refresh()}>Try again</Button></div> : <>
    <InterviewCalendar events={events} accounts={query.data?.accounts||[]} account={account} filterCount={[account,status,company].filter(Boolean).length} filters={filterControls} onSelect={select}/></>}
    <Dialog open={selected!==null} onOpenChange={open=>{if(!open)select(null)}}>{selected!==null && <InterviewDetails key={selected} id={selected} stages={query.data?.stages||[]} statuses={query.data?.statuses||[]}/>}</Dialog>
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
  const save=useMutation({mutationFn:()=>{const fields=new Set(dirty);if(fields.has("start_at")||fields.has("end_at"))fields.add("timezone");if(dirty.has("timezone")){fields.add("start_at");if(draft.end_at)fields.add("end_at")}const changes=Object.fromEntries([...fields].map(k=>[k,draft[k]===""?null:draft[k]]));return api.post(`/api/interviews/${event.id}`,changes)},onSuccess:async()=>{await client.invalidateQueries({queryKey:["interviews"]});toast("Interview corrections saved locally.","success");onSaved()},onError:e=>toast(e.message,"error")})
  return <form className="interview-editor" onSubmit={e=>{e.preventDefault();save.mutate()}}><p className="form-hint">Date and time fields use the timezone below. Use an IANA name, such as America/Chicago.</p><div className="interview-editor-grid">{[["company","Company"],["role","Role"],["start_at","Start date/time"],["end_at","End date/time"],["timezone","Timezone"],["meeting_url","Meeting URL"],["location","Location"]].map(([name,label])=><label key={name}>{label}<input type={name.endsWith("_at")?"datetime-local":name==="meeting_url"?"url":"text"} value={String(draft[name])} onChange={e=>set(name,e.target.value)} maxLength={1000}/></label>)}<label>Interview stage<select aria-label="Interview stage" value={String(draft.stage)} onChange={e=>set("stage",e.target.value)}>{stages.map(s=><option key={s}>{s}</option>)}</select></label><label>Status<select aria-label="Status" value={String(draft.status)} onChange={e=>set("status",e.target.value)}>{statuses.map(s=><option key={s}>{s}</option>)}</select></label></div><label>Notes<textarea value={String(draft.notes)} onChange={e=>set("notes",e.target.value)} maxLength={8000}/></label><label className="interview-review-checkbox"><input type="checkbox" checked={Boolean(draft.needs_review)} onChange={e=>set("needs_review",e.target.checked)}/>Needs review</label>{save.error && <p role="alert" className="inline-error">{save.error.message}</p>}<Button type="submit" disabled={save.isPending||!dirty.size}>{save.isPending?"Saving…":"Save corrections"}</Button></form>
}
