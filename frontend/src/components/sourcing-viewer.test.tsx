import {afterEach,beforeEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import SourcingViewer from "./sourcing-viewer"
import {api,request} from "@/lib/api"
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{post:vi.fn()},serverNow:()=>Date.now()}))
const cell=(value:string)=>({value,display:value,style:{},formula:false,link:"",version:0})
const snapshot={id:7,title:"Work",revision:"1",structure_revision:0,refreshed_at:0,columns:[{id:"c",title:"Company",kind:"company",width:200},{id:"l",title:"Job link",kind:"link",width:400}],row_ids:["h","a","b"],row_dates:[null,"2026-10-20","2026-10-21"],rows:[[cell("Company"),cell("Job link")],[cell("Acme"),cell("https://jobs.test/1")],[cell("Beta"),cell("https://jobs.test/2")]],properties:{gridProperties:{rowCount:3,columnCount:2}}}
let client:QueryClient
const copy=vi.fn().mockResolvedValue(undefined)
beforeEach(()=>{vi.mocked(request).mockResolvedValue(snapshot);Object.defineProperty(navigator,"clipboard",{configurable:true,value:{writeText:copy}});client=new QueryClient({defaultOptions:{queries:{retry:false}}})})
afterEach(()=>{cleanup();client.clear();vi.clearAllMocks()})
function mount(){render(<QueryClientProvider client={client}><SourcingViewer tab={{id:7,title:"Work",account_id:1,header_row:1,refreshed_at:0}} initialDay="2026-10-20"/></QueryClientProvider>)}
it("views saved dates and copies rows without edit, refresh or write actions",async()=>{
 mount();await screen.findByText("Acme")
 expect(screen.queryByText("Beta")).toBeNull()
 fireEvent.click(screen.getByRole("button",{name:"Copy these jobs"}))
 await waitFor(()=>expect(copy).toHaveBeenCalledWith("Company\tJob link\nAcme\thttps://jobs.test/1"))
 fireEvent.change(screen.getByLabelText("Saved job days"),{target:{value:"2026-10-21"}})
 await screen.findByText("Beta")
 expect(screen.queryByText("Acme")).toBeNull()
 expect(screen.queryByRole("button",{name:/Refresh|Assign date|Check applications|Rows|Import|Save|Delete/})).toBeNull()
 expect(api.post).not.toHaveBeenCalled()
 expect(request).toHaveBeenCalledTimes(1)
})

it("marks an opened link immediately and restores the same job after returning to a reordered sheet",async()=>{
 const opened:string[]=[]
 const createdAt=Date.now()/1000
 let finishSave:()=>void=()=>{}
 vi.mocked(request).mockImplementation(async(_,init)=>{
  if(init?.method==="POST"){
   await new Promise<void>(resolve=>{finishSave=resolve})
   opened.push(JSON.parse(String(init.body)).row_id)
   return {ok:true} as never
  }
  return (opened.length?{
   ...snapshot,row_ids:["h","b","a"],row_dates:[null,"2026-10-20","2026-10-20"],row_created:[null,createdAt+1,createdAt],
   rows:[snapshot.rows[0],snapshot.rows[2],snapshot.rows[1]],opened_row_ids:opened,
  }:{...snapshot,row_created:[null,createdAt,createdAt+1]}) as never
 })
 mount()
 const link=await screen.findByRole("link",{name:"https://jobs.test/1"})
 expect(link.getAttribute("target")).toBe("_blank")
 fireEvent.click(link)
 expect(link.closest("tr")?.getAttribute("data-opened")).toBe("true")
 expect(screen.getByRole("button",{name:/Completed 0/})).toBeTruthy()
 expect(request).toHaveBeenCalledWith("/api/sourcing/tabs/7/opened",expect.objectContaining({
  method:"POST",body:JSON.stringify({row_id:"a",job_created_at:createdAt}),keepalive:true,
 }))
 finishSave()
 await waitFor(()=>expect(opened).toEqual(["a"]))
 cleanup()
 client.clear()
 mount()
 expect((await screen.findByText("Acme")).closest("tr")?.getAttribute("data-opened")).toBe("true")
 expect(screen.getByText("Beta").closest("tr")?.hasAttribute("data-opened")).toBe(false)
})

vi.mock("@/components/auth",()=>({useAuth:()=>({role:"bidder"})}))
vi.mock("@/components/sourcing-editor",()=>({default:()=>{throw new Error("Bidder must never mount the editor")}}))
it("does not expose a search refresh button to bidders",async()=>{
 const {MemoryRouter}=await import("react-router-dom")
 const {default:SourcingPage}=await import("@/pages/sourcing")
 vi.mocked(request).mockImplementation(async(url)=>url==="/api/sourcing"?{books:[]}: {results:[]} as never)
 render(<QueryClientProvider client={client}><MemoryRouter initialEntries={["/sourcing?q=Acme"]}><SourcingPage/></MemoryRouter></QueryClientProvider>)
 await screen.findByRole("heading",{name:/Applications matching/})
 expect(screen.queryByRole("button",{name:"Refresh results"})).toBeNull()
 expect(api.post).not.toHaveBeenCalled()
})

it("shows a bidder every unfinished job across days, marks the ones expiring soon and keeps expired ones in history",async()=>{
 const now=Date.now(),hour=3600_000
 const queued={...snapshot,row_ids:["h","a","b","c"],row_dates:[null,"2026-10-01","2026-10-20","2026-10-21"],
  row_created:[null,(now-6*24*hour)/1000,(now-hour)/1000,(now-8*24*hour)/1000],
  rows:[[cell("Company"),cell("Job link")],[cell("Aging"),cell("https://jobs.test/1")],[cell("Fresh"),cell("https://jobs.test/2")],[cell("Lapsed"),cell("https://jobs.test/3")]]}
 vi.mocked(request).mockResolvedValue(queued)
 render(<QueryClientProvider client={client}><SourcingViewer tab={{id:7,title:"Work",account_id:1,header_row:1,refreshed_at:0}}/></QueryClientProvider>)
 await screen.findByText("Aging")
 expect(screen.getByText("Fresh")).toBeTruthy()
 expect(screen.queryByText("Lapsed")).toBeNull()
 expect(screen.getAllByLabelText("Expiring soon").length).toBeGreaterThan(0)
 expect(screen.getByRole("button",{name:/To do 2/}).getAttribute("aria-pressed")).toBe("true")
 fireEvent.click(screen.getByRole("button",{name:/Expired 1/}))
 await screen.findByText("Lapsed")
 expect(screen.queryByText("Aging")).toBeNull()
 expect(api.post).not.toHaveBeenCalled()
})

it("sorts the bidder table by Added while keeping the saved clipboard fields", async () => {
 const now = Date.now() / 1000
 const data = {...snapshot, row_dates: [null, "2026-10-20", "2026-10-20"], row_created: [null, now - 7200, now - 3600]}
 vi.mocked(request).mockResolvedValue(data)
 mount()
 const header = await screen.findByRole("columnheader", {name: "Added"})
 const sort = screen.getByRole("button", {name: "Added"})
 fireEvent.click(sort)
 expect(header.getAttribute("aria-sort")).toBe("ascending")
 fireEvent.click(sort)
 expect(header.getAttribute("aria-sort")).toBe("descending")
 const links = screen.getAllByRole("link").map(link => link.getAttribute("href"))
 expect(links).toEqual(["https://jobs.test/2", "https://jobs.test/1"])
 fireEvent.click(screen.getByRole("button", {name: "Copy these jobs"}))
 await waitFor(() => expect(copy).toHaveBeenCalledWith("Company\tJob link\nBeta\thttps://jobs.test/2\nAcme\thttps://jobs.test/1"))
})
