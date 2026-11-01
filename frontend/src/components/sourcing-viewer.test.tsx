import {afterEach,beforeEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import SourcingViewer from "./sourcing-viewer"
import {api,request} from "@/lib/api"
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{post:vi.fn()}}))
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
 fireEvent.click(screen.getByRole("button",{name:"Copy jobs for this date"}))
 await waitFor(()=>expect(copy).toHaveBeenCalledWith("Company\tJob link\nAcme\thttps://jobs.test/1"))
 fireEvent.change(screen.getByLabelText("Saved job days"),{target:{value:"2026-10-21"}})
 await screen.findByText("Beta")
 expect(screen.queryByText("Acme")).toBeNull()
 expect(screen.queryByRole("button",{name:/Refresh|Assign date|Check applications|Rows|Import|Save|Delete/})).toBeNull()
 expect(api.post).not.toHaveBeenCalled()
 expect(request).toHaveBeenCalledTimes(1)
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
