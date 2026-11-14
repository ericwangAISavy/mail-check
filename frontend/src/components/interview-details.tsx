import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink } from "lucide-react"
import { api, request } from "@/lib/api"
import type { InterviewEvent, InterviewSource } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Loading, useToast } from "@/components/common"
import { InterviewJobMatches } from "@/components/interview-job-matches"
import "@/pages/interviews.css"

const stateClass = (event: InterviewEvent) => event.display_status.toLowerCase().replaceAll(" ","-")
const dateTime = (value: string | null, timeZone?:string) => value ? new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short",timeZone}).format(new Date(value)) : "Unknown"

function localInput(value: string | null, zone: string) {
  if (!value) return ""
  try {
    const parts = new Intl.DateTimeFormat("en-CA",{timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date(value))
    const p = Object.fromEntries(parts.map(x=>[x.type,x.value]))
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
  } catch { return "" }
}
export function InterviewDetails({id,stages,statuses,displayTimezone,onCloseAutoFocus,onRemoved}:{id:number;displayTimezone?:string;stages?:string[];statuses?:string[];onCloseAutoFocus?:(event:Event)=>void;onRemoved?:()=>void}) {
  const query = useQuery({queryKey:["interviews","detail",id],queryFn:({ signal }) =>request<{event:InterviewEvent;sources:InterviewSource[];stages:string[];statuses:string[]}>(`/api/interviews/${id}`, { signal })})
  const client = useQueryClient()
  const [removed, setRemoved] = useState(false)
  const remove = useMutation({
    mutationFn: () => api.post(`/api/interviews/${id}/remove`),
    onSuccess: async () => { setRemoved(true); onRemoved?.(); await client.invalidateQueries({queryKey:["interviews"]}) },
  })
  const [editing,setEditing] = useState(false)
  const event = query.data?.event
  const sources = query.data?.sources || []
  const accountEmails = new Set(sources.map(source => source.account_email.trim().toLowerCase()).filter(Boolean))
  const accounts = [...new Map(sources.map(source => { const value = source.account_email.trim() || source.account_label; return [value.toLowerCase(), value] })).values()].filter(Boolean)
  const contacts = new Map<string, string>()
  const addContact = (value: string | null, name?: string | null) => {
    if (!value) return
    const key = (value.match(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/i)?.[0] || value).trim().toLowerCase()
    if (!key || accountEmails.has(key) || contacts.has(key)) return
    contacts.set(key, name ? `${name} · ${value}` : value)
  }
  if (event?.interviewers?.length || event?.manual_fields.includes("interviewers")) {
    event.interviewers?.forEach(person => addContact(person))
  } else {
    addContact(event?.organizer_email || event?.organizer_name || null, event?.organizer_email ? event.organizer_name : null)
    event?.participants.forEach(participant => addContact(participant))
  }
  // Native calendars provide a title, not a structured company or role.
  // Keep the title above, but do not mislabel it as an extracted company.
  const titleAsCompany = event && !event.manual_fields.includes("company") &&
    /\b(interview|confirmed|meeting|screening|call)\b/i.test(event.company || "") &&
    sources.some(source => source.message_pk === null && source.source_subject === event.company)
  const company = titleAsCompany ? null : event?.company
  const httpUrl = (value: string | null | undefined) => {
    try { const url = new URL(value || ""); return ["http:","https:"].includes(url.protocol) ? url.href : null } catch { return null }
  }
  const meetingUrl = httpUrl(event?.meeting_url)
  const locationUrl = httpUrl(event?.location)
  const joinUrl = meetingUrl || locationUrl
  const physicalLocation = event?.location && !locationUrl ? event.location : null
  const zone = displayTimezone || Intl.DateTimeFormat().resolvedOptions().timeZone
  const zoneLabel = event?.start_at ? new Intl.DateTimeFormat(undefined, { timeZone: zone, timeZoneName: "short" }).formatToParts(new Date(event.start_at)).find(part => part.type === "timeZoneName")?.value : null
  return <DialogContent className="interview-dialog" onCloseAutoFocus={onCloseAutoFocus}><DialogHeader><DialogTitle>{event?.company || "Meeting details"}</DialogTitle><DialogDescription>Interview time, account, and meeting details.</DialogDescription></DialogHeader>
    {removed ? <p role="status">Event removed from calendar.</p> : query.isPending ? <Loading/> : query.error ? <p role="alert" className="inline-error">{query.error.message}</p> : event && <>
    <div className="interview-detail-status"><span className={`interview-status ${stateClass(event)}`}>{event.display_status}</span><Button variant="outline" onClick={()=>setEditing(!editing)}>{editing?"Cancel editing":"Edit details"}</Button></div>
    {editing ? <InterviewEditor displayTimezone={displayTimezone} event={event} stages={stages || query.data?.stages || []} statuses={statuses || query.data?.statuses || []} onSaved={()=>setEditing(false)}/> : <>
      {event.needs_review && <p className="review-note">Needs review: {event.review_reason || "Verify the event details in your calendar."}</p>}
      <div className="interview-time-summary"><span>When</span><strong>{dateTime(event.start_at,displayTimezone)}{event.end_at ? ` – ${dateTime(event.end_at,displayTimezone)}` : ""}{zoneLabel ? ` (${zoneLabel})` : ""}</strong></div>
      <dl className="interview-details interview-essential-details">
        <div><dt>Email account</dt><dd>{accounts.length ? accounts.map(account => <span className="interview-detail-line" key={account}>{account}</span>) : "Not provided"}</dd></div>
        <div><dt>Company</dt><dd>{company || "Not provided"}</dd></div>
        <div><dt>Role</dt><dd>{event.role || "Not provided"}</dd></div>
        <div><dt>Interviewer / contact</dt><dd>{contacts.size ? [...contacts].map(([key,contact]) => <span className="interview-detail-line" key={key}>{contact}</span>) : "Not provided"}</dd></div>
        <div><dt>Location</dt><dd>{physicalLocation || (joinUrl ? "Online" : "Not provided")}</dd></div>
        {joinUrl && <div className="interview-location"><dt>Meeting link</dt><dd><a className="interview-meeting-link interview-explicit-link" href={joinUrl} target="_blank" rel="noopener noreferrer">{joinUrl}<ExternalLink size={14} aria-hidden="true"/></a></dd></div>}
      </dl>
      <InterviewJobMatches id={id}/>
    </>}
    {editing && <div className="interview-dialog-maintenance"><Button variant="destructive" disabled={remove.isPending} onClick={()=>remove.mutate()}>{remove.isPending ? "Removing…" : "Remove from calendar"}</Button>
    <p className="form-hint">Removes this event from this app. Your connected calendar is unchanged.</p>
    {remove.error && <p role="alert" className="inline-error">{remove.error.message}</p>}</div>}

    </>}
  </DialogContent>
}
function InterviewEditor({event,stages,statuses,displayTimezone,onSaved}:{displayTimezone?:string;event:InterviewEvent;stages:string[];statuses:string[];onSaved:()=>void}) {
  const client=useQueryClient(), toast=useToast()
  const initialZone=displayTimezone||(()=>{try{new Intl.DateTimeFormat(undefined,{timeZone:event.timezone||""});return event.timezone!}catch{return Intl.DateTimeFormat().resolvedOptions().timeZone}})()
  const [draft,setDraft]=useState<Record<string,string|boolean>>({company:event.company||"",role:event.role||"",stage:event.stage,status:event.status,start_at:localInput(event.start_at,initialZone),end_at:localInput(event.end_at,initialZone),timezone:initialZone,interviewers:(event.interviewers || []).join("\n"),meeting_url:event.meeting_url||"",location:event.location||"",notes:event.notes||"",needs_review:event.needs_review})
  const [dirty,setDirty]=useState<Set<string>>(new Set())
  const set=(name:string,value:string|boolean)=>{setDraft(d=>({...d,[name]:value}));setDirty(d=>new Set([...d,name]))}
  const save=useMutation({mutationFn:()=>{const fields=new Set(dirty);if(fields.has("start_at")||fields.has("end_at"))fields.add("timezone");if(dirty.has("timezone")){fields.add("start_at");if(draft.end_at)fields.add("end_at")}const changes=Object.fromEntries([...fields].map(k=>[k,k==="interviewers"?String(draft[k]).split("\n").map(value=>value.trim()).filter(Boolean):draft[k]===""?null:draft[k]]));return api.post(`/api/interviews/${event.id}`,changes)},onSuccess:async()=>{await client.invalidateQueries({queryKey:["interviews"]});toast("Interview corrections saved locally.","success");onSaved()},onError:e=>toast(e.message,"error")})
  return <form className="interview-editor" onSubmit={e=>{e.preventDefault();save.mutate()}}><p className="form-hint">Date and time fields use the timezone below. Use an IANA name, such as America/Chicago.</p><div className="interview-editor-grid">{[["company","Company"],["role","Role"],["start_at","Start date/time"],["end_at","End date/time"],["timezone","Timezone"],["meeting_url","Meeting URL"],["location","Location"]].map(([name,label])=><label key={name}>{label}<input type={name.endsWith("_at")?"datetime-local":name==="meeting_url"?"url":"text"} disabled={save.isPending} value={String(draft[name])} onChange={e=>set(name,e.target.value)} maxLength={1000}/></label>)}<label>Interview stage<select disabled={save.isPending} aria-label="Interview stage" value={String(draft.stage)} onChange={e=>set("stage",e.target.value)}>{stages.map(s=><option key={s}>{s}</option>)}</select></label><label>Status<select disabled={save.isPending} aria-label="Status" value={String(draft.status)} onChange={e=>set("status",e.target.value)}>{statuses.map(s=><option key={s}>{s}</option>)}</select></label></div><label>Interviewers (one per line)<textarea disabled={save.isPending} value={String(draft.interviewers)} onChange={e=>set("interviewers",e.target.value)} maxLength={20000}/></label><label>Notes<textarea disabled={save.isPending} value={String(draft.notes)} onChange={e=>set("notes",e.target.value)} maxLength={8000}/></label><label className="interview-review-checkbox"><input type="checkbox" disabled={save.isPending} checked={Boolean(draft.needs_review)} onChange={e=>set("needs_review",e.target.checked)}/>Needs review</label>{save.error && <p role="alert" className="inline-error">{save.error.message}</p>}<Button type="submit" disabled={save.isPending||!dirty.size}>{save.isPending?"Saving…":"Save corrections"}</Button></form>
}
