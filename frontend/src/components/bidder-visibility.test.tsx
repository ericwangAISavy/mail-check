import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {api,request} from "@/lib/api"
import BidderVisibility from "./bidder-visibility"
vi.mock("@/lib/api",()=>({api:{post:vi.fn()},request:vi.fn()}))
let client:QueryClient
const mount=()=>{client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});render(<QueryClientProvider client={client}><BidderVisibility/></QueryClientProvider>)}
afterEach(()=>{cleanup();client.clear();vi.resetAllMocks()})
it('requires explicit saving and sends the reviewed visibility revision',async()=>{
 vi.mocked(request).mockResolvedValue({bidders:[{id:1,name:'Alex',payment_visible:1,other_work_visible:0,visibility_revision:4}]})
 vi.mocked(api.post).mockResolvedValue({ok:true})
 mount()
 const payment=await screen.findByRole('checkbox',{name:'Payment visible for Alex'})
 expect((payment as HTMLInputElement).checked).toBe(true)
 fireEvent.click(payment)
 fireEvent.click(screen.getByRole('checkbox',{name:'Other bidders work visible for Alex'}))
 expect(api.post).not.toHaveBeenCalled()
 fireEvent.click(screen.getByRole('button',{name:'Save visibility'}))
 await waitFor(()=>expect(api.post).toHaveBeenCalledWith('/api/payments/bidders/1/visibility',{payment_visible:false,other_work_visible:true,expected_revision:4}))
})
it('preserves drafts on failure and lets admins reload saved options',async()=>{
 vi.mocked(request).mockResolvedValue({bidders:[{id:1,name:'Alex',payment_visible:1,other_work_visible:0,visibility_revision:0}]})
 vi.mocked(api.post).mockRejectedValue(new Error('Visibility changed elsewhere'))
 mount()
 const payment=await screen.findByRole('checkbox',{name:'Payment visible for Alex'})
 fireEvent.click(payment);fireEvent.click(screen.getByRole('button',{name:'Save visibility'}))
 await screen.findByRole('alert')
 expect((payment as HTMLInputElement).checked).toBe(false)
 fireEvent.click(screen.getByRole('button',{name:'Reload saved options'}))
 await waitFor(()=>expect((payment as HTMLInputElement).checked).toBe(true))
})
