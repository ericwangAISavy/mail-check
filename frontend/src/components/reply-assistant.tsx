import {useEffect, useRef, useState} from "react"
import {useQuery, useQueryClient} from "@tanstack/react-query"
import {api, request} from "@/lib/api"
import {Button} from "@/components/ui/button"
import "./reply-assistant.css"

type Preferences = {sender_name:string;signature:string;tone:"professional"|"warm"|"concise";duration_minutes:number;calendar_account_ids:number[]}
type Context = {saved_draft?:Preview|null;account:{id:number;label:string};preferences:Preferences;cases:{id:string;label:string}[];calendars:{id:number;label:string;email:string}[];model_ready:boolean}
type Preview = {body:string;case:string;model:string;warnings:string[];context_summary:string;availability:null|{ranges:{date:string;start:string;end:string;label:string}[];timezone:string;checked_at:string;calendar_labels:string[]}}
const cases=[{id:"availability",label:"Availability"},{id:"follow_up",label:"Follow up"},{id:"thank_you",label:"Thank you"},{id:"reschedule",label:"Reschedule"},{id:"confirm",label:"Confirm"},{id:"question",label:"Question"},{id:"decline",label:"Decline"},{id:"custom",label:"Custom"}]
export default function ReplyAssistant({pk,body,disabled,onInsert}:{pk:number;body:string;disabled:boolean;onInsert:(body:string)=>void}) {
 const client=useQueryClient()
 const context=useQuery({queryKey:["assistant-context",pk],queryFn:()=>request<Context>(`/api/agent/messages/${pk}`),retry:false,staleTime:60_000})
 const [preferences,setPreferences]=useState<Preferences|null>(null)
 const [duration,setDuration]=useState("30"),[custom,setCustom]=useState(30),[instructions,setInstructions]=useState("")
 const [preview,setPreview]=useState<Preview|null>(null),[busy,setBusy]=useState(false),[saving,setSaving]=useState(false),[error,setError]=useState("")
 const [insertion,setInsertion]=useState<{before:string;after:string}|null>(null)
 const latest=useRef({pk,body,disabled});latest.current={pk,body,disabled}
 const sequence=useRef(0)
 useEffect(()=>()=>{sequence.current++},[])
 useEffect(()=>{setPreview(null);setInsertion(null);setError("");setBusy(false);sequence.current++},[pk])
 useEffect(()=>{if(context.data?.preferences){setPreferences(context.data.preferences);const n=context.data.preferences.duration_minutes;setDuration([30,45,60].includes(n)?String(n):"custom");setCustom(n)}},[context.data])
 const generate=async(caseId:string,refinement="original")=>{
  if(disabled||busy)return
  const stamp=++sequence.current,original=body,target=pk
  setBusy(true);setError("")
  try{const result=await api.post<Preview>(`/api/agent/messages/${pk}/generate`,{case:caseId,instructions,duration_minutes:duration==="custom"?custom:Number(duration),tone:preferences?.tone,refinement,current_draft:refinement==="original"?body:preview?.body||body})
   if(stamp!==sequence.current||latest.current.pk!==target)return
   if(latest.current.body!==original||latest.current.disabled){setError("Your reply changed while generating. Generate again to use the latest text.");return}
   setPreview(result)
  }catch(e){if(stamp===sequence.current)setError(e instanceof Error?e.message:"Could not generate draft.")}
  finally{if(stamp===sequence.current)setBusy(false)}
 }
 const save=async()=>{if(!preferences||!context.data)return;setSaving(true);setError("");try{await api.post(`/api/agent/preferences/${context.data.account.id}`,{...preferences,duration_minutes:duration==="custom"?custom:Number(duration)});await client.invalidateQueries({queryKey:["assistant-context",pk]})}catch(e){setError(e instanceof Error?e.message:"Could not save preferences.")}finally{setSaving(false)}}
 return <section className="reply-assistant" aria-label="Reply assistant">
  <div className="assistant-heading"><strong>Draft with assistant</strong><small>Review before using. Send is always your choice.</small></div>
  {context.isPending?<p role="status">Loading assistant…</p>:context.error?<div role="alert">Assistant unavailable: {context.error.message} <Button size="sm" variant="outline" onClick={()=>void context.refetch()}>Retry assistant</Button></div>:<>
  {context.data?.saved_draft&&<Button size="sm" variant="outline" disabled={disabled||busy} onClick={()=>setPreview(context.data!.saved_draft!)}>Review saved draft</Button>}
  <div className="assistant-cases" role="group" aria-label="Draft type">{(context.data?.cases?.length?context.data.cases:cases).map(c=><Button key={c.id} size="sm" variant="outline" disabled={disabled||busy||!context.data?.model_ready} onClick={()=>void generate(c.id)}>{c.label}</Button>)}</div>
  {context.data&&!context.data.model_ready&&<p>Configure your model in Settings to generate drafts.</p>}
  <div className="assistant-options"><label>Meeting duration<select aria-label="Meeting duration" disabled={disabled||busy} value={duration} onChange={e=>setDuration(e.target.value)}>{[30,45,60].map(n=><option key={n} value={n}>{n} minutes</option>)}<option value="custom">Custom</option></select></label>{duration==="custom"&&<label>Minutes<input aria-label="Custom duration in minutes" type="number" min="1" max="480" value={custom} disabled={disabled||busy} onChange={e=>setCustom(Number(e.target.value))}/></label>}<label className="assistant-instructions">Wording instructions<input value={instructions} disabled={disabled||busy} onChange={e=>setInstructions(e.target.value)} placeholder="Tone or details to include; availability uses saved defaults"/></label></div>
  <details><summary>Assistant preferences</summary>{preferences&&<fieldset disabled={disabled||saving||busy}><label>Sender name<input value={preferences.sender_name} onChange={e=>setPreferences({...preferences,sender_name:e.target.value})}/></label><label>Signature<textarea aria-label="Signature" value={preferences.signature} onChange={e=>setPreferences({...preferences,signature:e.target.value})}/></label><label>Tone<select value={preferences.tone} onChange={e=>setPreferences({...preferences,tone:e.target.value as Preferences["tone"]})}>{["professional","warm","concise"].map(t=><option key={t}>{t}</option>)}</select></label><p>Availability combines calendars and saved events from all accounts automatically.</p><Button size="sm" variant="outline" onClick={()=>void save()}>{saving?"Saving…":"Save preferences"}</Button></fieldset>}</details>
  </>}
  {busy&&<p role="status">Generating a preview… You can keep writing.</p>}
  {error&&<p role="alert">{error}</p>}
  {preview&&<div className="assistant-preview"><strong>Draft preview</strong><pre>{preview.body}</pre>{preview.warnings?.map((w,i)=><p role="note" key={i}>{w}</p>)}{preview.availability&&<details open><summary>Verified calendar availability · {preview.availability.timezone}</summary><small>{preview.availability.calendar_labels.join(", ")} · Checked {new Date(preview.availability.checked_at).toLocaleString()}</small><ul>{preview.availability.ranges.map((r,i)=><li key={i}>{r.label||`${r.date}: ${r.start} – ${r.end}`}</li>)}</ul></details>}<div className="assistant-cases"><Button size="sm" disabled={disabled||busy} onClick={()=>{setInsertion({before:body,after:preview.body});onInsert(preview.body)}}>Use draft</Button>{[["Regenerate","original"],["Shorter","shorter"],["More formal","formal"]].map(([label,r])=><Button key={r} variant="outline" size="sm" disabled={disabled||busy} onClick={()=>void generate(preview.case,r)}>{label}</Button>)}</div><small>Generated by {preview.model}</small></div>}
  {insertion&&<Button size="sm" variant="outline" disabled={disabled||body!==insertion.after} onClick={()=>{onInsert(insertion.before);setInsertion(null)}}>Undo insertion</Button>}
 </section>
}
