import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react'
import {QueryClient, QueryClientProvider} from '@tanstack/react-query'
import {afterEach, expect, it, vi} from 'vitest'
import SystemMonitoring from './system-monitoring'
let owner=true
vi.mock('@/components/auth',()=>({useAuth:()=>({session:{is_owner:owner}})}))
afterEach(()=>{cleanup();vi.unstubAllGlobals();owner=true})
const snapshot={checked_at:Date.now()/1000,components:[{id:'gateway',name:'Gateway',status:'healthy',detail:'Request served.'},{id:'redis',name:'Redis / event broker',status:'disabled',detail:'Not configured.'}],workspaces:[{id:'legacy',name:'Original workspace',enabled:true,accounts:[],queues:[],outbox:null}],events:[{id:'legacy:1-0',at:Date.now()/1000,workspace:'legacy',component:'mail',action:'queued',status:'healthy'}],event_retention:1000}
function mount(){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><SystemMonitoring/></QueryClientProvider>)}
it('shows component evidence and event flow with pause and filtering',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(snapshot),{headers:{'Content-Type':'application/json'}})))
 mount()
 expect(await screen.findByText('Gateway')).toBeTruthy()
 expect(screen.getByText('Not configured.')).toBeTruthy()
 expect(screen.getByText('queued')).toBeTruthy()
 fireEvent.click(screen.getByRole('button',{name:'Pause live updates'}))
 expect(screen.getByRole('button',{name:'Resume live updates'})).toBeTruthy()
 fireEvent.change(screen.getByLabelText('Event component'),{target:{value:'calendar'}})
 expect(screen.queryByText('queued')).toBeNull()
 expect(screen.getByText(/No events match/)).toBeTruthy()
})
it('does not fetch monitoring data for a nonowner',()=>{
 owner=false;const fetch=vi.fn();vi.stubGlobal('fetch',fetch);mount()
 expect(screen.getByText('Owner access required')).toBeTruthy();expect(fetch).not.toHaveBeenCalled()
})
it('shows unavailable feedback when a snapshot fails',async()=>{
 vi.stubGlobal('fetch',vi.fn().mockRejectedValue(new Error('offline')));mount()
 expect(await screen.findByRole('alert')).toBeTruthy()
})
it('freezes the displayed snapshot when an in-flight refresh finishes after pause',async()=>{
 let finish!:(r:Response)=>void
 let calls=0
 vi.stubGlobal('fetch',vi.fn().mockImplementation(()=>{
  calls++
  return calls===1?Promise.resolve(new Response(JSON.stringify(snapshot),{headers:{"Content-Type":"application/json"}})):new Promise<Response>(resolve=>{finish=resolve})
 }))
 mount();await screen.findByText('Gateway')
 await waitFor(()=>expect(screen.getByRole('button',{name:'Refresh monitoring'})).toHaveProperty('disabled',false))
 fireEvent.click(screen.getByRole('button',{name:'Refresh monitoring'}))
 await waitFor(()=>expect(calls).toBe(2))
 fireEvent.click(screen.getByRole('button',{name:'Pause live updates'}))
 await act(async()=>{finish(new Response(JSON.stringify({...snapshot,components:[{id:'changed',name:'Changed gateway',status:'healthy',detail:'Updated.'}]}),{headers:{"Content-Type":"application/json"}}));await new Promise(resolve=>setTimeout(resolve,30))})
 expect(screen.queryByText('Changed gateway')).toBeNull()
 expect(screen.getByText('Gateway')).toBeTruthy()
})
it('shows shared process and data flow with global queues',async()=>{
 const shared={...snapshot,architecture:'shared',process_counts:{api:2,collection:2,model:1},global_queues:[{kind:'mail',pending:3,retry:1,dead:0}]}
 vi.stubGlobal('fetch',vi.fn().mockResolvedValue(new Response(JSON.stringify(shared),{headers:{'Content-Type':'application/json'}})))
 mount()
 expect(await screen.findByRole('region',{name:'Shared process and data flow'})).toBeTruthy()
 expect(screen.getByText('Shared API pool')).toBeTruthy()
 expect(screen.getByText('Collection pool')).toBeTruthy()
 expect(screen.getByText('Model process')).toBeTruthy()
 expect(screen.getByText('Workspace databases')).toBeTruthy()
 expect(screen.getByText('RabbitMQ change exchange')).toBeTruthy()
 expect(screen.getByText('Global RabbitMQ queues')).toBeTruthy()
 expect(screen.getByText(/Ready messages exclude in-flight/)).toBeTruthy()
})
