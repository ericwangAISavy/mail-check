import { useState } from "react"
import { Link } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ExternalLink } from "lucide-react"
import { api, request } from "@/lib/api"
import type { InterviewEvent, InterviewSource } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Loading, useToast } from "@/components/common"
import "@/pages/interviews.css"

const stateClass = (event: InterviewEvent) => event.display_status.toLowerCase().replaceAll(" ","-")
const dateTime = (value: string | null) => value ? new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"short"}).format(new Date(value)) : "Unknown"

function localInput(value: string | null, zone: string) {
  if (!value) return ""
  try {
    const parts = new Intl.DateTimeFormat("en-CA",{timeZone:zone,year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).formatToParts(new Date(value))
    const p = Object.fromEntries(parts.map(x=>[x.type,x.value]))
    return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`
  } catch { return "" }
}
export function InterviewDetails({id,stages,statuses,onCloseAutoFocus,onRemoved}:{id:number;stages?:string[];statuses?:string[];onCloseAutoFocus?:(event:Event)=>void;onRemoved?:()=>void}) {
  const query = useQuery({queryKey:["interviews","detail",id],queryFn:()=>request<{event:InterviewEvent;sources:InterviewSource[];stages:string[];statuses:string[]}>(`/api/interviews/${id}`)})
  const client = useQueryClient()
  const [removed, setRemoved] = useState(false)
  const remove = useMutation({
    mutationFn: () => api.post(`/api/interviews/${id}/remove`),
    onSuccess: async () => { setRemoved(true); onRemoved?.(); await client.invalidateQueries({queryKey:["interviews"]}) },
  })
  const [editing,setEditing] = useState(false)
  const event = query.data?.event
  const applicationLookup = new URLSearchParams({q:[event?.company,event?.role].filter(Boolean).join(" ")})
  const profileIds = [...new Set(query.data?.sources.filter(s=>s.account_enabled!==false).map(s=>s.account_id).filter((id):id is number=>typeof id==="number")||[])]
  if(profileIds.length===1)applicationLookup.set("account",String(profileIds[0]))
  return <DialogContent className="interview-dialog" onCloseAutoFocus={onCloseAutoFocus}><DialogHeader><DialogTitle>{event?.company || "Meeting details"}</DialogTitle><DialogDescription>Calendar event details and local corrections.</DialogDescription></DialogHeader>
    {removed ? <p role="status">Event removed from calendar.</p> : query.isPending ? <Loading/> : query.error ? <p role="alert" className="inline-error">{query.error.message}</p> : event && <>
    <div className="interview-detail-status"><span className={`interview-status ${stateClass(event)}`}>{event.display_status}</span><Button variant="outline" onClick={()=>setEditing(!editing)}>{editing?"Cancel editing":"Edit details"}</Button></div>
    {editing ? <InterviewEditor event={event} stages={stages || query.data?.stages || []} statuses={statuses || query.data?.statuses || []} onSaved={()=>setEditing(false)}/> : <>
      {event.needs_review && <p className="review-note">Needs review: {event.review_reason || "Verify the event details in your calendar."}</p>}
      <Link className="interview-meeting-link" to={`/sourcing?${applicationLookup}`}>Find application <ExternalLink size={14}/></Link>
      <dl className="interview-details">{[["Company",event.company],["Role",event.role],["Interview stage",event.stage],["Start",dateTime(event.start_at)],["End",dateTime(event.end_at)],["Original timezone",event.timezone],["Display timezone",Intl.DateTimeFormat().resolvedOptions().timeZone],["Meeting platform",event.meeting_platform],["Location",event.location],["Organizer",[event.organizer_name,event.organizer_email].filter(Boolean).join(" · ")],["Participants",event.participants.join(", ")],["Detected status",event.status],["Last updated",dateTime(event.updated_at)],["Notes",event.notes]].map(([name,value])=><div key={name}><dt>{name}</dt><dd>{value||"Unknown"}</dd></div>)}</dl>
      {event.meeting_url && <a className="interview-meeting-link" href={event.meeting_url} target="_blank" rel="noopener noreferrer">Open {event.meeting_platform || "meeting"} link <ExternalLink size={14}/></a>}
      {!!event.manual_fields.length && <p className="form-hint">Manually corrected fields are protected from later automated updates.</p>}
    </>}
    <Button variant="destructive" disabled={remove.isPending} onClick={()=>remove.mutate()}>{remove.isPending ? "Removing…" : "Remove from calendar"}</Button>
    <p className="form-hint">Removes this event from this app. Your connected calendar is unchanged.</p>
    {remove.error && <p role="alert" className="inline-error">{remove.error.message}</p>}
    <div className="interview-sources"><h2>Connected calendar accounts</h2>{query.data?.sources.map(s=><article key={s.id}><strong>{s.account_label}</strong><p>{s.account_email}</p></article>)}</div>
    </>}
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
