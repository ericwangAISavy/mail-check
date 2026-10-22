import {useCallback, useEffect, useRef, useState} from "react"
import {useQuery, useQueryClient} from "@tanstack/react-query"
import {Check, LoaderCircle, Reply, ReplyAll, Send, Trash2, X} from "lucide-react"
import {api, ApiError, request} from "@/lib/api"
import {operationId} from "@/lib/operation-id"
import {Button} from "@/components/ui/button"
import {useToast} from "@/components/common"
import OutgoingDialog from "./outgoing-dialog"
import OutlookDialog from "./outlook-dialog"
import type {SentReply} from "@/lib/types"
import "./reply-composer.css"

type Mode = "reply" | "reply_all"
type Context = {from:string;to:string[];cc:string[];subject:string}
type Draft = {body:string;mode:Mode;operation:string;markDone?:boolean;uncertain?:boolean}
function loadDraft(key:string):Draft {
  try {const value=JSON.parse(localStorage.getItem(key)||"null");if(typeof value?.body==="string" && typeof value?.operation==="string") return value} catch { /* Storage can be unavailable in private browsing. */ }
  return {body:"",mode:"reply",operation:operationId()}
}
export default function ReplyComposer({pk,accountLabel,messageId,provider="outlook",mode,onModeChange,replies}:{pk:number;accountLabel:string;messageId?:string;provider?:string;mode:Mode|null;onModeChange:(mode:Mode|null)=>void;replies:SentReply[]}) {
  const key=`mailcheck:reply:${encodeURIComponent(accountLabel)}:${encodeURIComponent(messageId || String(pk))}`
  const [draft,setDraft]=useState(()=>loadDraft(key))
  const [draftSaved,setDraftSaved]=useState(false)
  const [sending,setSending]=useState(false)
  const [error,setError]=useState("")
  const [uncertain,setUncertain]=useState(false)
  const [checking,setChecking]=useState(false)
  const [reconnect,setReconnect]=useState(false)
  const [discard,setDiscard]=useState(false)
  const deliveryUncertain=uncertain || draft.uncertain || replies.some(r=>r.operation===draft.operation && ["preparing","sending","unknown"].includes(r.status))
  const lock=useRef(false)
  const area=useRef<HTMLTextAreaElement>(null)
  const client=useQueryClient()
  const toast=useToast()
  const open=mode!==null
  const context=useQuery({queryKey:["reply-context",pk,mode],queryFn:()=>request<Context>(`/api/messages/${pk}/reply?mode=${mode}`),enabled:open,retry:false,staleTime:60_000})
  const refresh=useCallback(()=>{void client.invalidateQueries({queryKey:["reply-context",pk]})},[client,pk])
  useEffect(()=>{if(open){area.current?.focus();area.current?.scrollIntoView?.({block:"nearest",behavior:"smooth"})}},[open,context.data])
  useEffect(()=>{try {if(draft.body){localStorage.setItem(key,JSON.stringify(draft));setDraftSaved(true)}else{localStorage.removeItem(key);setDraftSaved(false)}} catch {setDraftSaved(false)}},[draft,key])
  useEffect(()=>{if(!draft.body)return;const warn=(e:BeforeUnloadEvent)=>{e.preventDefault();e.returnValue=""};window.addEventListener("beforeunload",warn);return()=>window.removeEventListener("beforeunload",warn)},[draft.body])
  const send=async(markDone:boolean,retry=false)=>{
    if(lock.current || !draft.body.trim() || !context.data || !mode || (deliveryUncertain&&!retry))return
    const sendMode=retry?draft.mode:mode
    if(retry)markDone=draft.markDone??false
    lock.current=true;setSending(true);setError("")
    const operation = !retry && draft.markDone !== undefined && draft.markDone !== markDone ? operationId() : draft.operation
    setDraft(d=>({...d,operation,markDone,mode:sendMode}))
    try {
      const result=await api.post<{warning?:string;done?:boolean}>(`/api/messages/${pk}/reply`,{operation,body:draft.body,mode:sendMode,mark_done:markDone})
      setUncertain(false);setDraft({body:"",mode,operation:operationId()});try{localStorage.removeItem(key)}catch{/* optional browser storage */}
      toast(result.warning || (result.done?"Reply sent. Message marked done.":"Reply sent."),result.warning?"error":"success")
      await Promise.all([client.invalidateQueries({queryKey:["reader",pk]}),client.invalidateQueries({queryKey:["triage"]}),client.invalidateQueries({queryKey:["bootstrap"]})])
      onModeChange(null)
    }catch(caught){const text=caught instanceof Error?caught.message:"Could not send your reply.";setError(text);if(!(caught instanceof ApiError)||caught.status>=500||text.includes("not confirmed")){setUncertain(true);setDraft(d=>({...d,uncertain:true}))}}
    finally{lock.current=false;setSending(false)}
  }
  const checkDelivery=async()=>{
    setChecking(true)
    try {
      const reader=await api.reader(pk)
      client.setQueryData(["reader",pk],reader)
      const record=reader.replies?.find(r=>r.operation===draft.operation)
      if(record?.status==="sent"){
        setDraft({body:"",mode:draft.mode,operation:operationId()});setUncertain(false);setError("")
        toast("Reply sent. Delivery record confirmed.","success");onModeChange(null)
        await client.invalidateQueries({queryKey:["triage"]})
      }else if(record?.status==="failed"){
        setUncertain(false);setDraft(d=>({...d,uncertain:false}));setError(record.error||"The reply was not sent. You can try again.")
      }else{setError(record?"Delivery is still not confirmed. Do not start another reply for this send.":"No delivery record was found yet. Retry the original send to safely reuse its request ID.")}
    }catch(caught){setError(caught instanceof Error?caught.message:"Could not check delivery status.")}
    finally{setChecking(false)}
  }
  const choose=(next:Mode)=>{setError("");setDiscard(false);setDraft(d=>({...d,mode:next,operation:d.mode===next?d.operation:operationId(),markDone:d.mode===next?d.markDone:undefined}));onModeChange(next)}
  const clear=()=>{setDraft({body:"",mode:"reply",operation:operationId()});setError("");setUncertain(false);setDiscard(false);onModeChange(null)}
  return <section className="mail-reply" aria-label="Message replies">
    {replies.length>0 && <div className="reply-history">{replies.map(reply=><article className={`reply-record reply-${reply.status}`} key={reply.operation}><div><strong><Check size={14}/>{reply.status==="sent"?"Your reply · sent":reply.status==="unknown"||reply.status==="sending"||reply.status==="preparing"?"Reply · delivery not confirmed":"Reply · not sent"}</strong><time>{new Date(reply.sent_at||reply.created_at).toLocaleString("en-US",{timeZone:"America/Chicago",timeZoneName:"short"})}</time></div><p>{reply.body}</p>{reply.error && <small>{reply.error}</small>}</article>)}</div>}
    {!open ? <div className="reply-open-actions"><Button variant="outline" size="sm" onClick={()=>choose(draft.body?draft.mode:"reply")}><Reply size={15}/>{draft.body?"Continue draft":"Reply"}</Button><Button variant="ghost" size="sm" disabled={Boolean(deliveryUncertain)} onClick={()=>choose("reply_all")}><ReplyAll size={15}/>Reply all</Button>{draft.body&&<small>{draftSaved?"Draft saved on this browser":"Draft kept in this view"}</small>}</div> : <div className="reply-editor">
      <header><h3>{mode==="reply_all"?<ReplyAll size={17}/>:<Reply size={17}/>} {mode==="reply_all"?"Reply all":"Reply"}</h3><div role="group" aria-label="Reply recipients"><Button type="button" size="sm" variant={mode==="reply"?"secondary":"ghost"} disabled={Boolean(sending||deliveryUncertain)} aria-pressed={mode==="reply"} onClick={()=>choose("reply")}>Reply</Button><Button type="button" size="sm" variant={mode==="reply_all"?"secondary":"ghost"} disabled={Boolean(sending||deliveryUncertain)} aria-pressed={mode==="reply_all"} onClick={()=>choose("reply_all")}>Reply all</Button><Button type="button" variant="ghost" size="icon" aria-label="Close reply composer and keep draft" disabled={sending} onClick={()=>onModeChange(null)}><X size={15}/></Button></div></header>
      {context.isPending?<p role="status" className="reply-loading"><LoaderCircle size={15} className="spin"/>Loading reply details…</p>:context.error?<div className="reply-error" role="alert"><p>{context.error.message}</p><Button variant="outline" size="sm" onClick={()=>void context.refetch()}>Try again</Button><Button variant="outline" size="sm" onClick={()=>setReconnect(true)}>{provider==="outlook"?"Reconnect Outlook":"Configure outgoing mail"}</Button></div>:context.data&&<>
        <div className="reply-envelope"><label>From<input readOnly value={context.data.from} /></label><label>To<input readOnly value={context.data.to.join("; ")} /></label>{context.data.cc.length>0&&<label>Cc<input readOnly value={context.data.cc.join("; ")} /></label>}<label>Subject<input readOnly value={context.data.subject}/></label></div>
        <textarea ref={area} aria-label="Your reply" placeholder="Write your reply…" maxLength={30000} disabled={Boolean(sending||deliveryUncertain)} value={draft.body} onChange={e=>setDraft(d=>({...d,body:e.target.value,operation:operationId()}))}/>
        {error&&<p role="alert" className="reply-error">{error}</p>}{deliveryUncertain&&<div className="reply-delivery-check"><p>Delivery is not confirmed. Keep this draft unchanged until its status is known.</p><Button variant="outline" size="sm" disabled={sending||checking} onClick={()=>void checkDelivery()}>Check send status</Button><Button variant="outline" size="sm" disabled={sending||checking} onClick={()=>void send(draft.markDone??false,true)}>Retry original send safely</Button></div>}
        <footer><div><Button disabled={Boolean(sending||deliveryUncertain||!draft.body.trim()||!context.data.to.length)} onClick={()=>void send(false)}>{sending?<LoaderCircle className="spin" size={15}/>:<Send size={15}/>}Send</Button><Button variant="outline" disabled={Boolean(sending||deliveryUncertain||!draft.body.trim()||!context.data.to.length)} onClick={()=>void send(true)}>Send &amp; Done</Button></div><span>{sending?"Sending…":draft.body?(draftSaved?"Draft saved on this browser":"Draft kept in this view"):""}</span><Button variant="ghost" size="sm" disabled={sending} aria-label="Discard reply draft" onClick={()=>draft.body?setDiscard(true):clear()}><Trash2 size={16}/></Button></footer>
      </>}
      {discard&&<div className="reply-discard" role="alert"><span>Discard this draft?</span><Button size="sm" variant="outline" onClick={()=>setDiscard(false)}>Keep writing</Button><Button size="sm" onClick={clear}>Discard draft</Button></div>}
    </div>}
    {provider==="outlook"?<OutlookDialog open={reconnect} onOpenChange={setReconnect} accountLabel={accountLabel} refresh={refresh}/>:<OutgoingDialog open={reconnect} onOpenChange={setReconnect} label={accountLabel} onSaved={refresh}/>}
  </section>
}
