import {afterEach,beforeEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {MemoryRouter} from "react-router-dom"
import {ToastProvider} from "@/components/common"
import JobLinks from "./job-links"
import {copyPaymentReport} from "@/lib/payment-report"

vi.mock("@/lib/payment-report",()=>({copyPaymentReport:vi.fn().mockResolvedValue(undefined)}))
const clients:QueryClient[]=[]
const job={id:"opaque-job",company:"Acme",role:"Engineer",link:"https://jobs.test/1"}
beforeEach(()=>{
 vi.stubGlobal('ResizeObserver',class{observe(){}unobserve(){}disconnect(){}})
 vi.spyOn(Element.prototype,'clientWidth','get').mockReturnValue(1200)
 vi.spyOn(Element.prototype,'clientHeight','get').mockReturnValue(500)
 Element.prototype.scrollTo=vi.fn()
 Element.prototype.scrollIntoView=vi.fn()
 const query=Element.prototype.querySelector
 vi.spyOn(Element.prototype,'querySelector').mockImplementation(function(this:Element,selector:string){return query.call(this,selector.startsWith('&')?':scope'+selector.slice(1):selector)} as typeof Element.prototype.querySelector)
})
afterEach(()=>{cleanup();clients.forEach(client=>client.clear());clients.length=0;vi.restoreAllMocks();vi.clearAllMocks();vi.unstubAllGlobals()})
function mount(){
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client)
 render(<QueryClientProvider client={client}><MemoryRouter><ToastProvider><JobLinks/></ToastProvider></MemoryRouter></QueryClientProvider>)
}
function serve(incomplete=false){
 const fetch=vi.fn(async(_url:string)=>new Response(JSON.stringify({items:[job],next_cursor:null,incomplete}),{headers:{"content-type":"application/json"}}))
 vi.stubGlobal("fetch",fetch)
 return fetch
}
it("searches company role and links and copies rows in sheet paste format",async()=>{
 const fetch=serve()
 mount()
 await screen.findByRole('gridcell',{name:'Acme'})
 expect(screen.queryByText("Account")).toBeNull()
 fireEvent.mouseDown(screen.getByRole('gridcell',{name:'Acme'}),{button:0,buttons:1})
 fireEvent.mouseUp(document)
 fireEvent.click(screen.getByRole("button",{name:"Copy selected rows"}))
 await waitFor(()=>expect(copyPaymentReport).toHaveBeenCalledWith("Acme\tEngineer\thttps://jobs.test/1"))
 fireEvent.click(screen.getByRole("button",{name:"Copy links"}))
 await waitFor(()=>expect(copyPaymentReport).toHaveBeenCalledWith(job.link))
 fireEvent.change(screen.getByLabelText("Search job links"),{target:{value:"senior engineer"}})
 fireEvent.submit(screen.getByLabelText("Search job links").closest("form")!)
 await waitFor(()=>expect(String(fetch.mock.lastCall?.[0])).toContain("q=senior+engineer"))
})
it('drag-selects multiple compact rows and copies them like the sourcing sheet',async()=>{
 vi.stubGlobal('fetch',vi.fn(async()=>new Response(JSON.stringify({items:[job,{...job,id:'second',company:'Beta',link:'https://jobs.test/2'}],next_cursor:null,incomplete:false}),{headers:{'content-type':'application/json'}})))
 mount()
 const first=await screen.findByRole('gridcell',{name:job.link})
 const last=await screen.findByRole('gridcell',{name:'https://jobs.test/2'})
 fireEvent.mouseDown(first,{button:0,buttons:1})
 fireEvent.mouseMove(last,{buttons:1,clientY:35})
 fireEvent.mouseUp(document)
 const clipboardData={setData:vi.fn()}
 fireEvent.copy(screen.getByRole('grid',{name:'Shared job links'}),{clipboardData})
 expect(clipboardData.setData).toHaveBeenCalledWith('text/plain','Acme\tEngineer\thttps://jobs.test/1\nBeta\tEngineer\thttps://jobs.test/2')
 fireEvent.click(screen.getByRole('button',{name:'Copy links'}))
 await waitFor(()=>expect(copyPaymentReport).toHaveBeenCalledWith('https://jobs.test/1\nhttps://jobs.test/2'))
 fireEvent.keyDown(screen.getByRole('grid'),{key:'Delete'})
 expect(screen.getByRole('gridcell',{name:'Acme'})).toBeTruthy()
 fireEvent.doubleClick(screen.getByRole('gridcell',{name:'Acme'}))
 expect(screen.queryByRole('textbox',{name:'Edit cell'})).toBeNull()
})
it("warns when a workspace cannot be searched",async()=>{
 serve(true)
 mount()
 expect(await screen.findByRole("alert")).toBeTruthy()
 expect(await screen.findByRole('gridcell',{name:'Acme'})).toBeTruthy()
})
it('filters by job date with the sourcing controls and keeps the date when searching',async()=>{
 const fetch=serve()
 mount()
 await screen.findByRole('grid',{name:'Shared job links'})
 fireEvent.change(screen.getByLabelText('Job date'),{target:{value:'2026-11-23'}})
 await waitFor(()=>expect(String(fetch.mock.lastCall?.[0])).toContain('day=2026-11-23'))
 fireEvent.click(screen.getByRole('button',{name:'Previous day'}))
 await waitFor(()=>expect(String(fetch.mock.lastCall?.[0])).toContain('day=2026-11-22'))
 fireEvent.click(screen.getByRole('button',{name:'Next day'}))
 await waitFor(()=>expect(String(fetch.mock.lastCall?.[0])).toContain('day=2026-11-23'))
 fireEvent.change(screen.getByLabelText('Search job links'),{target:{value:'engineer'}})
 fireEvent.submit(screen.getByLabelText('Search job links').closest('form')!)
 await waitFor(()=>{
  expect(String(fetch.mock.lastCall?.[0])).toContain('q=engineer')
  expect(String(fetch.mock.lastCall?.[0])).toContain('day=2026-11-23')
 })
 fireEvent.click(screen.getByRole('button',{name:'All dates'}))
 await waitFor(()=>{
  expect(String(fetch.mock.lastCall?.[0])).toContain('q=engineer')
  expect(new URL(String(fetch.mock.lastCall?.[0]),'http://localhost').searchParams.get('day')).toBe('')
 })
})
it('returns to the first results page when changing the date',async()=>{
 const fetch=vi.fn(async(url:string)=>new Response(JSON.stringify({items:[job],next_cursor:new URL(url,'http://localhost').searchParams.get('cursor')?null:'next-page',incomplete:false}),{headers:{'content-type':'application/json'}}))
 vi.stubGlobal('fetch',fetch)
 mount()
 await screen.findByRole('grid',{name:'Shared job links'})
 await waitFor(()=>expect((screen.getByRole('button',{name:'Next'}) as HTMLButtonElement).disabled).toBe(false))
 fireEvent.click(screen.getByRole('button',{name:'Next'}))
 await screen.findByText('Page 2')
 fireEvent.change(screen.getByLabelText('Job date'),{target:{value:'2026-11-23'}})
 await waitFor(()=>{
  const query=new URL(String(fetch.mock.lastCall?.[0]),'http://localhost').searchParams
  expect(query.get('day')).toBe('2026-11-23')
  expect(query.get('cursor')).toBe('')
 })
 expect(screen.getByText('Page 1')).toBeTruthy()
})
