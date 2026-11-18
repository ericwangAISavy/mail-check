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
    <p>Collect new mail as it arrives.</p>
    {query.isPending?<p>Loading automatic update settings…</p>:query.isError?<p role="status">Automatic update status is temporarily unavailable.</p>:!query.data?.configured?
      <p>Automatic updates are not available.</p>:
      <Card>{accounts.map(account=>{
        const status=query.data.accounts?.find(item=>item.account_id===account.id)
        return <div className="account-row" key={account.id}><div className="account-info"><strong>{account.label}</strong>
          {status?.last_error&&<p role="status">{status.last_error}</p>}</div>
          <Switch label={`Automatic updates for ${account.label}`} checked={!!status?.enabled} disabled={!account.enabled||busy!==null}
            onChange={enabled=>void change(account.id,enabled)} /></div>
      })}</Card>}
    {error&&<p role="alert">{error}</p>}
  </section>
}
