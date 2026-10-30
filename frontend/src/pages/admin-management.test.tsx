import {afterEach,expect,it,vi} from "vitest"
import {cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react"
import {QueryClient,QueryClientProvider} from "@tanstack/react-query"
import {api,request} from "@/lib/api"
import AdminManagement from "./admin-management"
const state=vi.hoisted(()=>({owner:true}))
vi.mock("@/components/auth",()=>({useAuth:()=>({role:"admin",session:{is_owner:state.owner,workspace_id:"legacy"}})}))
vi.mock("@/lib/api",()=>({request:vi.fn(),api:{post:vi.fn()},setWorkspaceIdentity:vi.fn(),getWorkspaceIdentity:vi.fn()}))
const clients:QueryClient[]=[]
afterEach(()=>{cleanup();clients.splice(0).forEach(c=>c.clear());vi.resetAllMocks();vi.restoreAllMocks();state.owner=true})
function mount(){
  vi.mocked(request).mockImplementation(async url=>url==="/api/admin/backups"?{enabled:true,retain:7,folder:"/backups",running:false,last_error:null,last_success:null,next_due:null,archives:[]} as never:url==="/api/admin/users"?{max_workspaces:4,admins:[{id:1,username:"owner",owner:1,enabled:1,workspace_id:"legacy",workspace_name:"Original workspace",health:"running",online:true},{id:2,username:"alice",owner:0,enabled:1,workspace_id:"alice",workspace_name:"Alice workspace",health:"running",online:false}]} as never:{events:[]} as never)
  const client=new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}});clients.push(client)
  render(<QueryClientProvider client={client}><AdminManagement/></QueryClientProvider>)
}
it("creates an admin with workspace and temporary password",async()=>{
  vi.mocked(api.post).mockResolvedValue({ok:true})
  mount();await screen.findByText("Alice workspace")
  fireEvent.change(screen.getByLabelText("Username"),{target:{value:"bob"}})
  fireEvent.change(screen.getByLabelText("Workspace name"),{target:{value:"Bob workspace"}})
  fireEvent.change(screen.getByLabelText("Temporary password"),{target:{value:"temporary-pass-123"}})
  fireEvent.click(screen.getByRole("button",{name:"Create admin"}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/users",{username:"bob",workspace_name:"Bob workspace",password:"temporary-pass-123"}))
})
it("suspends access without deleting the workspace",async()=>{
  vi.spyOn(window,"confirm").mockReturnValue(true)
  vi.mocked(api.post).mockResolvedValue({ok:true})
  mount();fireEvent.click(await screen.findByRole("button",{name:"Suspend"}))
  await waitFor(()=>expect(api.post).toHaveBeenCalledWith("/api/admin/users/2",{enabled:false}))
  expect(screen.queryByRole("button",{name:"Delete"})).toBeNull()
})
it("does not offer owner controls or load other workspaces to an added admin",async()=>{
  state.owner=false;mount()
  expect(screen.getByRole("heading",{name:"Owner access required"})).toBeTruthy()
  expect(request).not.toHaveBeenCalled()
  expect(screen.queryByRole("button",{name:"Create admin"})).toBeNull()
})

it("shows browser presence separately from workspace server health",async()=>{
  mount()
  await screen.findByText("Alice workspace")
  expect(screen.getByText("Online")).toBeTruthy()
  expect(screen.getByText("Offline")).toBeTruthy()
})
