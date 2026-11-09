import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter, useNavigate } from "react-router-dom"
import { ToastProvider } from "@/components/common"
import { api, request } from "@/lib/api"
import type { Bootstrap, InterviewEvent } from "@/lib/types"
import InterviewsPage from "./interviews"
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{status:vi.fn(),startCheck:vi.fn(),post:vi.fn(),reader:vi.fn()}}))
const bootstrap:Bootstrap={readiness:{model:true,accounts:true,privacy_ack:true,outlook:true},counts:{},taxonomy:[],presets:[],last_run:"",account_count:2}
const event=():InterviewEvent=>({id:1,calendar_uid:"uid",company:"Acme",role:"Engineer",stage:"Technical Interview",status:"Scheduled",display_status:"Scheduled",start_at:new Date(new Date().setHours(23,0,0,0)).toISOString(),end_at:new Date(new Date().setHours(23,45,0,0)).toISOString(),timezone:"UTC",meeting_platform:"Zoom",meeting_url:"https://zoom.us/j/123",location:null,organizer_name:"Recruiter",organizer_email:"recruiter@acme.test",participants:[],notes:null,confidence:.98,needs_review:false,review_reason:null,manual_fields:[],created_at:new Date().toISOString(),updated_at:new Date().toISOString()})
const clients:QueryClient[]=[]
let current=event()
beforeEach(()=>{
  // Keep the fixture inside the default work-week view, including on weekends.
  vi.useFakeTimers({toFake:["Date"]})
  vi.setSystemTime(new Date("2026-10-16T12:00:00Z"))
  current=event()
  vi.mocked(api.status).mockResolvedValue({running:false,completion_id:0,auto:false,next_in:null,message:"",detail:"",ok:true,stage_elapsed:null})
  vi.mocked(api.startCheck).mockResolvedValue({ok:true})
  vi.mocked(api.post).mockResolvedValue({ok:true})
  vi.mocked(request).mockImplementation(async(url)=>{
    if(url==="/api/interviews/scan")return {running:false,processed:0,total:0,found:0,errors:0} as any
    if(url==="/api/interviews/1")return {event:current,sources:[{id:1,account_id:1,message_pk:100,account_label:"work",account_email:"work@example.test",source_subject:"Interview confirmation",source_sender:"recruiter@acme.test",source_received_at:new Date().toISOString()}]} as any
    return {events:[current],accounts:[{id:1,label:"work",email:"work@example.test"},{id:2,label:"personal",email:"me@example.test"}],companies:["Acme"],stages:["Technical Interview","Other"],statuses:["Scheduled","Cancelled","Needs review"]} as any
  })
})
afterEach(()=>{vi.useRealTimers();cleanup();clients.splice(0).forEach(c=>c.clear());vi.clearAllMocks()})
function ChangeInterview() { const navigate=useNavigate(); return <button data-testid="other-interview" onClick={()=>navigate("/interviews?event=2")}>Navigate to another interview</button> }
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client);render(<QueryClientProvider client={client}><MemoryRouter><ChangeInterview/><ToastProvider><InterviewsPage bootstrap={bootstrap}/></ToastProvider></MemoryRouter></QueryClientProvider>)}
it("retries a failed interview list read without starting calendar collection",async()=>{
  const successful=vi.mocked(request).getMockImplementation()!
  let listReads=0
  vi.mocked(request).mockImplementation(async(url,...rest)=>{
    if(url.startsWith("/api/interviews?") && ++listReads===1)throw new Error("list unavailable")
    return successful(url,...rest)
  })
  mount()
  await screen.findByText("list unavailable")
  fireEvent.click(screen.getByRole("button",{name:"Try again"}))
  await screen.findByRole("button",{name:"Month"})
  expect(listReads).toBe(2)
  expect(api.post).not.toHaveBeenCalled()
  expect(screen.queryByText("list unavailable")).toBeNull()
})
