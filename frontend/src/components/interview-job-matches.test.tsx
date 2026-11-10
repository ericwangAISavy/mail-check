import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { request } from "@/lib/api"
import { InterviewJobMatches } from "./interview-job-matches"
import type { InterviewJobMatch } from "@/lib/types"
vi.mock("@/lib/api",()=>({request:vi.fn()}))
const fetchMatches=vi.mocked(request)
const match=(row_id:number,overrides:Partial<InterviewJobMatch>={}):InterviewJobMatch=>({row_id:`job-row-${row_id}`,tab_id:1,account_id:1,account_label:"Work account",bidder_id:1,bidder_name:"Alex",company:"Acme",role:"Engineer",link:`https://jobs.example/${row_id}`,applied:true,application_date:"2026-10-15",work_date:null,archived:false,confidence:"strong",reasons:["Company name matches"],...overrides})
function mount(){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><InterviewJobMatches id={42}/></QueryClientProvider>)}
afterEach(()=>{cleanup();vi.resetAllMocks()})
it("shows multiple job links and historical bidders",async()=>{
 fetchMatches.mockResolvedValue({matches:[match(1),match(2,{bidder_name:"Sam",archived:true,confidence:"possible"})],total:2,next_cursor:null})
 mount();expect(await screen.findByRole("link",{name:"https://jobs.example/1"})).toBeTruthy()
 expect(screen.getByRole("link",{name:"https://jobs.example/2"})).toBeTruthy()
 expect(screen.getByText("Applied by Alex")).toBeTruthy();expect(screen.getByText("Applied by Sam")).toBeTruthy()
 expect(screen.getAllByText("Work account")).toHaveLength(2);expect(screen.getByText("Archived job")).toBeTruthy()
 expect(screen.getByText("Strong match")).toBeTruthy();expect(screen.getByText("Possible match")).toBeTruthy()
})
it("explains saved rows and never activates unsafe links",async()=>{
 fetchMatches.mockResolvedValue({matches:[match(1,{link:"javascript:alert(1)",applied:false,application_date:null,work_date:"2026-10-14"}),match(2,{link:"data:text/html,unsafe",application_date:null})],total:2,next_cursor:null})
 mount();expect(await screen.findByText("Saved by Alex")).toBeTruthy();expect(screen.getByText("Application not verified")).toBeTruthy()
 expect(screen.getByText("Source date: 2026-10-14")).toBeTruthy();expect(screen.getByText("Recorded application date unknown")).toBeTruthy();expect(screen.queryAllByRole("link")).toHaveLength(0)
})
it("shows loading and an empty result",async()=>{
 let finish!:(value:unknown)=>void;fetchMatches.mockImplementation(()=>new Promise(resolve=>{finish=resolve}) as ReturnType<typeof request>)
 mount();expect(screen.getByRole("status").textContent).toContain("Loading job matches")
 finish({matches:[],total:0,next_cursor:null});expect(await screen.findByText("No possible job matches found.")).toBeTruthy()
})
it("retries a failed initial request",async()=>{
 fetchMatches.mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce({matches:[match(1)],total:1,next_cursor:null})
 mount();expect((await screen.findByRole("alert")).textContent).toContain("Could not load job matches")
 fireEvent.click(screen.getByRole("button",{name:"Retry job matches"}));expect(await screen.findByRole("link")).toBeTruthy()
})
it("preserves matches after pagination failure and retries the cursor",async()=>{
 fetchMatches.mockResolvedValueOnce({matches:[match(1)],total:2,next_cursor:"next & more"}).mockRejectedValueOnce(new Error("Offline")).mockResolvedValueOnce({matches:[match(1),match(2)],total:2,next_cursor:null})
 mount();await screen.findByRole("link");fireEvent.click(screen.getByRole("button",{name:"Load more job matches"}))
 expect((await screen.findByRole("alert")).textContent).toContain("Could not load more job matches");expect(screen.getAllByRole("link")).toHaveLength(1)
 fireEvent.click(screen.getByRole("button",{name:"Retry loading more job matches"}));await waitFor(()=>expect(screen.getAllByRole("link")).toHaveLength(2))
 expect(fetchMatches.mock.calls[2][0]).toBe('/api/interviews/42/job-matches?limit=25&cursor=next+%26+more')
})
