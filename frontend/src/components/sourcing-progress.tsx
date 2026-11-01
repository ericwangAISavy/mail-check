import { useCallback, useEffect, useRef, useState } from "react"
import { api, request } from "@/lib/api"
import type { Snapshot } from "@/lib/sourcing"
import "./sourcing-progress.css"

type ServerProgress = {stage:string;processed:number;total:number|null}
export type JobProgress = ServerProgress & {revision?:string;filtered?:Snapshot["filtered"]}
export type RunJobOperation = (url:string,payload:Record<string,unknown>&{operation:string})=>Promise<Snapshot>

export function useSourcingProgress(tabId:number,revision?:string) {
  const [progress,setProgress]=useState<JobProgress|null>(null)
  const alive=useRef(true),cancel=useRef<(()=>void)|null>(null)
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;cancel.current?.()}},[])
  useEffect(()=>{
    if(progress?.stage==='rendering' && progress.revision===revision)
      setProgress(current=>current?{...current,stage:'complete'}:current)
    else if(progress?.stage==='complete' && progress.revision!==revision)
      setProgress(null)
  },[revision,progress?.revision,progress?.stage])
  const run:RunJobOperation=useCallback(async(url,payload)=>{
    cancel.current?.()
    let active=true,timer=0
    const controller=new AbortController()
    const stop=()=>{active=false;window.clearTimeout(timer);controller.abort()}
    cancel.current=stop
    setProgress({stage:'preparing',processed:0,total:null})
    const poll=async()=>{
      try {
        const next=await request<ServerProgress>(`/api/sourcing/tabs/${tabId}/progress/${payload.operation}`,{signal:controller.signal})
        if(active&&alive.current)setProgress({...next,stage:next.stage==='complete'?'saving':next.stage})
      } catch { /* The write response remains authoritative if progress polling fails. */ }
      if(active)timer=window.setTimeout(()=>void poll(),500)
    }
    void poll()
    try {
      const result=await api.post<Snapshot>(url,payload)
      if(alive.current)setProgress({stage:'rendering',processed:0,total:null,revision:result.revision,filtered:result.filtered})
      return result
    } catch(error) {
      if(alive.current)setProgress(current=>current?{...current,stage:'error'}:current)
      throw error
    } finally {stop();if(cancel.current===stop)cancel.current=null}
  },[tabId])
  return {progress,run}
}

export default function SourcingProgress({progress}:{progress:JobProgress|null}) {
  if(!progress)return null
  const complete=progress.stage==='complete'
  const percent=complete?100:progress.total!=null&&progress.total>0?Math.min(99,Math.floor(progress.processed/progress.total*100)):undefined
  const label=complete?'Sheet ready':progress.stage==='error'?'Could not finish — your changes have not been confirmed':progress.stage==='rendering'||progress.stage==='saving'||percent===99?'Saving and preparing your sheet':progress.stage==='filtering'?'Checking duplicate links and blocked companies':'Preparing new jobs'
  return <div className="sourcing-progress" aria-live="polite">
    <div className="sourcing-progress-label"><span>{label}</span><span>{percent==null?'Working…':`${percent}%`}</span></div>
    <div className={`sourcing-progress-track ${percent==null&&progress.stage!=='error'?'is-indeterminate':''}`} role="progressbar" aria-label="Job filtering progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-valuetext={label}><span style={{width:percent==null?'30%':`${percent}%`}}/></div>
    {progress.total!=null&&!complete&&<small>{progress.processed} of {progress.total} rows checked</small>}
    {complete&&progress.filtered&&<small>{progress.filtered.duplicates} duplicate links and {progress.filtered.blocked_companies} blocked companies removed.</small>}
  </div>
}
