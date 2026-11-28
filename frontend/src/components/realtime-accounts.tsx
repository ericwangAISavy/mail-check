import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, request } from '@/lib/api'
import { Switch, useToast } from '@/components/common'

type Account = {id:number;label:string;enabled:boolean;provider:string}
type Status = {account_id:number;enabled:boolean;last_sync:number|null;last_error:string;subscription_status?:string;subscription_error?:string}
type Realtime = {configured:boolean;public_ready?:boolean;accounts:Status[]}

/** One shared status request for every account row (refreshed every 30 s). */
function useRealtimeStatus() {
  return useQuery({queryKey:['realtime-accounts'],queryFn:({signal})=>request<Realtime>('/api/realtime/accounts',{signal}),
    retry:false,refetchInterval:30_000})
}

/**
 * The account row's "Sync" switch: automatic collection of new mail.
 * Turning it on also includes a paused account in checks again, since the row
 * no longer has a separate "Include in checks" switch.
 */
export function AccountSync({account,onChanged,disabled=false}:{account:Account;onChanged:()=>void;disabled?:boolean}) {
  const client=useQueryClient()
  const toast=useToast()
  const query=useRealtimeStatus()
  const [busy,setBusy]=useState(false)
  const status=query.data?.accounts?.find(item=>item.account_id===account.id)
  const available=!!query.data?.configured
  const on=available&&account.enabled&&!!status?.enabled
  const change=async(enabled:boolean)=>{
    setBusy(true)
    try {
      if(enabled&&!account.enabled)await api.post(`/api/accounts/${encodeURIComponent(account.label)}/toggle?enabled=true`)
      await api.post(`/api/realtime/accounts/${account.id}`,{enabled})
      await client.invalidateQueries({queryKey:['realtime-accounts']})
      onChanged()
      toast(enabled?`Sync is on for ${account.label}.`:`Sync is off for ${account.label}.`,'success')
    } catch(reason) {toast(reason instanceof Error?reason.message:'Could not change sync.','error')}
    finally {setBusy(false)}
  }
  const title=query.isPending?'Loading sync status…':query.isError&&!query.data?'Sync status is temporarily unavailable.':!available?'Automatic sync is not available on this server.':on?'New mail is collected as it arrives.':'Turn on to collect new mail as it arrives.'
  return <span className="account-sync" title={title}>
    <span className="account-toggle-label">Sync</span>
    <Switch label={`Sync ${account.label}`} checked={on} disabled={!available||busy||disabled} onChange={enabled=>void change(enabled)} />
  </span>
}
