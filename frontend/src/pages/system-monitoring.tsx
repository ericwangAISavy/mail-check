import {useState} from 'react'
import {keepPreviousData,useQuery} from '@tanstack/react-query'
import {AlertTriangle,CheckCircle2,CircleHelp,MinusCircle,Pause,Play,RefreshCw,XCircle} from 'lucide-react'
import {useAuth} from '@/components/auth'
import {request} from '@/lib/api'
import {Button} from '@/components/ui/button'
import {Loading, PageHeading} from '@/components/common'
import MonitorChart,{Sparkline,type ChartSeries} from '@/components/monitor-chart'
import './system-monitoring.css'

type Health='healthy'|'degraded'|'unavailable'|'disabled'|'unknown'
type Component={id:string;name:string;status:Health;detail:string;workspace?:string|null}
type Queue={kind:string;pending:number;retry:number;dead:number}
type Workspace={id:string;name:string;enabled:boolean;outbox:number|null;pending_jobs?:number|null;accounts:{account_id:number;enabled:boolean;last_sync:number|null;status:Health}[];queues:Queue[]}
type Event={job_id?:string;id:string;at:number;workspace:string;component:string;action:string;status:Health}
type Snapshot={checked_at:number;components:Component[];workspaces:Workspace[];events:Event[];event_retention:number;architecture?:'shared';process_counts?:{api:number;collection:number;model:number};global_queues?:Queue[]}
type Series=(number|null)[]
type Stage={stage:string;queued:number;started:number;completed:number;retry_or_failed:number;discarded:number;failure_rate:number|null;duration_p50:number|null;duration_p95:number|null}
type Metrics={range:Range;step:number;buckets:number[];generated_at:number;jobs_tracked?:boolean
 traffic:{requests:number[];client_errors:number[];server_errors:number[];throttled:number[];p50:Series;p95:Series}
 jobs:{completed:number[];failed:number[];discarded:number[];queued:number[];p95:Series}
 queues:{ready:Series;retry:Series;dead:Series}
 summary:{requests:number;client_errors:number;server_errors:number;error_rate:number|null;p50:number|null;p95:number|null;completed:number;failed:number;discarded:number;failure_rate:number|null}
 stages:Stage[]}
type Range='1h'|'6h'|'24h'

const RANGES:{value:Range;label:string;refresh:number}[]=[{value:'1h',label:'1 hour',refresh:15000},{value:'6h',label:'6 hours',refresh:30000},{value:'24h',label:'24 hours',refresh:60000}]
const STAGES:Record<string,string>={mail:'Mail collection',calendar:'Calendar collection',classify:'Classification',other:'Other jobs',events:'Event publication'}
const C={blue:'var(--mon-blue)',aqua:'var(--mon-aqua)',warning:'var(--mon-warning)',serious:'var(--mon-serious)',critical:'var(--mon-critical)'}
const compact=new Intl.NumberFormat(undefined,{notation:'compact',maximumFractionDigits:1})
const count=(v:number)=>v<10000?Math.round(v).toLocaleString():compact.format(v)
const ms=(v:number)=>v<1000?`${Math.round(v)} ms`:`${(v/1000).toFixed(v<10000?1:0)} s`
const seconds=(v:number)=>v<60?`${v<10?v.toFixed(1):Math.round(v)} s`:`${(v/60).toFixed(1)} min`
const percent=(v:number|null)=>v===null?'—':`${(v*100).toFixed(v<.1?1:0)}%`
const STATUS:{[K in Health]:{label:string;icon:typeof CheckCircle2}}={healthy:{label:'Healthy',icon:CheckCircle2},degraded:{label:'Degraded',icon:AlertTriangle},unavailable:{label:'Down',icon:XCircle},disabled:{label:'Off',icon:MinusCircle},unknown:{label:'No data',icon:CircleHelp}}

function worst(items:Health[]):Health{
 for(const status of ['unavailable','degraded','healthy','unknown','disabled'] as Health[])if(items.includes(status))return status
 return 'unknown'
}
/** One tile per service: pools and per-workspace parts are rolled up with ready counts. */
function services(data:Snapshot){
 const items=data.components
 const tiles:{id:string;name:string;status:Health;meter?:[number,number];note?:string;detail?:string}[]=[]
 const pools:[string,string][]=[['shared-api-','API pool'],['shared-job-collection-','Collection pool'],['shared-job-model-','Model worker']]
 const short:Record<string,string>={'model-scheduler':'Model scheduler','control-db':'Control database','rabbitmq':'RabbitMQ','redis':'Redis'}
 for(const c of items.filter(c=>!c.workspace&&!pools.some(([prefix])=>c.id.startsWith(prefix))))tiles.push({id:c.id,name:short[c.id]??c.name,status:c.status,detail:c.detail})
 for(const [prefix,name] of pools){
  const members=items.filter(c=>!c.workspace&&c.id.startsWith(prefix));if(!members.length)continue
  const ready=members.filter(c=>c.status==='healthy').length
  tiles.push({id:prefix,name,status:ready===members.length?'healthy':members.every(c=>c.status==='unavailable')?'unavailable':members.every(c=>c.status==='unknown')?'unknown':'degraded',meter:[ready,members.length],note:`${ready}/${members.length} ready`})
 }
 const databases=items.filter(c=>c.workspace&&c.id.endsWith(':database')&&c.status!=='disabled')
 if(databases.length){const ok=databases.filter(c=>c.status==='healthy').length;tiles.push({id:'databases',name:'Databases',status:worst(databases.map(c=>c.status)),meter:[ok,databases.length],note:`${ok}/${databases.length} readable`})}
 const outbox=data.workspaces.reduce((sum,w)=>sum+(w.outbox??0),0)
 if(data.workspaces.some(w=>w.outbox!==null))tiles.push({id:'publication',name:'Publication',status:outbox?'degraded':'healthy',note:outbox?`${count(outbox)} waiting`:'Up to date'})
 return tiles
}
function queueTotals(data:Snapshot):Queue[]|null{
 if(data.architecture==='shared')return data.global_queues?.length?data.global_queues:null
 const totals=new Map<string,Queue>()
 for(const workspace of data.workspaces)for(const q of workspace.queues){const p=totals.get(q.kind)??{kind:q.kind,pending:0,retry:0,dead:0};totals.set(q.kind,{kind:q.kind,pending:p.pending+q.pending,retry:p.retry+q.retry,dead:p.dead+q.dead})}
 return totals.size?[...totals.values()]:null
}

function Stat({label,value,sub,trend,color,tone}:{label:string;value:string;sub?:string;trend?:Series;color:string;tone?:Health}){
 const Icon=tone&&tone!=='healthy'?STATUS[tone].icon:null
 return <div className={`monitor-stat${tone&&tone!=='healthy'?` is-${tone}`:''}`}>
  <span className="monitor-stat-label">{label}{Icon&&<Icon size={14} aria-label={STATUS[tone!].label}/>}</span>
  <strong>{value}</strong>
  {sub&&<span className="monitor-stat-sub">{sub}</span>}
  {trend&&<Sparkline values={trend} color={color}/>}
 </div>
}

export default function SystemMonitoring(){
 const {session}=useAuth()
 const [paused,setPaused]=useState(false),[range,setRange]=useState<Range>('1h'),[allEvents,setAllEvents]=useState(false)
 const [frozen,setFrozen]=useState<{snapshot?:Snapshot;metrics?:Metrics}>({})
 const owner=!!session?.is_owner
 const live=useQuery({queryKey:['system-monitoring'],queryFn:({signal})=>request<Snapshot>('/api/admin/system-monitoring',{signal}),enabled:owner&&!paused,refetchInterval:paused?false:5000,retry:false})
 const refresh=RANGES.find(r=>r.value===range)!.refresh
 const series=useQuery({queryKey:['system-monitoring-metrics',range],queryFn:({signal})=>request<Metrics>(`/api/admin/system-monitoring/metrics?range=${range}`,{signal}),enabled:owner&&!paused,refetchInterval:paused?false:refresh,placeholderData:keepPreviousData,retry:false})
 if(!owner)return <div className="page-wrap"><PageHeading title="Owner access required"/></div>
 const data=paused?frozen.snapshot:live.data,metrics=paused?frozen.metrics:series.data
 const names=new Map(data?.workspaces.map(w=>[w.id,w.name]))
 const queues=data?queueTotals(data):null
 const backlog=queues?.reduce((s,q)=>({pending:s.pending+q.pending,retry:s.retry+q.retry,dead:s.dead+q.dead}),{pending:0,retry:0,dead:0})
 const s=metrics?.summary
 const perMinute=metrics?(metrics.step/60)*metrics.buckets.length:1
 const errorTone:Health=s?.error_rate==null?'healthy':s.error_rate>=.05?'unavailable':s.error_rate>=.01?'degraded':'healthy'
 const failTone:Health=s?.failure_rate==null?'healthy':s.failure_rate>=.2?'unavailable':s.failure_rate>=.05?'degraded':'healthy'
 const backlogTone:Health=!backlog?'healthy':backlog.dead?'unavailable':backlog.retry?'degraded':'healthy'
 const problems=(data?.events??[]).filter(e=>allEvents||e.action==='retry_or_failed'||e.action==='discarded')
 const stageQueue=new Map(queues?.map(q=>[q.kind,q]))
 const stageRows=metrics?[...metrics.stages,...[...stageQueue.keys()].filter(k=>!metrics.stages.some(st=>st.stage===k)).map(k=>({stage:k,queued:0,started:0,completed:0,retry_or_failed:0,discarded:0,failure_rate:null,duration_p50:null,duration_p95:null}))]:[]
 const chart=(key:string,label:string,color:string,values:Series,type:'bar'|'line'):ChartSeries=>({key,label,color,values,type})
 const t=metrics?.traffic,j=metrics?.jobs,q=metrics?.queues
 const jobs=metrics?.jobs_tracked!==false
 return <div className="page-wrap system-monitoring-page">
  <PageHeading title="System monitoring"/>
  <div className="monitor-toolbar">
   <div className="monitor-ranges" role="group" aria-label="Time range">{RANGES.map(r=><button key={r.value} type="button" aria-pressed={range===r.value} onClick={()=>setRange(r.value)}>{r.label}</button>)}</div>
   <span className={`monitor-live${live.isError&&!paused?' is-error':''}`}>{paused?'Paused':live.isError?'Connection lost':'Live'}{data&&<span className="muted"> · {new Date(data.checked_at*1000).toLocaleTimeString()}</span>}</span>
   <Button variant="outline" size="sm" onClick={()=>{if(!paused)setFrozen({snapshot:live.data,metrics:series.data});setPaused(!paused)}}>{paused?<Play size={15}/>:<Pause size={15}/>} {paused?'Resume live updates':'Pause live updates'}</Button>
   <Button variant="outline" size="sm" disabled={live.isFetching||paused} onClick={()=>{void live.refetch();void series.refetch()}} aria-label="Refresh monitoring"><RefreshCw size={15}/></Button>
  </div>
  {!paused&&live.isError&&<p role="alert" className="inline-error">Monitoring is unavailable{data?'; showing the last snapshot':''}. {live.error.message}</p>}
  {!data&&live.isPending&&!paused?<Loading/>:null}
  {data&&<div className={`monitor-body${series.isFetching&&series.isPlaceholderData?' is-refreshing':''}`}>
   <section className="monitor-stats" aria-label="Key metrics">
    <Stat label="Requests" value={s?count(s.requests):'—'} sub={s?`${count(s.requests/perMinute)}/min average`:undefined} trend={t?.requests} color={C.blue}/>
    <Stat label="Server errors" value={percent(s?.error_rate??null)} sub={s?`${count(s.server_errors)} 5xx · ${count(s.client_errors)} 4xx`:undefined} trend={t?.server_errors} color={C.critical} tone={errorTone}/>
    <Stat label="Response time p95" value={s?.p95!=null?ms(s.p95):'—'} sub={s?.p50!=null?`p50 ${ms(s.p50)}`:undefined} trend={t?.p95} color={C.blue}/>
    <Stat label="Jobs completed" value={s&&jobs?count(s.completed):'—'} sub={!jobs?'Not tracked in this mode':s?`${count(s.completed/perMinute*60)}/hour`:undefined} trend={jobs?j?.completed:undefined} color={C.blue}/>
    <Stat label="Retries & failures" value={s&&jobs?count(s.failed+s.discarded):'—'} sub={!jobs?'Not tracked in this mode':s?(s.failure_rate===null?'No finished jobs':`${percent(s.failure_rate)} of finished jobs`):undefined} trend={jobs?j?.failed:undefined} color={C.serious} tone={jobs?failTone:undefined}/>
    <div role="region" aria-label="Queue backlog" className="monitor-backlog-region"><Stat label="Queue backlog" value={backlog?count(backlog.pending+backlog.retry+backlog.dead):'—'} sub={backlog?`${count(backlog.pending)} ready · ${count(backlog.retry)} retrying · ${count(backlog.dead)} dead`:'Queue metrics unavailable.'} trend={q?.ready} color={C.blue} tone={backlogTone}/></div>
   </section>

   <section className="monitor-services" aria-label="Service health">{services(data).map(tile=>{const Icon=STATUS[tile.status].icon;return <div key={tile.id} className={`monitor-service is-${tile.status}`} title={tile.detail}>
    <Icon size={16} aria-hidden="true"/><span className="monitor-service-name">{tile.name}</span><span className="monitor-service-state">{tile.note??STATUS[tile.status].label}</span>
    {tile.meter&&<span className="monitor-meter" aria-hidden="true"><span style={{width:`${tile.meter[1]?tile.meter[0]/tile.meter[1]*100:0}%`}}/></span>}
    <span className="sr-only">{STATUS[tile.status].label}</span></div>})}</section>

   {metrics&&t&&j&&q?<div className="monitor-charts">
    <MonitorChart title="Traffic" summary={`${count(s!.requests)} requests`} buckets={metrics.buckets} step={metrics.step} format={count}
     series={[chart('ok','Successful',C.blue,t.requests.map((v,i)=>Math.max(0,v-t.client_errors[i]-t.server_errors[i])),'bar'),chart('4xx','Client errors (4xx)',C.warning,t.client_errors,'bar'),chart('5xx','Server errors (5xx)',C.critical,t.server_errors,'bar')]}/>
    <MonitorChart title="Response time" summary={s?.p95!=null?`p95 ${ms(s.p95)}`:undefined} buckets={metrics.buckets} step={metrics.step} format={ms}
     series={[chart('p95','p95',C.blue,t.p95,'line'),chart('p50','p50',C.aqua,t.p50,'line')]}/>
    {jobs&&<MonitorChart title="Job outcomes" summary={`${count(s!.completed)} completed`} buckets={metrics.buckets} step={metrics.step} format={count}
     series={[chart('done','Completed',C.blue,j.completed,'bar'),chart('retry','Retried or failed',C.serious,j.failed,'bar'),chart('dead','Discarded',C.critical,j.discarded,'bar')]}/>}
    <MonitorChart title="Queue backlog" summary={backlog?`${count(backlog.pending+backlog.retry+backlog.dead)} now`:undefined} buckets={metrics.buckets} step={metrics.step} format={count}
     series={[chart('ready','Ready',C.blue,q.ready,'line'),chart('retrying','Retrying',C.serious,q.retry,'line'),chart('deadq','Dead letters',C.critical,q.dead,'line')]}/>
   </div>:series.isError?<p role="alert" className="inline-error">Graphs are unavailable. {series.error.message}</p>:<Loading/>}

   {stageRows.length>0&&(jobs||stageQueue.size>0)&&<section aria-labelledby="monitor-stages"><h2 id="monitor-stages">Processing stages</h2>
    <div className="monitor-table-scroll"><table><thead><tr><th>Stage</th><th>Completed</th><th>Retried / failed</th><th>Discarded</th><th>Failure rate</th><th>Time p95</th><th>Ready</th><th>Retrying</th><th>Dead</th></tr></thead>
     <tbody>{stageRows.map(row=>{const stageLive=stageQueue.get(row.stage);const rate=row.failure_rate;return <tr key={row.stage}>
      <th scope="row">{STAGES[row.stage]??row.stage}</th><td>{jobs?count(row.completed):'—'}</td><td>{jobs?count(row.retry_or_failed):'—'}</td><td>{jobs?count(row.discarded):'—'}</td>
      <td>{jobs?<span className="monitor-rate"><span className="monitor-meter" aria-hidden="true"><span className={rate!==null&&rate>=.05?'is-bad':''} style={{width:`${Math.min(100,(rate??0)*100)}%`}}/></span>{percent(rate)}</span>:'—'}</td>
      <td>{row.duration_p95!=null?seconds(row.duration_p95):'—'}</td><td>{stageLive?count(stageLive.pending):'—'}</td><td>{stageLive?count(stageLive.retry):'—'}</td><td className={stageLive?.dead?'is-bad':''}>{stageLive?count(stageLive.dead):'—'}</td></tr>})}</tbody></table></div>
   </section>}

   <section aria-labelledby="monitor-events"><div className="monitor-section-head"><h2 id="monitor-events">{allEvents?'Recent events':'Recent problems'}</h2>
    <label className="monitor-checkbox"><input type="checkbox" checked={allEvents} onChange={e=>setAllEvents(e.target.checked)}/>Show all events</label></div>
    {problems.length?<div className="monitor-table-scroll"><table><thead><tr><th>Time</th><th>Stage</th><th>Outcome</th><th>Workspace</th></tr></thead><tbody>{problems.slice(0,allEvents?200:20).map(e=><tr key={e.id} className={e.action==='retry_or_failed'||e.action==='discarded'?'is-problem':undefined}>
     <td><time dateTime={new Date(e.at*1000).toISOString()}>{new Date(e.at*1000).toLocaleString()}</time></td><td>{STAGES[e.component]??e.component}</td><td>{e.action==='retry_or_failed'?'Retried or failed':e.action.replaceAll('_',' ')}</td><td>{names.get(e.workspace)??'Unknown workspace'}</td></tr>)}</tbody></table></div>
    :<p className="monitor-empty">{allEvents?'No events recorded yet.':'No retries or failures in the recent event log.'}</p>}
   </section>
  </div>}
 </div>
}
