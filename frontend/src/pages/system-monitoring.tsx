import {useState} from 'react'
import {useQuery} from '@tanstack/react-query'
import {Activity, Pause, Play, RefreshCw} from 'lucide-react'
import {useAuth} from '@/components/auth'
import {request} from '@/lib/api'
import {Button} from '@/components/ui/button'
import {Card} from '@/components/ui/card'
import {Loading, PageHeading} from '@/components/common'
import MonitorEventHistory from '@/components/monitor-event-history'
import './system-monitoring.css'

type Health = 'healthy'|'degraded'|'unavailable'|'disabled'|'unknown'
type Component = {id:string;name:string;status:Health;detail:string;workspace?:string|null}
type Workspace = {id:string;name:string;enabled:boolean;outbox:number|null;pending_jobs?:number|null;accounts:{account_id:number;enabled:boolean;last_sync:number|null;status:Health}[];queues:{kind:string;pending:number;retry:number;dead:number}[]}
type Event = {job_id?:string;id:string;at:number;workspace:string;component:string;action:string;status:Health}
type Snapshot = {checked_at:number;components:Component[];workspaces:Workspace[];events:Event[];event_retention:number;architecture?:'shared';process_counts?:{api:number;collection:number;model:number};global_queues?:{kind:string;pending:number;retry:number;dead:number}[]}
const clock = (value:number) => new Date(value*1000).toLocaleString()
function globalComponents(items:Component[]){
 const global=items.filter(c=>!c.workspace)
 const pools=[['shared-api-','Shared API pool'],['shared-job-collection-','Collection pool'],['shared-job-model-','Model worker']]
 const result=global.filter(c=>!pools.some(([prefix])=>c.id.startsWith(prefix)))
 for(const [prefix,name] of pools){
  const members=global.filter(c=>c.id.startsWith(prefix))
  if(!members.length)continue
  const ready=members.filter(c=>c.status==='healthy').length
  const status:Health=ready===members.length?'healthy':members.every(c=>c.status==='unavailable')?'unavailable':members.every(c=>c.status==='unknown')?'unknown':'degraded'
  result.push({id:prefix,name,status,detail:`${ready} of ${members.length} processes ready.`})
 }
 return result
}
function queueTotals(data:Snapshot){
 if(data.architecture==='shared')return data.global_queues??[]
 const totals=new Map<string,{kind:string;pending:number;retry:number;dead:number}>()
 for(const workspace of data.workspaces)for(const queue of workspace.queues){
  const previous=totals.get(queue.kind)??{kind:queue.kind,pending:0,retry:0,dead:0}
  totals.set(queue.kind,{kind:queue.kind,pending:previous.pending+queue.pending,retry:previous.retry+queue.retry,dead:previous.dead+queue.dead})
 }
 return [...totals.values()]
}
function SharedFlow({counts}:{counts:Snapshot['process_counts']}){
 const box=(title:string,detail:string)=><span className="monitor-flow-box"><strong>{title}</strong><span>{detail}</span></span>
 const arrow=(label:string)=><span className="monitor-flow-arrow"><span aria-hidden="true">→</span><small>{label}</small></span>
 return <section aria-labelledby="monitor-shared-flow"><h2 id="monitor-shared-flow">Shared process and data flow</h2><p className="muted">Shared pools serve all enabled workspaces. Every request and job resolves its authorized workspace before reading or writing that workspace's database.</p>
 <ol className="monitor-architecture" aria-label="API data access"><li>{box('Browser','Authenticated API requests')}{arrow('request')}</li><li>{box('Gateway','Session checks and workspace routing')}{arrow('authorized request')}</li><li>{box('Shared API pool',`${counts?.api??'?'} processes · workspace API`)}{arrow('read / write')}</li><li>{box('Workspace databases','Separate data and configuration per workspace')}</li></ol>
 <ol className="monitor-architecture" aria-label="Job processing"><li>{box('Job triggers','Provider notifications, scheduled checks and manual actions')}{arrow('enqueue through gateway / scheduler')}</li><li>{box('RabbitMQ job queues','Global queues · bounded retries and dead letters')}{arrow('consume')}</li><li><div className="monitor-flow-stack">{box('Collection pool',`${counts?.collection??'?'} processes · mail and calendar`)}{box('Model process',`${counts?.model??'?'} process · classification`)}</div>{arrow('commit to workspace database')}</li><li>{box('Durable results and outbox','Workspace-scoped changes ready for publication')}</li></ol>
 <ol className="monitor-architecture monitor-change-path" aria-label="Browser change delivery"><li>{box('Committed outbox','Durable change hints')}{arrow('publish')}</li><li>{box('RabbitMQ change exchange','One temporary queue per gateway')}{arrow('fanout')}</li><li>{box('Gateway SSE','Workspace-scoped hints and reconnect resync')}{arrow('refresh')}</li><li>{box('Browser refresh','Authorized API fetches current data')}</li></ol></section>
}
function Badge({status}:{status:Health}){return <span className={`monitor-badge monitor-${status}`}><span aria-hidden="true"/>{status}</span>}

export default function SystemMonitoring(){
 const {session}=useAuth()
 const [paused,setPaused]=useState(false),[workspace,setWorkspace]=useState('all'),[component,setComponent]=useState('all'),[issuesOnly,setIssuesOnly]=useState(false)
 const [frozen,setFrozen]=useState<Snapshot|undefined>()
 const query=useQuery({queryKey:['system-monitoring'],queryFn:({signal})=>request<Snapshot>('/api/admin/system-monitoring',{signal}),enabled:!!session?.is_owner&&!paused,refetchInterval:paused?false:3000,retry:false})
 if(!session?.is_owner)return <div className="page-wrap"><PageHeading title="Owner access required"/></div>
 const data=paused?frozen:query.data
 const names=new Map(data?.workspaces.map(w=>[w.id,w.name]))
 const components=globalComponents(data?.components??[])
 const queues=data?queueTotals(data):[]
 const backlog=queues.length?queues.reduce((sum,q)=>({pending:sum.pending+q.pending,retry:sum.retry+q.retry,dead:sum.dead+q.dead}),{pending:0,retry:0,dead:0}):undefined
 const events=data?.events.filter(e=>(workspace==='all'||e.workspace===workspace)&&(component==='all'||e.component===component)&&(!issuesOnly||e.status==='degraded'||e.status==='unavailable'))??[]
 return <div className="page-wrap system-monitoring-page">
  <PageHeading title="System monitoring" description="Shared service health, processing backlog, and operational event flow."/>
  <div className="monitor-toolbar"><span className="monitor-live"><Activity size={16}/>{paused?'Updates paused':query.isError?'Connection interrupted':'Refreshes every 3 seconds'}</span><span className="muted">{data?`Last checked ${clock(data.checked_at)}`:'Awaiting first snapshot'}</span><Button variant="outline" onClick={()=>{if(!paused)setFrozen(query.data);setPaused(!paused)}}>{paused?<Play size={16}/>:<Pause size={16}/>} {paused?'Resume live updates':'Pause live updates'}</Button><Button variant="outline" disabled={query.isFetching||paused} onClick={()=>void query.refetch()} aria-label="Refresh monitoring"><RefreshCw size={16}/></Button></div>
  {!paused&&query.isError&&<p role="alert" className="inline-error">Monitoring is unavailable. {data?'The snapshot below is stale.':'No health data has been received.'} {query.error.message}</p>}
  {paused&&<p role="status">Live updates are paused. Health and events reflect the last snapshot.</p>}
  {!data&&query.isPending&&!paused?<Loading/>:null}
  {data&&<>
   <div role="region" aria-label="Queue backlog" className="monitor-overview"><Card><strong>{backlog?.pending??'—'}</strong><span>{data.architecture==='shared'?'Ready jobs':'Outstanding jobs'}</span></Card><Card><strong>{backlog?.retry??'—'}</strong><span>Delayed retries</span></Card><Card><strong>{backlog?.dead??'—'}</strong><span>Dead letters</span></Card></div>
   {data.architecture==='shared'&&<SharedFlow counts={data.process_counts}/>}
   <section aria-labelledby="monitor-health"><h2 id="monitor-health">Shared service health</h2><p className="muted">Health is based on local service checks and process readiness. Provider and model reachability are not actively probed. Unknown means no current evidence.</p><div className="monitor-component-grid">{components.map(c=><Card key={c.id} className="monitor-component"><div><h3>{c.name}</h3><Badge status={c.status}/></div><p>{c.detail}</p></Card>)}</div></section>
   <section aria-labelledby="monitor-global-queues"><h2 id="monitor-global-queues">{data.architecture==='shared'?'Global RabbitMQ queues':'Processing queues'}</h2><p className="muted">{data.architecture==='shared'?'These queues are shared across workspaces. Ready messages exclude in-flight work; delayed retries and dead letters are measured separately.':'Counts are aggregated across workspaces. Outstanding jobs include queued and in-progress work.'}</p>{queues.length?<Card className="monitor-table-scroll"><table><caption className="sr-only">System queue counts</caption><thead><tr><th>Stage</th><th>{data.architecture==='shared'?'Ready messages':'Outstanding jobs'}</th><th>Delayed retries</th><th>Dead letters</th></tr></thead><tbody>{queues.map(q=><tr key={q.kind}><td>{q.kind==='mail'?'Mail collection':q.kind==='calendar'?'Calendar collection':q.kind==='classify'?'Classification':q.kind}</td><td>{q.pending}</td><td>{q.retry}</td><td>{q.dead}</td></tr>)}</tbody></table></Card>:<p role="status">Queue metrics unavailable.</p>}</section>
   <section aria-labelledby="monitor-flow"><h2 id="monitor-flow">Live event flow</h2><p className="muted">Queued → started → completed → published. Failed jobs may retry or move to dead letters. Events begin after monitoring instrumentation is installed; up to {data.event_retention} are retained per workspace, with the latest 200 shown here. Telemetry is best effort and contains no email content.</p><div className="monitor-filters"><label>Event workspace<select value={workspace} onChange={e=>setWorkspace(e.target.value)}><option value="all">All workspaces</option>{data.workspaces.map(w=><option key={w.id} value={w.id}>{w.name}</option>)}</select></label><label>Event component<select value={component} onChange={e=>setComponent(e.target.value)}><option value="all">All components</option><option value="mail">Mail collection</option><option value="calendar">Calendar collection</option><option value="classify">Classification</option><option value="events">Event publication</option></select></label><label className="monitor-checkbox"><input type="checkbox" checked={issuesOnly} onChange={e=>setIssuesOnly(e.target.checked)}/>Issues only</label></div><MonitorEventHistory events={events} names={names}/></section>
  </>}
 </div>
}
