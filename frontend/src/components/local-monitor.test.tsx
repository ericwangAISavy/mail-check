import {afterEach,expect,it,vi} from "vitest"
import {cleanup,render,screen,within} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import LocalMonitor from "./local-monitor"
import {version} from '../../package.json'

vi.mock("@/pages/system-monitoring",()=>({MonitoringView:()=> <div>Recorded charts</div>}))
const clients:QueryClient[]=[]
afterEach(()=>{cleanup();clients.forEach(client=>client.clear());clients.length=0;vi.unstubAllGlobals()})
function mount(origin:string,checked_at=Date.now()/1000,failed=false,failed_services:string[]=[],problem_services:{id:string;status:string;name?:string;workspace_name?:string;reason?:string}[]=[],availableVersion=version){
 vi.stubGlobal("fetch",vi.fn(async(url:string)=>{
  if(failed)throw new Error("Connection refused")
  if(url.startsWith('/assets/build-info.json'))return new Response(JSON.stringify({version:availableVersion}),{headers:{'content-type':'application/json'}})
  return new Response(JSON.stringify({origin,checked_at,snapshot_stale:origin!=="ready",failed_services,problem_services,logs:[]}),{headers:{"content-type":"application/json"}})
 }))
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><LocalMonitor/></QueryClientProvider>)
}
it("shows a prominent outage alert and browser tab warning while keeping recorded charts",async()=>{
 mount("unavailable")
 const alert=await screen.findByRole("alert")
 expect(within(alert).getByText("OfferPath is down")).toBeTruthy()
 expect(alert.classList.contains("is-critical")).toBe(true)
 expect(document.title).toContain("ALERT")
 expect(screen.getByText("Recorded charts")).toBeTruthy()
})
it('identifies an older open monitoring UI and offers to reload the installed update',async()=>{
 mount('ready',Date.now()/1000,false,[],[],'99.0.0')
 expect(await screen.findByText('Monitoring update available')).toBeTruthy()
 expect(screen.getByRole('button',{name:'Reload monitoring'})).toBeTruthy()
 expect(screen.getByText(`UI v${version}`)).toBeTruthy()
 expect(screen.getByText(/v99.0.0 is installed/)).toBeTruthy()
 expect(screen.queryByRole('alert')).toBeNull()
})
it('does not call an older metadata file a newer monitoring update',async()=>{
 mount('ready',Date.now()/1000,false,[],[],'1.0.0')
 await screen.findByText('Local gateway is available')
 expect(screen.queryByText('Monitoring update available')).toBeNull()
})
it("warns about degraded and unknown evidence while the gateway is alive",async()=>{
 mount("ready",Date.now()/1000,false,[],[{id:"shared-job-model-0",status:"degraded"}])
 const alert=await screen.findByRole("alert")
 expect(within(alert).getByText("Service health needs attention")).toBeTruthy()
 expect(alert.classList.contains("is-warning")).toBe(true)
})
it('names the affected workspace and missing database reason in the warning',async()=>{
 mount('ready',Date.now()/1000,false,[],[{id:'tenant:database',name:'Workspace database',workspace_name:'OrionStar',status:'unknown',reason:'database_missing'}])
 const alert=await screen.findByRole('alert')
 expect(within(alert).getByText(/OrionStar: Workspace database \(unknown: database missing\)/)).toBeTruthy()
})
it("warns when a ready response contains an expired health check",async()=>{
 mount("ready",Date.now()/1000-60)
 expect(within(await screen.findByRole("alert")).getByText("Health checks are not updating")).toBeTruthy()
})
it("alerts when the monitoring connection itself is lost",async()=>{
 mount("ready",Date.now()/1000,true)
 expect(within(await screen.findByRole("alert")).getByText("Monitoring connection lost")).toBeTruthy()
})
it("identifies a failed worker even when the gateway still responds",async()=>{
 mount("ready",Date.now()/1000,false,["shared-job-model-0"])
 const alert=await screen.findByRole("alert")
 expect(within(alert).getByText("Service failure detected")).toBeTruthy()
 expect(within(alert).getByText(/shared-job-model-0/)).toBeTruthy()
})
