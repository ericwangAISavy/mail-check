import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { api, request } from '@/lib/api'
import { Switch } from '@/components/common'
import { Card } from '@/components/ui/card'

type Account = {id:number;label:string;enabled:boolean;provider:string}
type Status = {account_id:number;enabled:boolean;last_sync:number|null;last_error:string;subscription_status?:string;subscription_error?:string}

export default function RealtimeAccounts({accounts}:{accounts:Account[]}) {
  const client=useQueryClient()
  const [busy,setBusy]=useState<number|null>(null),[error,setError]=useState('')
  const query=useQuery({queryKey:['realtime-accounts'],queryFn:({signal})=>request<{
    configured:boolean;public_ready?:boolean;accounts:Status[]}>('/api/realtime/accounts',{signal}),
    retry:false,refetchInterval:30_000})
  const change=async(id:number,enabled:boolean)=>{
    setBusy(id);setError('')
    try {
      await api.post(`/api/realtime/accounts/${id}`,{enabled})
      await client.invalidateQueries({queryKey:['realtime-accounts']})
    } catch(reason) {setError(reason instanceof Error?reason.message:'Could not update automatic collection.')}
    finally {setBusy(null)}
  }
  return <section aria-label="Automatic updates"><h2>Automatic updates</h2>
    <p>Collect new email automatically and update open pages. Microsoft accounts also track calendar changes.</p>
    {query.isPending?<p>Loading automatic update settings…</p>:query.isError?<p role="status">Automatic update status is temporarily unavailable. Manual checks remain available.</p>:!query.data?.configured?
      <p>Automatic updates are not configured. Ask the owner to enable the background service.</p>:
      <Card>{accounts.map(account=>{
        const status=query.data.accounts?.find(item=>item.account_id===account.id)
        return <div className="account-row" key={account.id}><div className="account-info"><strong>{account.label}</strong>
          <p>{account.provider==='outlook'&&query.data.public_ready?'Email and calendar notifications with recovery checks':account.provider==='outlook'?'Email and calendar recovery checks; notifications need a public connection':'Email polling every 30 seconds'}</p>
          <p>{status?.last_sync?`Last synced ${new Date(status.last_sync*1000).toLocaleString()}`:'Not synced automatically yet'}</p>
          {status?.enabled&&<p>{status.subscription_status==='subscribed'?'Notifications connected':status.subscription_status==='pending'?'Connecting notifications; recovery checks are active':'Recovery checks are active'}</p>}
          {status?.last_error&&<p role="status">{status.last_error}</p>}</div>
          <Switch label={`Automatic updates for ${account.label}`} checked={!!status?.enabled} disabled={!account.enabled||busy!==null}
            onChange={enabled=>void change(account.id,enabled)} /></div>
      })}</Card>}
    {error&&<p role="alert">{error}</p>}
  </section>
}
