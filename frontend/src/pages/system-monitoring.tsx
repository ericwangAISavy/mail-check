import {useEffect,useState} from 'react'
import {keepPreviousData,useQuery} from '@tanstack/react-query'
import {AlertTriangle,CheckCircle2,CircleHelp,MinusCircle,Pause,Play,RefreshCw,XCircle} from 'lucide-react'
import {useAuth} from '@/components/auth'
import {request} from '@/lib/api'
import {Button} from '@/components/ui/button'
import {Loading, PageHeading} from '@/components/common'
import MonitorChart,{Sparkline,type ChartSeries} from '@/components/monitor-chart'
import './system-monitoring.css'

type Health='healthy'|'degraded'|'unavailable'|'disabled'|'unknown'
type Component={id:string;name:string;status:Health;detail:string;workspace?:string|null;reason?:string}
type Queue={kind:string;pending:number;retry:number;dead:number}
type Workspace={id:string;name:string;enabled:boolean;outbox:number|null;pending_jobs?:number|null;accounts:{account_id:number;enabled:boolean;last_sync:number|null;status:Health}[];queues:Queue[]}
type Event={detail?:string;job_id?:string;evidence?:Record<string,string|number>;id:string;at:number;workspace:string;component:string;action:string;status:Health}
type Snapshot={checked_at:number;observer_origin?:string;observer_stale?:boolean;components:Component[];workspaces:Workspace[];events:Event[];event_retention:number;architecture?:'shared';process_counts?:{api:number;collection:number;model:number};global_queues?:Queue[]}
type Series=(number|null)[]
type Stage={stage:string;queued:number;started:number;completed:number;retry_or_failed:number;discarded:number;failure_rate:number|null;duration_p50:number|null;duration_p95:number|null}
type Metrics={range:Range;step:number;buckets:number[];generated_at:number;observer_stale?:boolean;jobs_tracked?:boolean;jobs_current_available?:boolean;jobs_coverage_incomplete?:boolean;traffic_available?:boolean;source?:string
 traffic:{requests:number[];client_errors:number[];server_errors:number[];throttled:number[];p50:Series;p95:Series}
 jobs:{completed:Series;failed:Series;discarded:Series;queued:Series;p95:Series}
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
 for(const status of ['unavailable','degraded','unknown','healthy','disabled'] as Health[])if(items.includes(status))return status
 return 'unknown'
}
/** One tile per service: pools and per-workspace parts are rolled up with ready counts. */
function services(data:Snapshot){
 const items=data.components
 const tiles:{id:string;name:string;status:Health;meter?:[number,number];note?:string;detail?:string;evidence?:Component[]}[]=[]
 const pools:[string,string][]=[['shared-api-','API pool'],['shared-job-collection-','Collection pool'],['shared-job-model-','Model worker']]
 const short:Record<string,string>={'model-scheduler':'Model scheduler','control-db':'Control database','rabbitmq':'RabbitMQ','redis':'Redis'}
 for(const c of items.filter(c=>(!c.workspace||c.id.startsWith('subscriptions:')||c.id.startsWith('coordinator:'))&&!pools.some(([prefix])=>c.id.startsWith(prefix))))tiles.push({id:c.id,name:short[c.id]??c.name,status:c.status,detail:c.detail,evidence:[c]})
 for(const [prefix,name] of pools){
  const members=items.filter(c=>c.id.startsWith(prefix));if(!members.length)continue
  const ready=members.filter(c=>c.status==='healthy').length
  tiles.push({id:prefix,name,status:ready===members.length?'healthy':members.every(c=>c.status==='unavailable')?'unavailable':members.every(c=>c.status==='unknown')?'unknown':'degraded',meter:[ready,members.length],note:`${ready}/${members.length} ready`,evidence:members})
 }
 for(const c of items.filter(c=>pools.some(([prefix])=>c.id.startsWith(prefix))&&c.status!=="healthy"))tiles.push({id:c.id,name:c.name,status:c.status,detail:c.detail,evidence:[c]})
 const databases=items.filter(c=>c.workspace&&c.id.endsWith(':database')&&c.status!=='disabled')
 const incomplete=items.some(c=>c.id==='workspace-registry'&&c.status!=='healthy')
 if(databases.length){const ok=databases.filter(c=>c.status==='healthy').length,missing=databases.filter(c=>c.reason==='database_missing').length;tiles.push({id:'databases',name:'Databases',status:worst([...databases.map(c=>c.status),...(incomplete?['unknown' as Health]:[])]),meter:[ok,databases.length],note:`${ok}/${databases.length} readable${missing?` · ${missing} not initialized`:''}${incomplete?' · coverage unknown':''}`,evidence:databases})}
 const active=data.workspaces.filter(w=>w.enabled)
 const outbox=active.reduce((sum,w)=>sum+(w.outbox??0),0)
 const unknown=active.filter(w=>w.outbox===null).length
 if(active.length||incomplete)tiles.push({id:'publication',name:'Publication',status:outbox?'degraded':unknown||incomplete?'unknown':'healthy',note:[outbox?`${count(outbox)} waiting`:'',unknown?`${unknown} unknown`:'',incomplete?'coverage unknown':''].filter(Boolean).join(' · ')||'No pending outbox rows',detail:'Outbox counts only. An empty outbox does not prove delivery to browsers.'})
 return tiles
}
const evidenceFields=new Set(['scope','reason','probe_stage','first_failure_reason','first_failure_stage','attempts','shell_http_status','asset_http_status','pid','worker','workspace','account_id','operation','failure_count','job_id','kind','attempt','error_type','errno','winerror','sqlite_errorcode','http_status','source_location','checked_at','duration_ms','operation_age_seconds','poll_age_seconds','write_status','telemetry_status','telemetry_reason','telemetry_checked_at'])
function Evidence({value}:{value:object}){
 return <dl className="monitor-evidence">{Object.entries(value).filter(([key,item])=>evidenceFields.has(key)&&(typeof item==='string'||typeof item==='number')).map(([key,item])=><div key={key}><dt>{key.replaceAll('_',' ')}</dt><dd>{key==='checked_at'?new Date(Number(item)*1000).toLocaleString():String(item)}</dd></div>)}</dl>
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
 return <MonitoringView owner={!!session?.is_owner}/>
}

export function MonitoringView({owner,independent=false}:{owner:boolean;independent?:boolean}){
 const [clock,setClock]=useState(()=>Date.now()/1000)
 useEffect(()=>{const timer=window.setInterval(()=>setClock(Date.now()/1000),5000);return()=>window.clearInterval(timer)},[])
 const [paused,setPaused]=useState(false),[range,setRange]=useState<Range>('1h'),[allEvents,setAllEvents]=useState(false)
 const [frozen,setFrozen]=useState<{snapshot?:Snapshot;metrics?:Metrics}>({})
 const live=useQuery({queryKey:['system-monitoring'],queryFn:({signal})=>request<Snapshot>('/api/admin/system-monitoring',{signal}),enabled:owner&&!paused,refetchInterval:paused?false:5000,retry:false})
 const refresh=RANGES.find(r=>r.value===range)!.refresh
 const series=useQuery({queryKey:['system-monitoring-metrics',range],queryFn:({signal})=>request<Metrics>(`/api/admin/system-monitoring/metrics?range=${range}`,{signal}),enabled:owner&&!paused,refetchInterval:paused?false:refresh,placeholderData:keepPreviousData,retry:false})
 if(!owner)return <div className="page-wrap"><PageHeading title="Owner access required"/></div>
 const data=paused?frozen.snapshot:live.data,metrics=paused?frozen.metrics:series.data
 const stale=!!data?.observer_stale||(!paused&&(live.isError||!!data&&clock-data.checked_at>15))
 const names=new Map(data?.workspaces.map(w=>[w.id,w.name]))
 const queues=data?queueTotals(data):null
 const backlog=queues?.reduce((s,q)=>({pending:s.pending+q.pending,retry:s.retry+q.retry,dead:s.dead+q.dead}),{pending:0,retry:0,dead:0})
 const trafficAvailable=metrics?.traffic_available!==false
 const s=metrics?.summary
 const perMinute=metrics?(metrics.step/60)*metrics.buckets.length:1
 const errorTone:Health=s?.error_rate==null?'healthy':s.error_rate>=.05?'unavailable':s.error_rate>=.01?'degraded':'healthy'
 const failTone:Health=s?.failure_rate==null?'healthy':s.failure_rate>=.2?'unavailable':s.failure_rate>=.05?'degraded':'healthy'
 const backlogTone:Health=!backlog?'unknown':backlog.retry?'degraded':'healthy'
 const problems=(data?.events??[]).filter(e=>allEvents||['retry_or_failed','discarded','service_failed','service_degraded','service_unknown','deferred_busy','deferred_offline','deferred_state'].includes(e.action))
 const stageQueue=new Map(queues?.map(q=>[q.kind,q]))
 const stageRows=metrics?[...metrics.stages,...[...stageQueue.keys()].filter(k=>!metrics.stages.some(st=>st.stage===k)).map(k=>({stage:k,queued:0,started:0,completed:0,retry_or_failed:0,discarded:0,failure_rate:null,duration_p50:null,duration_p95:null}))]:[]
 const chart=(key:string,label:string,color:string,values:Series,type:'bar'|'line'):ChartSeries=>({key,label,color,values,type})
 const t=metrics?.traffic,j=metrics?.jobs,q=metrics?.queues
 const jobs=metrics?.jobs_tracked!==false
 return <div className="page-wrap system-monitoring-page">
  {!independent&&<p><a href="http://127.0.0.1:52401" target="_blank" rel="noreferrer">Independent local monitoring</a> · Open on the server PC to inspect availability and logs during an outage.</p>}
  <PageHeading title="System monitoring"/>
  <div className="monitor-toolbar">
   <div className="monitor-ranges" role="group" aria-label="Time range">{RANGES.map(r=><button key={r.value} type="button" aria-pressed={range===r.value} disabled={paused} title={paused?'Resume live updates to change the range':undefined} onClick={()=>setRange(r.value)}>{r.label}</button>)}</div>
   <span className={`monitor-live${(live.isError||stale)&&!paused?' is-error':''}`}>{paused?'Paused':live.isError?'Connection lost':stale?'Last known data':'Live'}{data&&<span className="muted"> · {new Date(data.checked_at*1000).toLocaleTimeString()}</span>}</span>
   <Button variant="outline" size="sm" onClick={()=>{if(!paused)setFrozen({snapshot:live.data,metrics:series.data});setPaused(!paused)}}>{paused?<Play size={15}/>:<Pause size={15}/>} {paused?'Resume live updates':'Pause live updates'}</Button>
   <Button variant="outline" size="sm" disabled={live.isFetching||paused} onClick={()=>{void live.refetch();void series.refetch()}} aria-label="Refresh monitoring"><RefreshCw size={15}/></Button>
  </div>
  {!paused&&live.isError&&<p role="alert" className="inline-error">Monitoring is unavailable{data?'; showing the last snapshot':''}. {live.error.message}</p>}
  {!data&&live.isPending&&!paused?<Loading/>:null}
  {data&&<div className={`monitor-body${series.isFetching&&series.isPlaceholderData?' is-refreshing':''}`}>
   {metrics?.observer_stale&&<p role="status" className="muted">Charts show recorded data from {new Date(metrics.generated_at*1000).toLocaleString()}. Waiting for updated metrics.</p>}
   {!trafficAvailable&&<p role="status" className="inline-error">Traffic measurements are unavailable while the gateway cannot report. Job and queue charts use independent observations.</p>}
   {metrics?.jobs_current_available===false?<p role="status" className="monitor-coverage-warning">Job monitoring is not fully reporting. Expand Job telemetry → Evidence to identify affected workers.</p>:metrics?.jobs_coverage_incomplete?<details className="monitor-history-note"><summary>Earlier monitoring gaps</summary><p>Some intervals in this time range have no confirmed job telemetry. Totals include recorded events; gaps do not mean zero jobs.</p></details>:null}
   <section className="monitor-stats" aria-label="Key metrics">
    <Stat label="Requests" value={s&&trafficAvailable?count(s.requests):'—'} sub={s&&trafficAvailable?`${count(s.requests/perMinute)}/min average`:undefined} trend={trafficAvailable?t?.requests:undefined} color={C.blue}/>
    <Stat label="Server errors" value={percent(trafficAvailable?s?.error_rate??null:null)} sub={s&&trafficAvailable?`${count(s.server_errors)} 5xx · ${count(s.client_errors)} 4xx`:undefined} trend={trafficAvailable?t?.server_errors:undefined} color={C.critical} tone={trafficAvailable?errorTone:'unknown'}/>
    <Stat label="Response time p95" value={trafficAvailable&&s?.p95!=null?ms(s.p95):'—'} sub={trafficAvailable&&s?.p50!=null?`p50 ${ms(s.p50)}`:undefined} trend={trafficAvailable?t?.p95:undefined} color={C.blue}/>
    <Stat label="Jobs completed" value={s&&jobs?count(s.completed):'—'} sub={!jobs?'Not tracked in this mode':s?`${count(s.completed/perMinute*60)}/hour`:undefined} trend={jobs?j?.completed:undefined} color={C.blue}/>
    <Stat label="Retries & failures" value={s&&jobs?count(s.failed+s.discarded):'—'} sub={!jobs?'Not tracked in this mode':s?(s.failure_rate===null?'No finished jobs':`${percent(s.failure_rate)} of finished jobs`):undefined} trend={jobs?j?.failed:undefined} color={C.serious} tone={jobs?failTone:undefined}/>
    <div role="region" aria-label="Queue backlog" className="monitor-backlog-region"><Stat label="Queue backlog" value={backlog?count(backlog.pending+backlog.retry):'—'} sub={backlog?`${count(backlog.pending)} ready · ${count(backlog.retry)} retrying`:'Queue metrics unavailable.'} trend={q?.ready} color={C.blue} tone={backlogTone}/></div>
    <div role="region" aria-label="Dead-lettered jobs" className="monitor-backlog-region"><Stat label="Dead-lettered jobs" value={backlog?count(backlog.dead):'—'} sub={backlog?'Retained failed jobs':'Queue metrics unavailable.'} trend={q?.dead} color={C.critical} tone={!backlog?'unknown':backlog.dead?'unavailable':'healthy'}/></div>
   </section>

   <section className="monitor-services" aria-label="Service health">{services(data).map(tile=>{if(stale)tile={...tile,status:"unknown",note:"Last known state"};const Icon=STATUS[tile.status].icon;return <div key={tile.id} className={`monitor-service is-${tile.status}`} title={tile.detail}>
    <Icon size={16} aria-hidden="true"/><span className="monitor-service-name">{tile.name}</span><span className="monitor-service-state">{tile.note??STATUS[tile.status].label}</span>
    {tile.meter&&<span className="monitor-meter" aria-hidden="true"><span style={{width:`${tile.meter[1]?tile.meter[0]/tile.meter[1]*100:0}%`}}/></span>}
    <span className="sr-only">{STATUS[tile.status].label}</span>
    <details className="monitor-service-details"><summary>Evidence</summary>{tile.evidence?.map(item=><div key={item.id}><strong>{item.workspace?(names.get(item.workspace)??item.workspace):item.id}</strong><p>{item.detail}</p><Evidence value={item}/></div>)??<p>{tile.detail}</p>}</details>
    </div>})}</section>

   {metrics&&t&&j&&q?<div className="monitor-charts">
    {trafficAvailable&&<><MonitorChart title="Traffic" summary={`${count(s!.requests)} requests`} buckets={metrics.buckets} step={metrics.step} format={count}
     series={[chart('ok','Successful',C.blue,t.requests.map((v,i)=>Math.max(0,v-t.client_errors[i]-t.server_errors[i])),'bar'),chart('4xx','Client errors (4xx)',C.warning,t.client_errors,'bar'),chart('5xx','Server errors (5xx)',C.critical,t.server_errors,'bar')]}/>
    <MonitorChart title="Response time" summary={s?.p95!=null?`p95 ${ms(s.p95)}`:undefined} buckets={metrics.buckets} step={metrics.step} format={ms}
     series={[chart('p95','p95',C.blue,t.p95,'line'),chart('p50','p50',C.aqua,t.p50,'line')]}/></>}
    {jobs&&<MonitorChart title="Job outcomes" summary={`${count(s!.completed)} completed`} buckets={metrics.buckets} step={metrics.step} format={count}
     series={[chart('done','Completed',C.blue,j.completed,'bar'),chart('retry','Retried or failed',C.serious,j.failed,'bar'),chart('dead','Discarded',C.critical,j.discarded,'bar')]}/>}
    <MonitorChart title="Queue backlog" summary={backlog?`${count(backlog.pending+backlog.retry)} now`:undefined} buckets={metrics.buckets} step={metrics.step} format={count}
     series={[chart('ready','Ready',C.blue,q.ready,'line'),chart('retrying','Retrying',C.serious,q.retry,'line')]}/>
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
    {problems.length?<div className="monitor-table-scroll"><table><thead><tr><th>Time</th><th>Stage</th><th>Outcome</th><th>Workspace</th><th>Evidence</th></tr></thead><tbody>{problems.slice(0,allEvents?200:20).map(e=><tr key={e.id} className={e.status!=='healthy'?'is-problem':undefined}>
     <td><time dateTime={new Date(e.at*1000).toISOString()}>{new Date(e.at*1000).toLocaleString()}</time></td><td>{STAGES[e.component]??e.component}</td><td title={e.detail}>{e.action==='retry_or_failed'?'Retried or failed':e.action.replaceAll('_',' ')}</td><td>{e.workspace?(names.get(e.workspace)??'Unknown workspace'):'System'}</td><td><details><summary>Details</summary>{e.detail&&<p>{e.detail}</p>}<Evidence value={{...e.evidence,...e}}/></details></td></tr>)}</tbody></table></div>
    :<p className="monitor-empty">{allEvents?'No events recorded yet.':'No retries or failures in the recent event log.'}</p>}
   </section>
  </div>}
 </div>
}
