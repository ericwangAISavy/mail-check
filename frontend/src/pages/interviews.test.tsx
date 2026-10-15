import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
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
afterEach(()=>{cleanup();clients.splice(0).forEach(c=>c.clear());vi.clearAllMocks()})
function ChangeInterview() { const navigate=useNavigate(); return <button data-testid="other-interview" onClick={()=>navigate("/interviews?event=2")}>Navigate to another interview</button> }
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client);render(<QueryClientProvider client={client}><MemoryRouter><ChangeInterview/><ToastProvider><InterviewsPage bootstrap={bootstrap}/></ToastProvider></MemoryRouter></QueryClientProvider>)}
it("renders real records in month, week, and day views with date navigation",async()=>{
  mount();await screen.findByRole("button",{name:"Month"})
  expect(screen.getByRole("button",{name:"Work week"}).getAttribute("aria-pressed")).toBe("true")
  fireEvent.click(screen.getByRole("button",{name:"Month"}))
  await waitFor(()=>expect(document.querySelectorAll('.calendar-day').length).toBe(42))
  expect(document.querySelector('.calendar-day .interview-event')).toBeTruthy()
  fireEvent.click(screen.getByRole("button",{name:"Week"}));expect(document.querySelectorAll('.calendar-day').length).toBe(7)
  fireEvent.click(screen.getByRole("button",{name:"Day"}));expect(document.querySelectorAll('.calendar-day').length).toBe(1)
  const day=document.querySelector('.calendar-day')!.getAttribute('aria-label')
  fireEvent.click(screen.getByRole("button",{name:"Next calendar period"}));expect(document.querySelector('.calendar-day')!.getAttribute('aria-label')).not.toBe(day)
  fireEvent.click(screen.getByRole("button",{name:"Today"}));expect(document.querySelector('.calendar-day')!.getAttribute('aria-label')).toBe(day)
})
it("filters real account, company, and status and collects calendar events without a model",async()=>{
  mount();await screen.findByRole("button",{name:"Month"})
  fireEvent.click(screen.getByRole("button",{name:"Filter"}))
  fireEvent.change(screen.getByLabelText("Account"),{target:{value:"personal"}})
  await waitFor(()=>expect(vi.mocked(request).mock.calls.some(([url])=>url.includes("account=personal"))).toBe(true))
  await screen.findByRole("button",{name:"Month"})
  fireEvent.change(screen.getByLabelText("Status"),{target:{value:"Cancelled"}})
  await screen.findByRole("button",{name:"Month"})
  fireEvent.change(screen.getByLabelText("Company"),{target:{value:"Acme"}})
  await waitFor(()=>expect(vi.mocked(request).mock.calls.some(([url])=>url.includes('account=personal')&&url.includes('status=Cancelled')&&url.includes('company=Acme'))).toBe(true))
  fireEvent.click(screen.getByRole("button",{name:"Check now"}));await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/interviews/sync"))
  expect(screen.queryByRole("button",{name:"Import saved invitations"})).toBeNull()
})
it("opens event details and persists only fields explicitly corrected",async()=>{
  mount();await screen.findByRole("button",{name:"Month"})
  fireEvent.click(screen.getAllByRole("button",{name:/Acme, Technical Interview/})[0])
  const dialog=await screen.findByRole("dialog")
  await within(dialog).findByRole("button",{name:"Edit details"})
  expect(within(dialog).getByRole("link",{name:/Open Zoom link/}).getAttribute('href')).toBe('https://zoom.us/j/123')
  expect(within(dialog).queryByRole("button",{name:"View source email"})).toBeNull()
  fireEvent.click(within(dialog).getByRole("button",{name:"Edit details"}))
  fireEvent.change(within(dialog).getByLabelText("Company"),{target:{value:"Correct Company"}})
  fireEvent.click(within(dialog).getByRole("button",{name:"Save corrections"}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/interviews/1',{company:'Correct Company'}))
})
it("shows only dated calendar events without upcoming or review panels",async()=>{
  current={...event(),start_at:null,end_at:null,display_status:'Needs review',needs_review:true}
  mount();await screen.findByRole("button",{name:"Month"})
  expect(document.querySelector('.calendar-day .interview-event')).toBeNull()
  expect(document.querySelector('.interview-agenda')).toBeNull()
  expect(document.querySelector('.interview-summary')).toBeNull()
  expect(screen.queryByText('UPCOMING INTERVIEWS')).toBeNull()
  expect(screen.queryByText('NEEDS REVIEW')).toBeNull()
})
it("sends the editor timezone when correcting a date with missing original timezone",async()=>{
  current={...event(),timezone:null}
  mount();await screen.findByRole("button",{name:"Month"})
  fireEvent.click(screen.getAllByRole("button",{name:/Acme, Technical Interview/})[0])
  const dialog=await screen.findByRole("dialog")
  fireEvent.click(await within(dialog).findByRole("button",{name:"Edit details"}))
  const start=within(dialog).getByLabelText("Start date/time") as HTMLInputElement
  const end=within(dialog).getByLabelText("End date/time") as HTMLInputElement
  fireEvent.change(start,{target:{value:"2026-10-20T10:00"}})
  fireEvent.change(end,{target:{value:"2026-10-20T11:00"}})
  const zone=(within(dialog).getByLabelText("Timezone") as HTMLInputElement).value
  fireEvent.click(within(dialog).getByRole("button",{name:"Save corrections"}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/interviews/1',{start_at:'2026-10-20T10:00',end_at:'2026-10-20T11:00',timezone:zone}))
})
it("resets editing and drafts when navigation selects another event",async()=>{
  const original=vi.mocked(request).getMockImplementation()!
  vi.mocked(request).mockImplementation(async(url,...rest)=>url==='/api/interviews/2'?{event:{...event(),id:2,company:'Second Company'},sources:[]} as any:original(url,...rest))
  mount();await screen.findByRole("button",{name:"Month"})
  fireEvent.click(screen.getAllByRole("button",{name:/Acme, Technical Interview/})[0])
  let dialog=await screen.findByRole("dialog")
  fireEvent.click(await within(dialog).findByRole("button",{name:"Edit details"}))
  fireEvent.change(within(dialog).getByLabelText("Company"),{target:{value:'Wrong draft from previous event'}})
  fireEvent.click(screen.getByTestId('other-interview'))
  dialog=await screen.findByRole('dialog')
  await within(dialog).findByRole('heading',{name:'Second Company'})
  fireEvent.click(await within(dialog).findByRole('button',{name:'Edit details'}))
  expect((within(dialog).getByLabelText('Company') as HTMLInputElement).value).toBe('Second Company')
})
it("does not protect an unchanged end time when only the start is corrected",async()=>{
  mount();await screen.findByRole("button",{name:"Month"})
  fireEvent.click(screen.getAllByRole("button",{name:/Acme, Technical Interview/})[0])
  const dialog=await screen.findByRole("dialog")
  fireEvent.click(await within(dialog).findByRole("button",{name:"Edit details"}))
  const zone=(within(dialog).getByLabelText("Timezone") as HTMLInputElement).value
  fireEvent.change(within(dialog).getByLabelText("Start date/time"),{target:{value:"2026-10-20T10:00"}})
  fireEvent.click(within(dialog).getByRole("button",{name:"Save corrections"}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/interviews/1',{start_at:'2026-10-20T10:00',timezone:zone}))
})

it('opens native application lookup with company, role and the available profile',async()=>{
 mount();await screen.findByRole('button',{name:'Month'})
 fireEvent.click(screen.getAllByRole('button',{name:/Acme, Technical Interview/})[0])
 const link=await screen.findByRole('link',{name:/Find application/})
 expect(link.getAttribute('href')).toBe('/sourcing?q=Acme+Engineer&account=1')
})
