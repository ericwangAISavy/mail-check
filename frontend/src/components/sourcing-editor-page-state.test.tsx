import { afterEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { PageStateProvider } from "@/lib/page-state"
import SourcingEditor from "./sourcing-editor"
vi.mock("@/lib/api",()=>({request:vi.fn(async()=>({id:1,title:"Jobs",revision:"1",structure_revision:1,refreshed_at:1,columns:[{id:"company",title:"Company",kind:"company",width:200},{id:"role",title:"Role",kind:"role",width:200}],rows:[],row_ids:[],properties:{gridProperties:{rowCount:0,columnCount:2}}})),api:{post:vi.fn()},downloadFile:vi.fn()}))
vi.mock("./sourcing-grid",()=>({SheetGrid:()=>null}))
vi.mock("./sourcing-progress",()=>({default:()=>null,useSourcingProgress:()=>({progress:null,run:vi.fn()})}))
afterEach(()=>{cleanup();sessionStorage.clear();vi.clearAllMocks()})
function draw(id:number){
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 return render(<PageStateProvider scope="sheet-test"><QueryClientProvider client={client}><SourcingEditor key={id} tab={{id,account_id:null,title:"Jobs",header_row:1,refreshed_at:1}} initialDay="2026-10-15" onDirty={()=>undefined}/></QueryClientProvider></PageStateProvider>)
}
it("restores sheet filters and sorting only for their original tab",async()=>{
 draw(1)
 fireEvent.click(screen.getByRole("button",{name:"Find and filter sheet"}))
 fireEvent.change(await screen.findByLabelText("Find in sheet"),{target:{value:"Acme"}})
 fireEvent.change(screen.getByLabelText("Filter value"),{target:{value:"Engineer"}})
 fireEvent.change(screen.getByLabelText("Filter column"),{target:{value:"1"}})
 fireEvent.change(screen.getByLabelText("Sort column"),{target:{value:"1"}})
 fireEvent.change(screen.getByLabelText("Sort direction"),{target:{value:"desc"}})
 cleanup();draw(2)
 expect(screen.queryByLabelText("Find in sheet")).toBeNull()
 cleanup();draw(1)
 expect(await screen.findByLabelText("Find in sheet")).toHaveProperty("value","Acme")
 expect(screen.getByLabelText("Filter value")).toHaveProperty("value","Engineer")
 expect(screen.getByLabelText("Filter column")).toHaveProperty("value","1")
 expect(screen.getByLabelText("Sort column")).toHaveProperty("value","1")
 expect(screen.getByLabelText("Sort direction")).toHaveProperty("value","desc")
})

it("ignores malformed saved sheet preferences",async()=>{
 sessionStorage.setItem('offerpath.page-state.v1:'+JSON.stringify(["sheet-test","/sourcing","tab:1:sheetView"]),JSON.stringify(JSON.stringify({find:"stale",filter:"",filterColumn:0,sortColumn:0,direction:["asc"]})))
 draw(1)
 fireEvent.click(screen.getByRole("button",{name:"Find and filter sheet"}))
 expect(await screen.findByLabelText("Find in sheet")).toHaveProperty("value","")
 expect(screen.getByLabelText("Sort direction")).toHaveProperty("value","none")
})
