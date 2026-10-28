import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { RefreshCw } from "lucide-react"
import { api, request } from "@/lib/api"
import type { Bootstrap, InterviewData } from "@/lib/types"
import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Dialog } from "@/components/ui/dialog"
import { Loading, useToast } from "@/components/common"
import { InterviewDetails } from "@/components/interview-details"
import InterviewCalendar from "@/components/interview-calendar"
import "./interviews.css"

export default function InterviewsPage({ bootstrap }: {bootstrap: Bootstrap}) {
  const toast = useToast(), client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [selected, setSelected] = useState<number | null>(() => Number(params.get("event")) || null)
  const account = params.get("account") || "", status = params.get("status") || "", company = params.get("company") || ""
  const queryParams = new URLSearchParams()
  if (account) queryParams.set("account",account)
  if (status) queryParams.set("status",status)
  if (company) queryParams.set("company",company)
  const query = useQuery({queryKey:["interviews", "list", queryParams.toString()],queryFn:()=>request<InterviewData>(`/api/interviews?${queryParams}`),placeholderData:previous=>previous})
  const seenJob = useRef<number | null>(null)
  const job = useQuery({queryKey:["interview-job"],queryFn:api.status,refetchInterval:2000})
  useEffect(() => {
    if (job.data && seenJob.current !== job.data.completion_id) {
      if (seenJob.current !== null) void client.invalidateQueries({queryKey:["interviews"]})
      seenJob.current = job.data.completion_id
    }
  }, [job.data?.completion_id,client])
  useEffect(() => { setSelected(Number(params.get("event")) || null) },[params])
  const setFilter = (name: string,value: string) => { const next = new URLSearchParams(params); value ? next.set(name,value) : next.delete(name); setParams(next) }
  const select = (id: number | null) => { setSelected(id); const next = new URLSearchParams(params); id ? next.set("event",String(id)) : next.delete("event"); setParams(next,{replace:true}) }
  const events = (query.data?.events || []).filter(event=>event.start_at)
  const refresh = async () => { try { await client.invalidateQueries({queryKey:["interviews"],refetchType:"all"},{throwOnError:true}); toast("Calendar and interview processes refreshed.","success") } catch (error) { toast(error instanceof Error ? error.message : "Could not refresh interviews.","error") } }
  const check = useMutation({mutationFn:()=>api.post("/api/interviews/sync"),onSuccess:()=>{toast("Calendar collection started.","info");window.dispatchEvent(new Event("mailcheck:check-started"));void job.refetch()},onError:e=>toast(e.message,"error")})
  const filterControls = <Card className="interview-filters"><label>Account<select aria-label="Account" value={account} onChange={e=>setFilter("account",e.target.value)}><option value="">All accounts</option>{query.data?.accounts.map(a=><option key={a.id} value={a.label}>{a.label}</option>)}</select></label><label>Status<select aria-label="Status" value={status} onChange={e=>setFilter("status",e.target.value)}><option value="">All statuses</option>{query.data?.statuses.map(s=><option key={s}>{s}</option>)}</select></label><label>Company<select aria-label="Company" value={company} onChange={e=>setFilter("company",e.target.value)}><option value="">All companies</option>{query.data?.companies.map(c=><option key={c}>{c}</option>)}</select></label></Card>
  const actions = <div className="interview-actions"><Button variant="outline" size="sm" onClick={()=>void refresh()} disabled={query.isFetching}><RefreshCw size={16}/>Refresh</Button><Button size="sm" onClick={()=>check.mutate()} disabled={check.isPending || job.isPending || job.isError || job.data?.running || !bootstrap.readiness.accounts}>Check now</Button></div>
  return <div className="page-wrap interviews-page">


    {query.isPending ? <Loading/> : query.error ? <div role="alert" className="inline-error">{query.error.message}<Button variant="outline" onClick={()=>void refresh()}>Try again</Button></div> : <>
    <InterviewCalendar actions={actions} events={events} accounts={query.data?.accounts||[]} account={account} filterCount={[account,status,company].filter(Boolean).length} filters={filterControls} onSelect={select}/></>}
    <Dialog open={selected!==null} onOpenChange={open=>{if(!open)select(null)}}>{selected!==null && <InterviewDetails key={selected} id={selected} onRemoved={()=>select(null)} stages={query.data?.stages||[]} statuses={query.data?.statuses||[]}/>}</Dialog>
  </div>
}
