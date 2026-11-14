import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '@/components/auth'
import { getWorkspaceIdentity, getWorkspaceIdentityRevision, request, subscribeWorkspaceIdentity } from './api'

/** SSE is only an invalidation hint; normal authenticated reads remain authoritative. */
export function connectRealtime(workspace: string, changed: ()=>void, sessionEnded: ()=>void) {
  if (typeof EventSource === 'undefined') return ()=>{}
  const revision = getWorkspaceIdentityRevision()
  const controller = new AbortController()
  let stream: EventSource | undefined
  let stopped = false, retry = 0, refresh = 0, attempts = 0, cursor = ''
  const current = () => !stopped && getWorkspaceIdentity() === workspace && getWorkspaceIdentityRevision() === revision
  const scheduleRefresh = () => {
    if (!current() || refresh) return
    refresh = window.setTimeout(()=>{refresh=0;if(current())changed()},200)
  }
  const stop = () => {
    stopped=true;controller.abort();stream?.close()
    window.clearTimeout(retry);window.clearTimeout(refresh)
  }
  const unsubscribe = subscribeWorkspaceIdentity(stop)
  const reconnect = () => {
    stream?.close()
    if (!current()) return
    window.clearTimeout(retry)
    retry=window.setTimeout(()=>void open(),Math.min(30_000,1000*2**Math.min(attempts++,5)))
  }
  const open = async () => {
    try {
      const capabilities=await request<{configured:boolean}>('/api/realtime/capabilities',{signal:controller.signal})
      if(!current() || !capabilities.configured)return
      const params=new URLSearchParams({workspace,...(cursor?{cursor}:{})})
      stream=new EventSource(`/api/realtime/events?${params}`)
      const update=(event:Event)=>{
        if(!current())return
        const id=(event as MessageEvent).lastEventId
        if(id && /^\d+-\d+$/.test(id))cursor=id
        attempts=0;scheduleRefresh()
      }
      stream.addEventListener('resync',update)
      stream.addEventListener('changed',update)
      stream.addEventListener('degraded',reconnect)
      stream.addEventListener('session-ended',()=>{if(current()){stop();sessionEnded()}})
      stream.onerror=reconnect
    } catch {
      if(current())reconnect()
    }
  }
  void open()
  return ()=>{unsubscribe();stop()}
}

export function useRealtimeUpdates() {
  const {session}=useAuth()
  const client=useQueryClient()
  useEffect(()=>{
    if(!session?.workspace_id || session.must_change_password)return
    const keys=new Set(['bootstrap','accounts','triage','reader','dashboard','payments','interviews',
      'pipeline','interview-processes','sourcing','sourcing-index','sourcing-search','sourcing-viewer','dashboard-accounts',
      'sourcing-filters','sourcing-role-filters','sourcing-delete-preview','bidder-management','bidder-access','bidder-visibility','followups','reply-context',
      'interview-job','status','applications-today','realtime-accounts'])
    return connectRealtime(session.workspace_id,
      ()=>{void client.invalidateQueries({predicate:query=>keys.has(String(query.queryKey[0]))})},
      ()=>{void client.invalidateQueries({queryKey:['auth']})})
  },[client,session?.workspace_id,session?.user_id,session?.bidder_id,session?.role,session?.must_change_password])
}
