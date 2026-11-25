import {act, cleanup, fireEvent, render, screen, waitFor, within} from '@testing-library/react'
import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {afterEach, beforeAll, expect, it, vi} from 'vitest'
import SystemMonitoring, {MonitoringView} from './system-monitoring'
let owner=true
vi.mock('@/components/auth',()=>({useAuth:()=>({session:{is_owner:owner}})}))
beforeAll(()=>{vi.stubGlobal('ResizeObserver',class{constructor(private cb:ResizeObserverCallback){}observe(){this.cb([{contentRect:{width:600}} as ResizeObserverEntry],this as unknown as ResizeObserver)}disconnect(){}unobserve(){}})})
afterEach(()=>{cleanup();vi.unstubAllGlobals();owner=true;vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}unobserve(){}})})
const now=Date.now()/1000
const snapshot={checked_at:now,components:[{id:'gateway',name:'Gateway',status:'healthy',detail:'Request served.'},{id:'redis',name:'Redis / event broker',status:'disabled',detail:'Not configured.'}],workspaces:[{id:'legacy',name:'Original workspace',enabled:true,accounts:[],queues:[],outbox:null}],
 events:[{id:'legacy:1',at:now-5,workspace:'legacy',component:'mail',action:'queued',status:'healthy'},{id:'legacy:2',at:now,workspace:'legacy',component:'classify',action:'retry_or_failed',status:'degraded'}],event_retention:1000}
const zeros=(n:number)=>Array(n).fill(0)
const buckets=Array.from({length:60},(_,i)=>Math.floor(now/60)*60-59*60+i*60)
const metrics={range:'1h',step:60,buckets,generated_at:now,
 traffic:{requests:[...zeros(59),120],client_errors:[...zeros(59),6],server_errors:[...zeros(59),3],throttled:zeros(60),p50:[...Array(59).fill(null),40],p95:[...Array(59).fill(null),480]},
 jobs:{completed:[...zeros(59),18],failed:[...zeros(59),2],discarded:zeros(60),queued:zeros(60),p95:Array(60).fill(null)},
 queues:{ready:[...Array(59).fill(null),7],retry:[...Array(59).fill(null),1],dead:[...Array(59).fill(null),0]},
 summary:{requests:120,client_errors:6,server_errors:3,error_rate:.025,p50:40,p95:480,completed:18,failed:2,discarded:0,failure_rate:.1},
 stages:[{stage:'mail',queued:0,started:0,completed:18,retry_or_failed:2,discarded:0,failure_rate:.1,duration_p50:1.5,duration_p95:4.2}]}
const json=(body:unknown)=>new Response(JSON.stringify(body),{headers:{'Content-Type':'application/json'}})
function serve(snap:unknown=snapshot,series:unknown=metrics){return vi.fn().mockImplementation((url:string)=>Promise.resolve(json(String(url).includes('/metrics')?series:snap)))}
function mount(){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><SystemMonitoring/></QueryClientProvider>)}

it('counts busy workers in their pools even when progress evidence identifies a workspace',async()=>{
 vi.stubGlobal('fetch',serve({...snapshot,components:[snapshot.components[0],
  {id:'shared-job-collection-0',name:'Collector 0',workspace:'legacy',status:'healthy',detail:'Collecting',kind:'mail'},
  {id:'shared-job-collection-1',name:'Collector 1',status:'healthy',detail:'Polling'},
  {id:'shared-job-model-0',name:'Model 0',workspace:'legacy',status:'healthy',detail:'Classifying'},
  {id:'subscriptions:shared-job-collection-0',name:'Microsoft subscriptions',workspace:'legacy',status:'degraded',detail:'Polling continues',reason:'http_403'}]}))
 mount()
 const health=await screen.findByRole('region',{name:'Service health'})
 const pool=within(health).getByText('Collection pool').closest('.monitor-service')!
 expect(pool.textContent).toContain('2/2 ready')
 expect(within(health).getByText('Model worker').closest('.monitor-service')!.textContent).toContain('1/1 ready')
 expect(within(health).getByText('Microsoft subscriptions')).toBeTruthy()
})

it('shows earlier coverage gaps as history rather than an active red warning',async()=>{
 vi.stubGlobal('fetch',serve(snapshot,{...metrics,jobs_current_available:true,jobs_coverage_incomplete:true}))
 mount()
 const note=await screen.findByText('Earlier monitoring gaps')
 expect(note.closest('details')).toBeTruthy()
 expect(screen.queryByText(/Job observation coverage is incomplete/)).toBeNull()
 expect(screen.queryByText(/Job monitoring is not fully reporting/)).toBeNull()
})

it('keeps a visible warning when current job monitoring is not reporting',async()=>{
 vi.stubGlobal('fetch',serve(snapshot,{...metrics,jobs_current_available:false,jobs_coverage_incomplete:true}))
 mount()
 const warning=await screen.findByText(/Job monitoring is not fully reporting/)
 expect(warning.getAttribute('role')).toBe('status')
 expect(warning.classList.contains('inline-error')).toBe(false)
 expect(screen.queryByText('Earlier monitoring gaps')).toBeNull()
})

it('keeps unknown publication and database coverage from becoming green and exposes evidence',async()=>{
 vi.stubGlobal('fetch',serve({...snapshot,architecture:'shared',workspaces:[
  {...snapshot.workspaces[0],outbox:0},{...snapshot.workspaces[0],id:'other',name:'Other',outbox:null}],
  components:[snapshot.components[0],
   {id:'legacy:database',workspace:'legacy',name:'Database',status:'healthy',detail:'Read only',scope:'sqlite_read'},
   {id:'other:database',workspace:'other',name:'Database',status:'unknown',detail:'Missing evidence',reason:'database_missing'},
   {id:'shared-job-model-0',name:'Model 0',status:'degraded',detail:'Slow operation',reason:'operation_slow',pid:123,job_id:'job-123'}]}))
 mount()
 const health=await screen.findByRole('region',{name:'Service health'})
 const publication=within(health).getByText('Publication').closest('.monitor-service')!
 expect(publication.classList.contains('is-healthy')).toBe(false)
 expect(publication.textContent).toContain('unknown')
 const databases=within(health).getByText('Databases').closest('.monitor-service')!
 expect(databases.classList.contains('is-healthy')).toBe(false)
 expect(within(health).getAllByText('Evidence').length).toBeGreaterThan(0)
 expect(within(health).getAllByText('operation_slow').length).toBeGreaterThan(0)
})

it('does not present unavailable independent traffic measurements as zero successful requests',async()=>{
 vi.stubGlobal('fetch',serve(snapshot,{...metrics,traffic_available:false,source:'independent'}))
 mount()
 await screen.findByText(/Traffic measurements are unavailable/)
 expect(screen.queryByRole('figure',{name:'Traffic'})).toBeNull()
 expect(screen.queryByRole('figure',{name:'Response time'})).toBeNull()
 expect(screen.getByRole('figure',{name:'Job outcomes'})).toBeTruthy()
})

it('renders identical charts independently of the application sign-in context',async()=>{
 owner=false
 vi.stubGlobal('fetch',serve({...snapshot,observer_origin:'ready',observer_stale:true}))
 render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><MonitoringView owner independent/></QueryClientProvider>)
 for(const name of ['Traffic','Response time','Job outcomes','Queue backlog'])expect(await screen.findByRole('figure',{name})).toBeTruthy()
 expect(screen.getByText('Last known data')).toBeTruthy()
 expect(screen.queryByText('Owner access required')).toBeNull()
})

it('shows key metrics, graphs and recent problems instead of explanations',async()=>{
 vi.stubGlobal('fetch',serve())
 mount()
 const stats=await screen.findByRole('region',{name:'Key metrics'})
 await within(stats).findByText('120')
 expect(within(stats).getByText('2.5%')).toBeTruthy()
 expect(within(stats).getByText('480 ms')).toBeTruthy()
 expect(within(stats).getByText('18')).toBeTruthy()
 expect(within(stats).getByText('10% of finished jobs')).toBeTruthy()
 for(const name of ['Traffic','Response time','Job outcomes','Queue backlog'])expect(screen.getByRole('figure',{name})).toBeTruthy()
 expect(screen.getByText('Server errors (5xx)')).toBeTruthy()
 const events=screen.getByRole('region',{name:'Recent problems'})
 expect(within(events).getByText('Retried or failed')).toBeTruthy()
 expect(within(events).queryByText('queued')).toBeNull()
 fireEvent.click(screen.getByLabelText('Show all events'))
 expect(within(screen.getByRole('region',{name:'Recent events'})).getByText('queued')).toBeTruthy()
 expect(screen.queryByText(/Telemetry is best effort/)).toBeNull()
})

it('reads chart values from the crosshair, the keyboard and the table view',async()=>{
 vi.stubGlobal('fetch',serve())
 mount()
 const traffic=await screen.findByRole('figure',{name:'Traffic'})
 const plot=within(traffic).getByRole('group',{name:/Traffic/})
 fireEvent.keyDown(plot,{key:'ArrowRight'})
 const tip=within(traffic).getByRole('status')
 expect(within(tip).getByText('111')).toBeTruthy()          // successful = 120 - 6 - 3
 expect(within(tip).getByText('Client errors (4xx)')).toBeTruthy()
 fireEvent.click(within(traffic).getByRole('button',{name:'Show table: Traffic'}))
 const table=within(traffic).getByRole('table')
 expect(within(table).getAllByRole('row')).toHaveLength(2)  // header + the one active minute
})

it('shows service health with rolled-up pools and stage table with live queues',async()=>{
 const shared={...snapshot,architecture:'shared',process_counts:{api:2,collection:1,model:1},
  global_queues:[{kind:'mail',pending:4,retry:2,dead:1},{kind:'classify',pending:7,retry:3,dead:2}],
  components:[snapshot.components[0],
   {id:'shared-api-0',name:'Shared api process · 0',status:'healthy',detail:'Ready.'},
   {id:'shared-api-1',name:'Shared api process · 1',status:'unavailable',detail:'Stopped.'},
   {id:'legacy:database',workspace:'legacy',name:'Workspace database',status:'healthy',detail:'Private admin database detail.'}]}
 vi.stubGlobal('fetch',serve(shared))
 mount()
 const health=await screen.findByRole('region',{name:'Service health'})
 expect(within(health).getByText('API pool')).toBeTruthy()
 expect(within(health).getByText('1/2 ready')).toBeTruthy()
 expect(within(health).getByText('1/1 readable')).toBeTruthy()
 expect(screen.queryByText('Shared api process · 0')).toBeNull()
 expect(screen.getByText('Private admin database detail.').closest('details')).toBeTruthy()
 const backlog=screen.getByRole('region',{name:'Queue backlog'})
 expect(within(backlog).getByText('16')).toBeTruthy()
 expect(within(backlog).getByText('11 ready · 5 retrying')).toBeTruthy()
 const dead=screen.getByRole('region',{name:'Dead-lettered jobs'})
 expect(within(dead).getByText('3')).toBeTruthy()
 expect(within(dead).getByText('Retained failed jobs')).toBeTruthy()
 const stages=await screen.findByRole('region',{name:'Processing stages'})
 expect(within(stages).getByText('Mail collection')).toBeTruthy()
 expect(within(stages).getByText('Classification')).toBeTruthy()
 expect(within(stages).getByText('4.2 s')).toBeTruthy()
})

it('does not invent queue counts when none are reported',async()=>{
 vi.stubGlobal('fetch',serve())
 mount()
 const backlog=await screen.findByRole('region',{name:'Queue backlog'})
 expect(within(backlog).getByText('Queue metrics unavailable.')).toBeTruthy()
 expect(within(backlog).queryByText('0')).toBeNull()
})

it('switches the time range for every graph',async()=>{
 const fetch=serve();vi.stubGlobal('fetch',fetch)
 mount()
 await screen.findByRole('figure',{name:'Traffic'})
 fireEvent.click(screen.getByRole('button',{name:'24 hours'}))
 await waitFor(()=>expect(fetch.mock.calls.some(([url])=>String(url).includes('range=24h'))).toBe(true))
 expect(screen.getByRole('button',{name:'24 hours'}).getAttribute('aria-pressed')).toBe('true')
})

it('does not fetch monitoring data for a nonowner',()=>{
 owner=false;const fetch=vi.fn();vi.stubGlobal('fetch',fetch);mount()
 expect(screen.getByText('Owner access required')).toBeTruthy();expect(fetch).not.toHaveBeenCalled()
})

it('shows unavailable feedback when a snapshot fails',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));mount()
 expect((await screen.findAllByRole('alert')).length).toBeGreaterThan(0)
})

it('freezes the displayed snapshot when an in-flight refresh finishes after pause',async()=>{
 let finish!:(r:Response)=>void
 let calls=0
 vi.stubGlobal('fetch',vi.fn().mockImplementation((url:string)=>{
  if(String(url).includes('/metrics'))return Promise.resolve(json(metrics))
  calls++
  return calls===1?Promise.resolve(json(snapshot)):new Promise<Response>(resolve=>{finish=resolve})
 }))
 mount();await screen.findByText('Gateway')
 await waitFor(()=>expect(screen.getByRole('button',{name:'Refresh monitoring'})).toHaveProperty('disabled',false))
 fireEvent.click(screen.getByRole('button',{name:'Refresh monitoring'}))
 await waitFor(()=>expect(calls).toBe(2))
 fireEvent.click(screen.getByRole('button',{name:'Pause live updates'}))
 expect(screen.getByRole('button',{name:'Resume live updates'})).toBeTruthy()
 expect(screen.getByRole('button',{name:'24 hours'})).toHaveProperty('disabled',true)
 await act(async()=>{finish(json({...snapshot,components:[{id:'changed',name:'Changed gateway',status:'healthy',detail:'Updated.'}]}));await new Promise(resolve=>setTimeout(resolve,30))})
 expect(screen.queryByText('Changed gateway')).toBeNull()
 expect(screen.getByText('Gateway')).toBeTruthy()
})
