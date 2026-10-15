import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import SourcingPage from "./sourcing"
import { api } from "@/lib/api"
vi.mock("@/components/auth",()=>({useAuth:()=>({role:'admin'})}))
vi.mock("@/components/sourcing-grid",()=>({SheetGrid:({changes,onChange,disabled}:{changes:{value:string}[];onChange:(changes:unknown[])=>void;disabled:boolean})=><div><output aria-label="Draft value">{changes[0]?.value||'No draft'}</output><button disabled={disabled} onClick={()=>onChange([{row:1,col:0,value:'New company'}])}>Edit company</button></div>}))
const snapshot={rows:[[],[{value:'Acme',display:'Acme',formula:false,link:''}]],title:'Profile',revision:'one',refreshed_at:1,properties:{gridProperties:{rowCount:100,columnCount:3}}}
const index={books:[{id:1,bidder_id:1,name:'Alex',title:'Applications',spreadsheet_id:'abc',tabs:[{id:1,sheet_id:12,account_id:1,title:'Profile',header_row:1}]}]}
const clients:QueryClient[]=[]
beforeEach(()=>{vi.stubGlobal('fetch',vi.fn(async (url:string)=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>url==='/api/sourcing'?index:snapshot})))})
afterEach(()=>{cleanup();clients.splice(0).forEach(c=>c.clear());vi.restoreAllMocks();vi.unstubAllGlobals()})
function mount(){const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client);render(<QueryClientProvider client={client}><MemoryRouter><SourcingPage/></MemoryRouter></QueryClientProvider>)}
it('keeps failed-save drafts visible and prevents tab changes',async()=>{
  vi.spyOn(api,'post').mockRejectedValue(new Error('Sheet changed in Google.'))
  mount();fireEvent.click(await screen.findByRole('button',{name:'Edit company'}))
  await screen.findByText(/Sheet changed in Google/,{}, {timeout:3000})
  expect(screen.getByLabelText('Draft value').textContent).toBe('New company')
  expect(screen.getByRole('tab',{name:'Profile'}).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('button',{name:'Edit company'}).hasAttribute('disabled')).toBe(true)
  expect(screen.getByRole('button',{name:'Download draft'})).toBeTruthy()
})
it('undoes an acknowledged edit through another revision-checked write',async()=>{
  const post=vi.spyOn(api,'post').mockResolvedValue({...snapshot,revision:'two',rows:[[],[{value:'New company',display:'New company',formula:false,link:''}]]})
  mount();fireEvent.click(await screen.findByRole('button',{name:'Edit company'}))
  await waitFor(()=>expect(post).toHaveBeenCalledTimes(1),{timeout:2500})
  await screen.findByText('Saved to Google')
  fireEvent.click(screen.getByRole('button',{name:'Undo edit'}))
  await waitFor(()=>expect(post).toHaveBeenCalledTimes(2),{timeout:2500})
  expect(post.mock.calls[1][1]).toMatchObject({revision:'two',changes:[{row:1,col:0,value:'Acme'}]})
})
it('invalidates positional undo after Google changes the sheet externally',async()=>{
  vi.spyOn(api,'post').mockResolvedValue({...snapshot,revision:'two',rows:[[],[{value:'New company',display:'New company',formula:false,link:''}]]})
  mount();fireEvent.click(await screen.findByRole('button',{name:'Edit company'}))
  await screen.findByText('Saved to Google',{}, {timeout:3000})
  expect(screen.getByRole('button',{name:'Undo edit'}).hasAttribute('disabled')).toBe(false)
  vi.mocked(fetch).mockImplementation(async ()=>({ok:true,headers:new Headers({'content-type':'application/json'}),json:async()=>({...snapshot,revision:'external-sort',rows:[[],[{value:'Another job',display:'Another job',formula:false,link:''}]]})}) as Response)
  fireEvent.click(screen.getByRole('button',{name:'Refresh sheet'}))
  await waitFor(()=>expect(screen.getByRole('button',{name:'Undo edit'}).hasAttribute('disabled')).toBe(true))
})
