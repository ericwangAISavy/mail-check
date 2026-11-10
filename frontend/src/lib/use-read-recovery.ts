import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export function isTransientReadError(error: unknown) {
  return error instanceof ApiError && [0,502,503,504,520,521,522,523,524,530].includes(error.status)
}

/** A small recovery budget for a mounted read query; never replays mutations. */
export function useReadRecovery({scope,error,errorUpdatedAt,isFetching,isSuccess,retry,enabled=true}: {
  scope:string;error:unknown;errorUpdatedAt:number;isFetching:boolean;isSuccess:boolean;retry:()=>Promise<unknown>;enabled?:boolean
}) {
  const budget=useRef({scope,attempts:0})
  const pending=useRef<number|undefined>(undefined)
  const [scheduled,setScheduled]=useState(false)
  useEffect(()=>{
    if(budget.current.scope!==scope)budget.current={scope,attempts:0}
    setScheduled(false)
    if(isSuccess){budget.current.attempts=0;return}
    if(!enabled||isFetching||!isTransientReadError(error)||budget.current.attempts>=3)return
    const delay=[5000,15000,30000][budget.current.attempts]
    setScheduled(true)
    const timer=window.setTimeout(()=>{
      pending.current=undefined
      budget.current.attempts++
      setScheduled(false)
      void retry()
    },delay)
    pending.current=timer
    return ()=>{window.clearTimeout(timer);if(pending.current===timer)pending.current=undefined}
  },[scope,error,errorUpdatedAt,isFetching,isSuccess,retry,enabled])
  const retryNow=useCallback(()=>{
    window.clearTimeout(pending.current);pending.current=undefined
    budget.current={scope,attempts:0}
    setScheduled(false)
    return retry()
  },[scope,retry])
  return {scheduled,retryNow}
}
