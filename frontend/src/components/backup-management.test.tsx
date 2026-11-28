import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor,within} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {api,request,getWorkspaceIdentity} from "@/lib/api"
import BackupManagement from "./backup-management"
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{post:vi.fn()},getWorkspaceIdentity:vi.fn(()=>"legacy")}))
const clients:QueryClient[]=[]
const status={enabled:true,retain:7,folder:"/backups",running:false,last_error:null,last_success:"2026-10-29T12:00:00Z",next_due:null,archives:[{name:"offerpath-test.zip",size:1024,created_at:"2026-10-29T12:00:00Z",automatic:false}]}
function mount(value=status){vi.mocked(getWorkspaceIdentity).mockReturnValue("legacy");vi.mocked(request).mockResolvedValue(value);const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client);render(<QueryClientProvider client={client}><BackupManagement/></QueryClientProvider>)}

it('keeps archive history off the page until its browser is opened',async()=>{
 mount();const browse=await screen.findByRole('button',{name:'Browse backups'})
 expect(screen.queryByText('offerpath-test.zip')).toBeNull()
 expect(screen.queryByRole('dialog')).toBeNull()
 fireEvent.click(browse)
 expect(await screen.findByRole('dialog',{name:'Available backups'})).toBeTruthy()
 expect(screen.getByText('offerpath-test.zip')).toBeTruthy()
})
it('returns keyboard focus to Browse backups after closing the archive dialog',async()=>{
 mount();const browse=await screen.findByRole('button',{name:'Browse backups'})
 browse.focus();fireEvent.click(browse)
 const dialog=await screen.findByRole('dialog',{name:'Available backups'})
 fireEvent.keyDown(dialog,{key:'Escape'})
 await waitFor(()=>expect(screen.queryByRole('dialog')).toBeNull())
 await waitFor(()=>expect(document.activeElement).toBe(browse))
})
it('sorts backup history newest first, paginates it and resets the page on type changes',async()=>{
 const archives=Array.from({length:18},(_,i)=>({name:`backup-${String(i).padStart(2,'0')}.zip`,created_at:`2026-11-${String(i+1).padStart(2,'0')}T12:00:00Z`,size:1024,automatic:i%2===0}))
 mount({...status,archives})
 fireEvent.click(await screen.findByRole('button',{name:'Browse backups'}))
 const dialog=await screen.findByRole('dialog',{name:'Available backups'})
 expect(within(dialog).getAllByRole('button',{name:/^Download /})).toHaveLength(8)
 expect(within(dialog).getByText('backup-17.zip')).toBeTruthy()
 expect(within(dialog).queryByText('backup-00.zip')).toBeNull()
 fireEvent.click(within(dialog).getByRole('button',{name:'Next backups'}))
 expect(within(dialog).getByText('Page 2 of 3')).toBeTruthy()
 fireEvent.change(within(dialog).getByLabelText('Backup type'),{target:{value:'automatic'}})
 expect(within(dialog).getByText('Page 1 of 2')).toBeTruthy()
 expect(within(dialog).getByText('backup-16.zip')).toBeTruthy()
 expect(within(dialog).queryByText('backup-17.zip')).toBeNull()
})
afterEach(()=>{cleanup();clients.splice(0).forEach(c=>c.clear());vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals()})
it("shows archive sensitivity, history and restore instructions",async()=>{mount();await screen.findByRole("button",{name:"Browse backups"});expect(screen.getByText(/Backups contain private mail/i)).toBeTruthy();expect(screen.getByText(/backup inspect FILE.zip/)).toBeTruthy();fireEvent.click(screen.getByRole("button",{name:"Browse backups"}));expect(screen.getByText(/1 KB/)).toBeTruthy()})
it("creates a backup and saves retention settings",async()=>{mount();await screen.findByRole("button",{name:"Browse backups"});fireEvent.click(screen.getByRole("button",{name:"Create backup"}));await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/backups/create",{}));await screen.findByText("Backup created.");fireEvent.click(screen.getByText("Automatic backups",{exact:true}));fireEvent.change(screen.getByLabelText("Automatic backups to keep"),{target:{value:"3"}});fireEvent.click(screen.getByRole("button",{name:"Save backup settings"}));await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/backups/settings",{enabled:true,retain:3}))})
it("protects backup settings during a pending save and keeps them after failure",async()=>{
  let rejectSave!:(error:Error)=>void
  vi.mocked(api.post).mockImplementation(()=>new Promise((_,reject)=>{rejectSave=reject}))
  mount();await screen.findByRole("button",{name:"Browse backups"})
  fireEvent.click(screen.getByText("Automatic backups",{exact:true}))
  fireEvent.change(screen.getByLabelText("Automatic backups to keep"),{target:{value:"3"}})
  fireEvent.click(screen.getByRole("button",{name:"Save backup settings"}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/backups/settings",{enabled:true,retain:3}))
  expect(screen.getByLabelText("Automatic backups to keep")).toHaveProperty("disabled",true)
  expect(screen.getByLabelText("Daily automatic backups")).toHaveProperty("disabled",true)
  rejectSave(new Error("Could not save backup settings"))
  await screen.findByText("Could not save backup settings")
  expect(screen.getByLabelText("Automatic backups to keep")).toHaveProperty("value","3")
  expect(screen.getByLabelText("Automatic backups to keep")).toHaveProperty("disabled",false)
})
it("starts a native download using a guarded server ticket",async()=>{
  mount();await screen.findByRole("button",{name:"Browse backups"})
  const url="/api/admin/backups/file/offerpath-test.zip?ticket=one-use&workspace=legacy"
  vi.mocked(api.post).mockResolvedValue({url})
  let href="",filename=""
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(function(this:HTMLAnchorElement){href=this.getAttribute("href")||"";filename=this.download})
  fireEvent.click(screen.getByRole("button",{name:"Download latest backup"}))
  await waitFor(()=>expect(click).toHaveBeenCalledOnce())
  expect(api.post).toHaveBeenCalledWith("/api/admin/backups/download-ticket/offerpath-test.zip",{})
  expect(href).toBe(url);expect(filename).toBe("offerpath-test.zip")
  expect(document.querySelector("a[download]")).toBeNull()
})
it("rejects a ticket if the workspace changes",async()=>{
  mount();await screen.findByRole("button",{name:"Browse backups"})
  vi.mocked(api.post).mockImplementation(async()=>{vi.mocked(getWorkspaceIdentity).mockReturnValue("other");return {url:"/api/admin/backups/file/offerpath-test.zip?ticket=one-use"} as never})
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{})
  fireEvent.click(screen.getByRole("button",{name:"Download latest backup"}))
  await screen.findByText("Workspace changed. Reload before continuing.")
  expect(click).not.toHaveBeenCalled()
})
it.each(["https://example.com/api/admin/backups/file/offerpath-test.zip?ticket=x","//example.com/api/admin/backups/file/offerpath-test.zip?ticket=x","/api/admin/backups/file/../users?ticket=x","/api/admin/backups/file/other.zip?ticket=x","/api/admin/backups/file/offerpath-test.zip"])("rejects invalid download URL %s",async url=>{
  mount();await screen.findByRole("button",{name:"Browse backups"});vi.mocked(api.post).mockResolvedValue({url})
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{})
  fireEvent.click(screen.getByRole("button",{name:"Download latest backup"}))
  await screen.findByText("OfferPath returned an unexpected backup response. Please try again.")
  expect(click).not.toHaveBeenCalled()
})
it("reports creation and ticket errors",async()=>{
  mount();await screen.findByRole("button",{name:"Browse backups"});vi.mocked(api.post).mockRejectedValue(new Error("Backup disk is full"))
  fireEvent.click(screen.getByRole("button",{name:"Create backup"}));await screen.findByText("Backup disk is full")
  vi.mocked(api.post).mockRejectedValue(new Error("Backup no longer exists"))
  fireEvent.click(screen.getByRole("button",{name:"Download latest backup"}));await screen.findByText("Backup no longer exists")
})
