import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {api,request,getWorkspaceIdentity} from "@/lib/api"
import BackupManagement from "./backup-management"
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{post:vi.fn()},getWorkspaceIdentity:vi.fn(()=>"legacy")}))
const clients:QueryClient[]=[]
const status={enabled:true,retain:7,folder:"/backups",running:false,last_error:null,last_success:"2026-10-29T12:00:00Z",next_due:null,archives:[{name:"offerpath-test.zip",size:1024,created_at:"2026-10-29T12:00:00Z",automatic:false}]}
function mount(){vi.mocked(getWorkspaceIdentity).mockReturnValue("legacy");vi.mocked(request).mockResolvedValue(status);const client=new QueryClient({defaultOptions:{queries:{retry:false}}});clients.push(client);render(<QueryClientProvider client={client}><BackupManagement/></QueryClientProvider>)}
afterEach(()=>{cleanup();clients.splice(0).forEach(c=>c.clear());vi.restoreAllMocks();vi.resetAllMocks();vi.unstubAllGlobals()})
it("shows archive sensitivity, history and restore instructions",async()=>{mount();await screen.findByText("offerpath-test.zip");expect(screen.getByText(/plain ZIP/i)).toBeTruthy();expect(screen.getByText(/backup inspect FILE.zip/)).toBeTruthy();expect(screen.getByText(/1 KB/)).toBeTruthy()})
it("creates a backup and saves retention settings",async()=>{mount();await screen.findByText("offerpath-test.zip");fireEvent.click(screen.getByRole("button",{name:"Create backup"}));await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/backups/create",{}));await screen.findByText("Backup created.");fireEvent.change(screen.getByLabelText("Automatic backups to keep"),{target:{value:"3"}});fireEvent.click(screen.getByRole("button",{name:"Save backup settings"}));await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/backups/settings",{enabled:true,retain:3}))})
it("starts a native download using a guarded server ticket",async()=>{
  mount();await screen.findByText("offerpath-test.zip")
  const url="/api/admin/backups/file/offerpath-test.zip?ticket=one-use&workspace=legacy"
  vi.mocked(api.post).mockResolvedValue({url})
  let href="",filename=""
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(function(this:HTMLAnchorElement){href=this.getAttribute("href")||"";filename=this.download})
  fireEvent.click(screen.getByRole("button",{name:"Download offerpath-test.zip"}))
  await waitFor(()=>expect(click).toHaveBeenCalledOnce())
  expect(api.post).toHaveBeenCalledWith("/api/admin/backups/download-ticket/offerpath-test.zip",{})
  expect(href).toBe(url);expect(filename).toBe("offerpath-test.zip")
  expect(document.querySelector("a[download]")).toBeNull()
})
it("rejects a ticket if the workspace changes",async()=>{
  mount();await screen.findByText("offerpath-test.zip")
  vi.mocked(api.post).mockImplementation(async()=>{vi.mocked(getWorkspaceIdentity).mockReturnValue("other");return {url:"/api/admin/backups/file/offerpath-test.zip?ticket=one-use"} as never})
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{})
  fireEvent.click(screen.getByRole("button",{name:"Download offerpath-test.zip"}))
  await screen.findByText("Workspace changed. Reload before continuing.")
  expect(click).not.toHaveBeenCalled()
})
it.each(["https://example.com/api/admin/backups/file/offerpath-test.zip?ticket=x","//example.com/api/admin/backups/file/offerpath-test.zip?ticket=x","/api/admin/backups/file/../users?ticket=x","/api/admin/backups/file/other.zip?ticket=x","/api/admin/backups/file/offerpath-test.zip"])("rejects invalid download URL %s",async url=>{
  mount();await screen.findByText("offerpath-test.zip");vi.mocked(api.post).mockResolvedValue({url})
  const click=vi.spyOn(HTMLAnchorElement.prototype,"click").mockImplementation(()=>{})
  fireEvent.click(screen.getByRole("button",{name:"Download offerpath-test.zip"}))
  await screen.findByText("OfferPath returned an unexpected backup response. Please try again.")
  expect(click).not.toHaveBeenCalled()
})
it("reports creation and ticket errors",async()=>{
  mount();await screen.findByText("offerpath-test.zip");vi.mocked(api.post).mockRejectedValue(new Error("Backup disk is full"))
  fireEvent.click(screen.getByRole("button",{name:"Create backup"}));await screen.findByText("Backup disk is full")
  vi.mocked(api.post).mockRejectedValue(new Error("Backup no longer exists"))
  fireEvent.click(screen.getByRole("button",{name:"Download offerpath-test.zip"}));await screen.findByText("Backup no longer exists")
})
